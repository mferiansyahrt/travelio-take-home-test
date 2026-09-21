from datetime import datetime
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field

from agents.message_classifier_agent import ClassificationOutput, ConversationTurn


class ClassificationRecord(BaseModel):
    """One /classify-message call as stored in the database, successful or failed."""

    id: str
    request_id: str
    created_at: datetime
    status: Literal["succeeded", "failed"]
    message: str
    conversation_context: list[ConversationTurn] = Field(default_factory=list)
    output: ClassificationOutput | None = None
    needs_human_reasons: list[str] = Field(default_factory=list)
    error_code: str | None = None
    attempts: int
    attempt_errors: list[str] = Field(default_factory=list)
    latency_ms: float


class ClassificationRepository(Protocol):
    """Storage interface. The service depends only on this, so backends are swappable (memory / MongoDB)."""

    async def save(self, record: ClassificationRecord) -> None: ...

    async def get(self, record_id: str) -> ClassificationRecord | None: ...

    async def ping(self) -> bool: ...

    async def close(self) -> None: ...


class ApiRequestLog(BaseModel):
    """One HTTP call to the service, with the request and response bodies as they went over the wire."""

    id: str
    request_id: str | None
    created_at: datetime
    method: str
    path: str
    query: str
    client_ip: str | None
    user_agent: str | None
    status_code: int
    latency_ms: float
    # Parsed JSON when the body is JSON, the raw text otherwise, None when empty.
    request_body: Any = None
    response_body: Any = None


class ApiRequestLogRepository(Protocol):
    """Storage for the HTTP request log. Kept apart from classification records: different shape, different use."""

    async def save(self, log: ApiRequestLog) -> None: ...

    async def close(self) -> None: ...
