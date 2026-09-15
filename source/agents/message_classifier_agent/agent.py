from datetime import datetime

from loguru import logger
from pydantic import ValidationError

from agents.base import BaseAgent, LLMOutputError
from llm_clients import LLMClient
from utils.clean_json import strip_code_fence

from .guardrails import apply_guardrails
from .prompt import MESSAGE_CLASSIFIER_HUMAN_PROMPT, MESSAGE_CLASSIFIER_SYSTEM_PROMPT
from .schema import ClassificationOutput, ClassificationResult, ConversationTurn


class MessageClassifierAgent(BaseAgent):
    """
    Agent that classifies a guest chat message for routing.

    Builds the prompt (with a reference datetime so relative dates can be resolved),
    calls the LLM with timeout + retry, validates the JSON answer against
    `ClassificationOutput`, then applies the needs_human guardrails.
    """

    def __init__(
        self,
        llm_client: LLMClient,
        *,
        timeout_seconds: float,
        max_retries: int,
        retry_backoff_seconds: float,
        confidence_threshold: float,
        max_context_messages: int,
        agent_name: str = "Message Classifier Agent",
    ):
        super().__init__(
            agent_name=agent_name,
            llm_client=llm_client,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            retry_backoff_seconds=retry_backoff_seconds,
        )
        self.confidence_threshold = confidence_threshold
        self.max_context_messages = max_context_messages

    @staticmethod
    def escape_untrusted(text: str) -> str:
        """Escape angle brackets so guest text cannot close the <guest_message> delimiter."""
        return text.replace("<", "&lt;").replace(">", "&gt;")

    def format_conversation_context(self, conversation_context: list[ConversationTurn]) -> str:
        """Render the most recent turns, oldest first, one per line."""
        if self.max_context_messages <= 0 or not conversation_context:
            return "(none)"
        recent_turns = conversation_context[-self.max_context_messages:]
        return "\n".join(f"- {turn.role}: {self.escape_untrusted(turn.text)}" for turn in recent_turns)

    def build_prompt(
        self, message: str, conversation_context: list[ConversationTurn], reference_time: datetime
    ) -> str:
        """Combine system and human prompt into one string (the LLM client takes a single prompt).

        Args:
            message: Latest guest message.
            conversation_context: Earlier turns of the chat (may be empty).
            reference_time: Timezone-aware "now", used to resolve relative dates.
        """
        human_prompt = MESSAGE_CLASSIFIER_HUMAN_PROMPT.format(
            reference_datetime=reference_time.isoformat(timespec="minutes"),
            weekday=reference_time.strftime("%A"),
            timezone=reference_time.tzinfo,
            conversation_context=self.format_conversation_context(conversation_context),
            message=self.escape_untrusted(message),
        )
        return f"{MESSAGE_CLASSIFIER_SYSTEM_PROMPT.strip()}\n\n{human_prompt.strip()}"

    @staticmethod
    def parse_output(raw_response: str) -> ClassificationOutput:
        """Validate the raw LLM answer; any JSON or schema problem becomes LLMOutputError (→ retry)."""
        try:
            return ClassificationOutput.model_validate_json(strip_code_fence(raw_response))
        except ValidationError as exc:
            # Only locations and error types: the raw input may contain guest data.
            summary = "; ".join(
                f"{'.'.join(str(part) for part in error['loc']) or '<root>'}: {error['type']}"
                for error in exc.errors()[:3]
            )
            raise LLMOutputError(f"{exc.error_count()} validation error(s): {summary}") from exc

    async def run(
        self, message: str, conversation_context: list[ConversationTurn], reference_time: datetime
    ) -> ClassificationResult:
        """
        Classify one guest message.

        Returns:
            ClassificationResult with the guarded output, needs_human reasons and attempt metadata.

        Raises:
            LLMFailure: when no valid answer was obtained within the retry budget.
        """
        log = logger.bind(agent=self.agent_name)
        log.bind(message_chars=len(message), context_turns=len(conversation_context)).info("classification_started")

        prompt = self.build_prompt(message, conversation_context, reference_time)
        output, attempt_errors = await self._complete_with_retry(prompt, self.parse_output)
        output, needs_human_reasons = apply_guardrails(
            output, message=message, confidence_threshold=self.confidence_threshold
        )

        log.bind(
            intent=output.intent.value,
            unrecognized_intent=output.unrecognized_intent,
            confidence=output.confidence,
            urgency=output.urgency.value,
            needs_human=output.needs_human,
            needs_human_reasons=needs_human_reasons,
            stays=len(output.entities.stays),
            attempts=len(attempt_errors) + 1,
        ).info("classification_completed")

        return ClassificationResult(
            output=output,
            needs_human_reasons=needs_human_reasons,
            attempts=len(attempt_errors) + 1,
            attempt_errors=attempt_errors,
        )
