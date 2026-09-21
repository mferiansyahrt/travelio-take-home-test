from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppConfig(BaseSettings):
    """Service settings. Every field can be overridden with an environment variable of the same name."""

    # `.env` is looked up both in the working directory and its parent, so it is found
    # whether the service is started from the repo root or from `source/`.
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    APP_NAME: str = "Travelio Message Classifier"
    APP_VERSION: str = "0.1.0"

    LOG_LEVEL: str = "INFO"
    # true → one JSON object per log line (for log shippers); false → human-readable lines
    LOG_JSON: bool = True

    # ── LLM call policy ──
    # The provided mock ignores its `timeout` argument, so the agent also enforces this
    # deadline itself with asyncio.wait_for.
    LLM_TIMEOUT_SECONDS: float = Field(default=5.0, gt=0)
    # "Retry up to N times": total attempts = 1 + LLM_MAX_RETRIES
    LLM_MAX_RETRIES: int = Field(default=2, ge=0)
    # Exponential backoff between attempts: base, 2x base, 4x base, ...
    LLM_RETRY_BACKOFF_SECONDS: float = Field(default=0.2, ge=0)

    # ── Classification rules ──
    # Below this confidence the service forces needs_human=true, whatever the model said.
    CONFIDENCE_THRESHOLD: float = Field(default=0.6, ge=0, le=1)
    # Relative dates ("besok", "next Monday") are resolved against "now" in this timezone.
    TIMEZONE: str = "Asia/Jakarta"
    # Only the most recent turns of conversation context are put in the prompt.
    MAX_CONTEXT_MESSAGES: int = Field(default=10, ge=0)

    # ── Persistence ──
    REPOSITORY_BACKEND: Literal["memory", "mongo"] = "memory"
    MONGO_URI: str = "mongodb://localhost:27017"
    MONGO_DB_NAME: str = "travelio"
    MONGO_COLLECTION: str = "message_classifications"
    # Every HTTP call with its request and response body (see services/api_request_log_middleware.py).
    MONGO_REQUEST_LOG_COLLECTION: str = "api_requests"


settings = AppConfig()
