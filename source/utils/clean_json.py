import re

_CODE_FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL | re.IGNORECASE)


def strip_code_fence(raw_response: str) -> str:
    """Remove one markdown code fence wrapping the whole response (```json ... ```), if present.

    This deliberately does NOT "repair" JSON (no json_repair): a truncated answer such as
    '{"intent": "booking_inquiry", "confidence": 0.9' must stay invalid, so validation fails,
    the failure is counted, and the call is retried instead of silently accepting half an output.
    """
    match = _CODE_FENCE.match(raw_response)
    return match.group(1) if match else raw_response.strip()
