import asyncio
import json
from datetime import datetime, timezone

from agents.message_classifier_agent import MessageClassifierAgent

# Tuesday 2026-09-15, 10:00 in Asia/Jakarta.
FIXED_NOW = datetime(2026, 9, 15, 3, 0, tzinfo=timezone.utc)

SAMPLE_BOOKING_MESSAGE = (
    "Halo, saya mau booking unit 2BR di Kemang dari tgl 12 sampai 15 Maret, masih ada yg available?"
)

# Exactly what MockLLMClient returns on its "malformed output" branch.
TRUNCATED_MOCK_OUTPUT = '{"intent": "booking_inquiry", "confidence": 0.9'


def llm_json(**overrides) -> str:
    """A valid classifier answer for SAMPLE_BOOKING_MESSAGE, with optional field overrides."""
    payload = {
        "intent": "booking_inquiry",
        "entities": {
            "stays": [
                {
                    "location": "Kemang",
                    "unit_type": "2br",
                    "check_in": "2027-03-12",
                    "check_out": "2027-03-15",
                    "new_check_out": None,
                }
            ]
        },
        "urgency": "low",
        "confidence": 0.93,
        "needs_human": False,
        "reason": "Asks availability of a 2BR in Kemang for 12-15 March.",
    }
    payload.update(overrides)
    return json.dumps(payload)


class ScriptedLLMClient:
    """Test double with the same interface as MockLLMClient, but deterministic.

    Each call consumes the next script step:
    - str       → returned as the LLM answer
    - Exception → raised
    - float     → sleep that many seconds first (to prove the agent enforces its own timeout)
    """

    def __init__(self, script: list):
        self.script = list(script)
        self.prompts: list[str] = []

    async def complete(self, prompt: str, *, timeout: float = 5.0) -> str:
        self.prompts.append(prompt)
        step = self.script.pop(0)
        if isinstance(step, BaseException):
            raise step
        if isinstance(step, float):
            await asyncio.sleep(step)
            return llm_json()
        return step


def build_agent(llm_client, **overrides) -> MessageClassifierAgent:
    options = {
        "timeout_seconds": 1.0,
        "max_retries": 2,
        "retry_backoff_seconds": 0.0,
        "confidence_threshold": 0.6,
        "max_context_messages": 10,
    }
    options.update(overrides)
    return MessageClassifierAgent(llm_client, **options)
