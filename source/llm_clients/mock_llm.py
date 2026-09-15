# mock_llm.py — provided. Do NOT call a real API.
import asyncio, json, random

class MockLLMClient:
    """Simulates an LLM. Occasionally returns malformed JSON or times out,
    so your service must handle those cases."""

    async def complete(self, prompt: str, *, timeout: float = 5.0) -> str:
        await asyncio.sleep(random.uniform(0.05, 0.3))

        roll = random.random()
        if roll < 0.08:                      # ~8% malformed output
            return '{"intent": "booking_inquiry", "confidence": 0.9'  # truncated JSON
        if roll < 0.12:                      # ~4% timeout
            raise asyncio.TimeoutError("LLM timed out")

        return json.dumps({
            "intent": random.choice(
                ["booking_inquiry", "maintenance_request",
                 "extension_request", "out_of_scope", "unknown"]
            ),
            "entities": {"dates": [], "location": None, "unit_type": None},
            "urgency": random.choice(["low", "medium", "high"]),
            "confidence": round(random.uniform(0.4, 0.99), 2),
            "needs_human": False,
        })
