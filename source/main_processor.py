import time
import uuid
from datetime import datetime, timezone
from typing import Callable
from zoneinfo import ZoneInfo

from loguru import logger

from agents import LLMFailure
from agents.message_classifier_agent import ConversationTurn, MessageClassifierAgent
from db_clients import ClassificationRecord, ClassificationRepository


def utc_now() -> datetime:
    now = datetime.now(timezone.utc)
    # MongoDB stores datetimes with millisecond precision; truncating keeps a stored record identical when read back.
    return now.replace(microsecond=now.microsecond // 1000 * 1000)


class MainProcessor:
    """Orchestrates one /classify-message call: agent → timing → persistence."""

    def __init__(
        self,
        agent: MessageClassifierAgent,
        repository: ClassificationRepository,
        *,
        timezone_name: str,
        now_fn: Callable[[], datetime] = utc_now,
    ):
        self.agent = agent
        self.repository = repository
        self.timezone = ZoneInfo(timezone_name)
        self.now_fn = now_fn

    @staticmethod
    def _elapsed_ms(started: float) -> float:
        return round((time.perf_counter() - started) * 1000, 1)

    async def process(
        self, message: str, conversation_context: list[ConversationTurn], request_id: str
    ) -> tuple[ClassificationRecord, bool]:
        """
        Classify a message and persist the outcome, whether it succeeded or failed.

        Returns:
            (record, persisted). `record.status` is "failed" when the LLM gave no valid answer
            within the retry budget; `persisted` is False when the database write failed.
        """
        created_at = self.now_fn()
        started = time.perf_counter()
        common_fields = {
            "id": uuid.uuid4().hex,
            "request_id": request_id,
            "created_at": created_at,
            "message": message,
            "conversation_context": conversation_context,
        }

        try:
            result = await self.agent.run(
                message, conversation_context, reference_time=created_at.astimezone(self.timezone)
            )
        except LLMFailure as failure:
            record = ClassificationRecord(
                **common_fields,
                status="failed",
                error_code=f"llm_{failure.reason}",
                attempts=failure.attempts,
                attempt_errors=failure.attempt_errors,
                latency_ms=self._elapsed_ms(started),
            )
        else:
            record = ClassificationRecord(
                **common_fields,
                status="succeeded",
                output=result.output,
                needs_human_reasons=result.needs_human_reasons,
                attempts=result.attempts,
                attempt_errors=result.attempt_errors,
                latency_ms=self._elapsed_ms(started),
            )

        persisted = await self._persist(record)
        return record, persisted

    async def _persist(self, record: ClassificationRecord) -> bool:
        """Best-effort write. A database outage must not throw away a classification that already
        cost an LLM call; the caller sees `persisted: false` and the error is logged for alerting."""
        try:
            await self.repository.save(record)
            return True
        except Exception:
            logger.bind(record_id=record.id, status=record.status).exception("classification_persist_failed")
            return False
