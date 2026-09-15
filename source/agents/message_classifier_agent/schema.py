from datetime import date
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class Intent(str, Enum):
    BOOKING_INQUIRY = "booking_inquiry"
    MAINTENANCE_REQUEST = "maintenance_request"
    EXTENSION_REQUEST = "extension_request"
    PAYMENT_INQUIRY = "payment_inquiry"
    OUT_OF_SCOPE = "out_of_scope"
    UNKNOWN = "unknown"


class Urgency(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


# Same values as bookings.property_type in the MySQL schema.
UnitType = Literal["studio", "1br", "2br", "3br"]

_INTENT_VALUES = {intent.value for intent in Intent}


class ConversationTurn(BaseModel):
    """An earlier chat message, used only as context for the latest guest message."""

    role: Literal["guest", "agent"]
    text: str = Field(min_length=1, max_length=2000)


class Stay(BaseModel):
    """One stay mentioned by the guest. Grouping location, unit and dates per stay keeps
    "Kemang on the 12th, then Gambir on the 15th" unambiguous."""

    location: str | None = Field(default=None, description="Area, building or city as written by the guest.")
    unit_type: UnitType | None = None
    check_in: date | None = None
    check_out: date | None = Field(
        default=None, description="Check-out date; for extension requests, the current check-out."
    )
    new_check_out: date | None = Field(
        default=None, description="Extension requests only: the requested later check-out."
    )

    @model_validator(mode="after")
    def check_date_order(self) -> "Stay":
        if self.check_in and self.check_out and self.check_out <= self.check_in:
            raise ValueError("check_out must be after check_in")
        if self.check_out and self.new_check_out and self.new_check_out <= self.check_out:
            raise ValueError("new_check_out must be after check_out")
        return self


class Entities(BaseModel):
    stays: list[Stay] = Field(default_factory=list)


class ClassificationOutput(BaseModel):
    """Contract for the classifier LLM's JSON answer. Every answer is validated against it."""

    intent: Intent
    entities: Entities = Field(default_factory=Entities)
    urgency: Urgency
    confidence: float = Field(ge=0.0, le=1.0)
    needs_human: bool = False
    reason: str | None = None
    unrecognized_intent: str | None = Field(
        default=None,
        description="Set by the service, never by the model: the original intent string when it was "
        "outside the enum and mapped to 'unknown'.",
    )

    @model_validator(mode="before")
    @classmethod
    def map_unrecognized_intent(cls, data: Any) -> Any:
        """Map an intent string outside the enum to `unknown` instead of rejecting the answer.

        Such an answer is well-formed JSON that we simply cannot route, so retrying would only
        burn latency; routing it to `unknown` lets the guardrails hand it to a human.
        A missing or non-string intent is still a validation error (malformed output → retry).
        """
        if not isinstance(data, dict) or not isinstance(data.get("intent"), str):
            return data

        raw_intent = data["intent"]
        normalized = raw_intent.strip().lower()
        if not normalized:
            return data
        if normalized in _INTENT_VALUES:
            # A stored record reloaded from the database already has intent "unknown" plus the original value:
            # keep it. For any other valid intent there is nothing unrecognized (and the model can't set this field).
            unrecognized_intent = data.get("unrecognized_intent") if normalized == Intent.UNKNOWN.value else None
            return {**data, "intent": normalized, "unrecognized_intent": unrecognized_intent}
        return {**data, "intent": Intent.UNKNOWN.value, "unrecognized_intent": raw_intent}


class ClassificationResult(BaseModel):
    """What the agent returns: the validated output after guardrails, plus call metadata."""

    output: ClassificationOutput
    needs_human_reasons: list[str]
    attempts: int
    attempt_errors: list[str]
