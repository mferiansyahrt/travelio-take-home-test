import re
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Annotated

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from loguru import logger
from pydantic import BaseModel, Field, StringConstraints
from starlette.exceptions import HTTPException as StarletteHTTPException

from agents.message_classifier_agent import ConversationTurn, Entities, Intent, MessageClassifierAgent, Urgency
from config import settings
from db_clients import ClassificationRecord, build_repository
from llm_clients import MockLLMClient
from main_processor import MainProcessor
from utils.logger import setup_logger

setup_logger(level=settings.LOG_LEVEL, json_logs=settings.LOG_JSON)

# Caller-supplied request ids end up in logs, so only a short, safe format is accepted.
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

# Error codes for HTTP errors raised by the framework itself (unknown route, wrong method).
HTTP_ERROR_CODES = {404: "not_found", 405: "method_not_allowed"}

SAMPLE_MESSAGE = "Halo, saya mau booking unit 2BR di Kemang dari tgl 12 sampai 15 Maret, masih ada yg available?"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Build the object graph once per process: repository → agent (with the provided mock LLM) → processor."""
    repository = await build_repository(
        settings.REPOSITORY_BACKEND,
        mongo_uri=settings.MONGO_URI,
        mongo_db_name=settings.MONGO_DB_NAME,
        mongo_collection=settings.MONGO_COLLECTION,
    )
    agent = MessageClassifierAgent(
        MockLLMClient(),
        timeout_seconds=settings.LLM_TIMEOUT_SECONDS,
        max_retries=settings.LLM_MAX_RETRIES,
        retry_backoff_seconds=settings.LLM_RETRY_BACKOFF_SECONDS,
        confidence_threshold=settings.CONFIDENCE_THRESHOLD,
        max_context_messages=settings.MAX_CONTEXT_MESSAGES,
    )
    app.state.processor = MainProcessor(agent, repository, timezone_name=settings.TIMEZONE)
    logger.bind(
        repository_backend=settings.REPOSITORY_BACKEND,
        llm_timeout_seconds=settings.LLM_TIMEOUT_SECONDS,
        llm_max_retries=settings.LLM_MAX_RETRIES,
    ).info("service_started")

    yield

    await repository.close()
    logger.info("service_stopped")


# ── FastAPI metadata ──────────────────────────────────────────────────────
app = FastAPI(
    title=settings.APP_NAME,
    description=(
        "Classifies guest chat messages (Bahasa Indonesia / English) into routing intents with structured entities.\n\n"
        "**Note:** the LLM is the provided `MockLLMClient`, which ignores the prompt and picks intent, urgency and "
        "confidence at random. The same message returns a different intent on every call. This service demonstrates "
        "the pipeline (timeouts, retries, validation, guardrails, persistence), not classification quality."
    ),
    version=settings.APP_VERSION,
    lifespan=lifespan,
)


# ── Pydantic models ───────────────────────────────────────────────────────
class ClassifyMessageInput(BaseModel):
    message: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)] = Field(
        examples=[SAMPLE_MESSAGE]
    )
    conversation_context: list[ConversationTurn] = Field(
        default_factory=list,
        max_length=50,
        description="Optional earlier turns, oldest first. Only the most recent ones are sent to the LLM.",
    )


class ClassifyMessageOutput(BaseModel):
    id: str = Field(description="Id of the stored record; fetch it with GET /classifications/{id}.")
    request_id: str
    intent: Intent
    entities: Entities
    urgency: Urgency
    confidence: float
    needs_human: bool
    needs_human_reasons: list[str]
    reason: str | None
    unrecognized_intent: str | None
    attempts: int
    latency_ms: float
    persisted: bool
    created_at: datetime


class FieldError(BaseModel):
    location: str = Field(examples=["body.message"])
    message: str


class ErrorDetail(BaseModel):
    code: str
    message: str
    fields: list[FieldError] | None = Field(default=None, description="Only for 422: the invalid request fields.")


class ErrorOutput(BaseModel):
    """Body of every error response (4xx and 5xx)."""

    error: ErrorDetail
    request_id: str
    id: str | None = None
    attempts: int | None = None
    persisted: bool | None = None
    # Only on 502/504: a message we could not classify must still reach a person.
    needs_human: bool | None = None


def error_response(
    status_code: int,
    code: str,
    message: str,
    request_id: str,
    *,
    fields: list[FieldError] | None = None,
    headers: dict[str, str] | None = None,
    **extra,
) -> JSONResponse:
    body = ErrorOutput(error=ErrorDetail(code=code, message=message, fields=fields), request_id=request_id, **extra)
    return JSONResponse(status_code=status_code, content=body.model_dump(mode="json", exclude_none=True), headers=headers)


# ── Dependencies ──────────────────────────────────────────────────────────
def get_processor(request: Request) -> MainProcessor:
    """Overridden in tests with a processor wired to a scripted LLM and an in-memory repository."""
    return request.app.state.processor


# ── Middleware: request id + structured access log ───────────────────────
@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    incoming_request_id = request.headers.get("X-Request-ID", "")
    request_id = incoming_request_id if REQUEST_ID_PATTERN.match(incoming_request_id) else uuid.uuid4().hex
    request.state.request_id = request_id
    started = time.perf_counter()

    # Every log line emitted while handling this request carries the request_id.
    with logger.contextualize(request_id=request_id):
        try:
            response = await call_next(request)
        except Exception:
            logger.exception("unhandled_exception")
            response = error_response(500, "internal_error", "Unexpected server error.", request_id)

        logger.bind(
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            latency_ms=round((time.perf_counter() - started) * 1000, 1),
        ).info("http_request")

    response.headers["X-Request-ID"] = request_id
    return response


# ── Error handlers: framework errors use the same ErrorOutput shape ──────
@app.exception_handler(RequestValidationError)
async def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    fields = [
        FieldError(location=".".join(str(part) for part in error["loc"]), message=error["msg"])
        for error in exc.errors()
    ]
    return error_response(422, "invalid_request", "The request is invalid.", request.state.request_id, fields=fields)


@app.exception_handler(StarletteHTTPException)
async def handle_http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    return error_response(
        exc.status_code,
        HTTP_ERROR_CODES.get(exc.status_code, "http_error"),
        str(exc.detail),
        request.state.request_id,
        headers=exc.headers,
    )


# ── Endpoint: classify message ────────────────────────────────────────────
@app.post(
    "/classify-message",
    response_model=ClassifyMessageOutput,
    responses={
        422: {"model": ErrorOutput, "description": "Invalid request body."},
        502: {"model": ErrorOutput, "description": "The LLM kept returning invalid output after all retries."},
        504: {"model": ErrorOutput, "description": "The LLM timed out on every attempt."},
    },
)
async def classify_message(
    payload: ClassifyMessageInput, request: Request, processor: MainProcessor = Depends(get_processor)
):
    """
    Classify a guest chat message for routing.

    Parameter:
    - **message**: latest guest message (Bahasa Indonesia, English or mixed), 1-2000 characters.
    - **conversation_context** (optional): earlier turns `{role: guest|agent, text}`, oldest first.

    Status codes:
    - `200` classified. Check `needs_human` / `needs_human_reasons` to decide on escalation.
    - `422` invalid request body (`error.fields` lists what is wrong).
    - `502` the LLM kept returning invalid output after all retries.
    - `504` the LLM timed out on every attempt.

    Every call, successful or failed, is stored and can be fetched with `GET /classifications/{id}`.
    """
    request_id = request.state.request_id
    record, persisted = await processor.process(
        message=payload.message,
        conversation_context=payload.conversation_context,
        request_id=request_id,
    )

    if record.status == "failed":
        timed_out = record.error_code == "llm_timeout"
        problem = "timed out" if timed_out else "returned invalid output"
        return error_response(
            504 if timed_out else 502,
            record.error_code,
            f"The language model {problem} on all {record.attempts} attempt(s).",
            request_id,
            id=record.id,
            attempts=record.attempts,
            persisted=persisted,
            needs_human=True,
        )

    return ClassifyMessageOutput(
        **record.output.model_dump(),
        id=record.id,
        request_id=request_id,
        needs_human_reasons=record.needs_human_reasons,
        attempts=record.attempts,
        latency_ms=record.latency_ms,
        persisted=persisted,
        created_at=record.created_at,
    )


# ── Endpoint: stored records ──────────────────────────────────────────────
@app.get(
    "/classifications/{record_id}",
    response_model=ClassificationRecord,
    responses={404: {"model": ErrorOutput}, 422: {"model": ErrorOutput}},
)
async def get_classification(record_id: str, request: Request, processor: MainProcessor = Depends(get_processor)):
    """Fetch a stored classification: input, parsed output, latency, attempts and timestamp."""
    record = await processor.repository.get(record_id)
    if record is None:
        return error_response(404, "not_found", f"Classification {record_id} not found.", request.state.request_id)
    return record


# ── Endpoint: health ──────────────────────────────────────────────────────
@app.get("/health")
async def health(processor: MainProcessor = Depends(get_processor)):
    """Liveness plus database reachability. Used by the Docker healthcheck."""
    repository_ok = await processor.repository.ping()
    return JSONResponse(
        status_code=200 if repository_ok else 503,
        content={
            "status": "ok" if repository_ok else "degraded",
            "version": settings.APP_VERSION,
            "repository": type(processor.repository).__name__,
            "repository_ok": repository_ok,
        },
    )
