import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from loguru import logger

from db_clients import ApiRequestLog

# Swagger UI and its schema are documentation pages, not API calls.
SKIPPED_PATHS = frozenset({"/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json"})
# The Docker healthcheck sends this User-Agent every 15 seconds; logging it would bury the real calls.
HEALTHCHECK_USER_AGENT = "docker-healthcheck"
# Guest messages are capped at 2,000 characters, so real bodies stay far below this.
MAX_BODY_BYTES = 64 * 1024


def _header(headers: list[tuple[bytes, bytes]], name: bytes) -> str | None:
    for key, value in headers:
        if key == name:
            return value.decode("latin-1")
    return None


def _decode_body(raw: bytearray, content_type: str | None) -> Any:
    if not raw:
        return None
    text = raw.decode("utf-8", errors="replace")
    if content_type and "json" in content_type:
        try:
            return json.loads(text)
        except ValueError:
            pass
    return text


class ApiRequestLogMiddleware:
    """Stores every HTTP call — request body, status and response body — through the request log repository.

    Pure ASGI instead of BaseHTTPMiddleware, so the bodies are copied as they stream through rather than
    re-read or rebuilt. The write happens after the response has been sent, and a failed write is logged,
    never raised: the request log must not be able to break the API.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        headers = scope.get("headers", []) if scope["type"] == "http" else []
        if (
            scope["type"] != "http"
            or scope["path"] in SKIPPED_PATHS
            or _header(headers, b"user-agent") == HEALTHCHECK_USER_AGENT
        ):
            await self.app(scope, receive, send)
            return

        started = time.perf_counter()
        request_body = bytearray()
        response_body = bytearray()
        response_start: dict = {}

        async def receive_and_copy():
            message = await receive()
            if message["type"] == "http.request":
                request_body.extend(message.get("body", b"")[: MAX_BODY_BYTES - len(request_body)])
            return message

        async def send_and_copy(message):
            if message["type"] == "http.response.start":
                response_start.update(message)
            elif message["type"] == "http.response.body":
                response_body.extend(message.get("body", b"")[: MAX_BODY_BYTES - len(response_body)])
            await send(message)

        try:
            await self.app(scope, receive_and_copy, send_and_copy)
        finally:
            response_headers = response_start.get("headers", [])
            client = scope.get("client")
            log = ApiRequestLog(
                id=uuid.uuid4().hex,
                request_id=_header(response_headers, b"x-request-id"),
                created_at=datetime.now(timezone.utc),
                method=scope["method"],
                path=scope["path"],
                query=scope.get("query_string", b"").decode("latin-1"),
                client_ip=client[0] if client else None,
                user_agent=_header(headers, b"user-agent"),
                status_code=response_start.get("status", 500),
                latency_ms=round((time.perf_counter() - started) * 1000, 1),
                request_body=_decode_body(request_body, _header(headers, b"content-type")),
                response_body=_decode_body(response_body, _header(response_headers, b"content-type")),
            )
            await self._save(scope, log)

    @staticmethod
    async def _save(scope, log: ApiRequestLog) -> None:
        request_log = getattr(scope["app"].state, "request_log", None)
        if request_log is None:
            return
        try:
            await request_log.save(log)
        except Exception as exc:
            logger.bind(request_id=log.request_id, error=str(exc)).warning("api_request_log_failed")
