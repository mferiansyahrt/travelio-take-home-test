import re

from .schema import ClassificationOutput, Intent, Urgency

# A cheap, deterministic second line of defence (the prompt is the first).
# A match only escalates to a human; it never changes the intent.
PROMPT_INJECTION_PATTERNS = [
    re.compile(r"\bignore\s+(all\s+|any\s+)?(the\s+)?(previous|prior|above)\s+(instructions|prompts?|rules)", re.I),
    re.compile(r"\babaikan\s+(semua\s+)?(instruksi|perintah|aturan)", re.I),
    re.compile(r"\b(system|developer)\s+prompt\b", re.I),
    re.compile(r"\b(admin|root)\s+(password|credentials?)\b", re.I),
]


def looks_like_prompt_injection(message: str) -> bool:
    return any(pattern.search(message) for pattern in PROMPT_INJECTION_PATTERNS)


def apply_guardrails(
    output: ClassificationOutput, *, message: str, confidence_threshold: float
) -> tuple[ClassificationOutput, list[str]]:
    """Decide needs_human with service-side rules on top of the model's own flag.

    The model's flag is not trusted alone (the provided mock always returns false).
    Rules can only escalate (false → true), never silence a model that asked for a human.

    Returns:
        The output with the final needs_human value, and the reasons (empty when no human is needed).
    """
    reasons: list[str] = []
    if output.needs_human:
        reasons.append("model_flagged")
    if output.intent == Intent.UNKNOWN:
        reasons.append("unknown_intent")
    if output.confidence < confidence_threshold:
        reasons.append("low_confidence")
    if output.urgency == Urgency.HIGH:
        reasons.append("high_urgency")
    if looks_like_prompt_injection(message):
        reasons.append("possible_prompt_injection")

    return output.model_copy(update={"needs_human": bool(reasons)}), reasons
