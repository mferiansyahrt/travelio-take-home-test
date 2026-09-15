import asyncio
from abc import ABC, abstractmethod
from typing import Any, Callable, Literal, TypeVar

from loguru import logger

from llm_clients import LLMClient

T = TypeVar("T")

AttemptError = Literal["timeout", "malformed_output"]


class LLMOutputError(Exception):
    """The LLM answered, but the answer is not a valid output for the agent (bad JSON or schema)."""


class LLMFailure(Exception):
    """Every attempt to get a valid output from the LLM failed."""

    def __init__(self, agent_name: str, attempt_errors: list[AttemptError]):
        self.agent_name = agent_name
        self.attempt_errors = attempt_errors
        self.attempts = len(attempt_errors)
        # "timeout" only when the model never answered in time; if it answered at least once
        # with something unusable, the failure is a bad upstream response.
        self.reason: AttemptError = (
            "timeout" if all(error == "timeout" for error in attempt_errors) else "malformed_output"
        )
        super().__init__(
            f"{agent_name}: no valid LLM output after {self.attempts} attempt(s): {', '.join(attempt_errors)}"
        )


class BaseAgent(ABC):
    """Base class for all agents: holds the LLM client and the timeout / retry policy."""

    def __init__(
        self,
        agent_name: str,
        llm_client: LLMClient,
        *,
        timeout_seconds: float,
        max_retries: int,
        retry_backoff_seconds: float,
    ):
        self.agent_name = agent_name
        self.llm_client = llm_client
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.retry_backoff_seconds = retry_backoff_seconds

    async def _complete_with_retry(
        self, prompt: str, parse: Callable[[str], T]
    ) -> tuple[T, list[AttemptError]]:
        """Call the LLM and parse its answer, retrying timeouts and invalid outputs.

        Args:
            prompt: Full prompt sent to the LLM.
            parse: Turns the raw answer into a validated output; raises LLMOutputError if it can't.

        Returns:
            The parsed output and the errors of the failed attempts before it
            (an empty list means the first attempt succeeded).

        Raises:
            LLMFailure: when all 1 + max_retries attempts failed.
            Any other exception is a programming or infrastructure error and is not retried.
        """
        max_attempts = self.max_retries + 1
        attempt_errors: list[AttemptError] = []

        for attempt in range(1, max_attempts + 1):
            log = logger.bind(agent=self.agent_name, attempt=attempt, max_attempts=max_attempts)
            try:
                # The client's own timeout is not trusted (the provided mock ignores it),
                # so the deadline is enforced here too.
                raw_response = await asyncio.wait_for(
                    self.llm_client.complete(prompt, timeout=self.timeout_seconds),
                    timeout=self.timeout_seconds,
                )
                output = parse(raw_response)
            except asyncio.TimeoutError:  # same class as the built-in TimeoutError since Python 3.11
                attempt_errors.append("timeout")
                log.warning("llm_attempt_timeout")
            except LLMOutputError as exc:
                attempt_errors.append("malformed_output")
                log.bind(error=str(exc)).warning("llm_attempt_malformed_output")
            else:
                if attempt_errors:
                    log.bind(previous_errors=attempt_errors).info("llm_attempt_recovered")
                return output, attempt_errors

            if attempt < max_attempts:
                await asyncio.sleep(self.retry_backoff_seconds * 2 ** (attempt - 1))

        logger.bind(agent=self.agent_name, attempt_errors=attempt_errors).error("llm_all_attempts_failed")
        raise LLMFailure(self.agent_name, attempt_errors)

    @abstractmethod
    async def run(self, *args: Any, **kwargs: Any) -> Any:
        """Execute the agent's main logic."""
