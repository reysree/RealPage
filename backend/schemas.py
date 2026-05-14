"""
File: schemas.py
Purpose: Pydantic models for outreach API inputs, outputs, and eval cases.
Author: Sreeram
"""

from datetime import date, datetime
from typing import Annotated, Literal, Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationInfo,
    field_validator,
    model_validator,
)

Channel = Literal["sms", "email", "voice"]
LanguageCode = Literal["en"]
ShortText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=80),
]
MediumText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=160),
]
LongText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=2000),
]
ComposerReasonText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=500),
]


def _wire_bool(value: object) -> bool:
    """
    Accept only JSON-native booleans — reject 0/1 and \"true\"/\"false\" strings.
    """

    if isinstance(value, bool):
        return value
    raise ValueError("Must be JSON true or false, not a string or number.")


def _wire_optional_bool(value: object) -> bool | None:
    """
    Accept null or JSON booleans only for optional constraint flags.
    """

    if value is None:
        return None
    return _wire_bool(value)


def _wire_int(value: object) -> int:
    """
    Accept JSON integers only — reject booleans and floats.
    """

    if isinstance(value, bool):
        raise ValueError("Integer threshold cannot be a boolean.")
    if isinstance(value, int):
        return value
    raise ValueError("Must be a JSON integer, not a float or string.")


def _wire_optional_int(value: object) -> int | None:
    """
    Accept null or JSON integers for optional integer thresholds.
    """

    if value is None:
        return None
    return _wire_int(value)


def _wire_optional_float(value: object) -> float | None:
    """
    Accept null or JSON numbers for float thresholds — not strings or booleans.
    """

    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("Float threshold cannot be a boolean.")
    if isinstance(value, float):
        return value
    if isinstance(value, int):
        return float(value)
    raise ValueError("Must be a JSON number.")


def _iso_date_wire(value: object) -> date:
    """
    Parse move date from JSON string YYYY-MM-DD or an existing date object.
    """

    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return date.fromisoformat(value)
    raise ValueError("Date must be an ISO 8601 date string (YYYY-MM-DD).")


def _iso_datetime_wire(value: object) -> datetime:
    """
    Parse last interaction from ISO 8601 JSON string or an existing datetime.
    """

    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        normalized = value.replace("Z", "+00:00") if value.endswith("Z") else value
        return datetime.fromisoformat(normalized)
    raise ValueError("Datetime must be an ISO 8601 string or datetime.")


JsonBoolean = Annotated[bool, BeforeValidator(_wire_bool)]
OptionalJsonBoolean = Annotated[bool | None, BeforeValidator(_wire_optional_bool)]
JsonInt = Annotated[int, BeforeValidator(_wire_int)]
OptionalJsonInt = Annotated[int | None, BeforeValidator(_wire_optional_int)]
OptionalJsonFloat = Annotated[float | None, BeforeValidator(_wire_optional_float)]
IsoDate = Annotated[date, BeforeValidator(_iso_date_wire)]
IsoDateTime = Annotated[datetime, BeforeValidator(_iso_datetime_wire)]


class ConsentRecord(BaseModel):
    """
    Recipient channel consent flags used to decide communication eligibility.
    """

    model_config = ConfigDict(extra="forbid")

    email_opt_in: JsonBoolean = Field(..., description="Whether email outreach is allowed.")
    sms_opt_in: JsonBoolean = Field(..., description="Whether SMS outreach is allowed.")
    voice_opt_in: JsonBoolean = Field(..., description="Whether voice outreach is allowed.")


class UserProfile(BaseModel):
    """
    Prospect profile facts available for message personalization.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    first_name: ShortText | None = Field(
        None,
        description="Recipient first name.",
    )
    city_interest: MediumText | None = Field(
        None,
        description="City or area of interest.",
    )
    amenity_interest: list[ShortText] | None = Field(
        None,
        max_length=10,
        description="Amenities the recipient has shown interest in.",
    )


class InputRecord(BaseModel):
    """
    Outreach context supplied by the caller for one stateless decision.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    property_name: MediumText = Field(
        ...,
        description="Property being marketed.",
    )
    move_date_target: IsoDate = Field(
        ...,
        description="Target move date.",
    )
    last_interaction: IsoDateTime = Field(
        ...,
        description="Last interaction timestamp in ISO 8601 format.",
    )
    timezone: ShortText = Field(
        ...,
        description="Recipient IANA timezone.",
    )
    language: LanguageCode = Field(..., description="Preferred language code.")
    profile: UserProfile = Field(..., description="Profile personalization facts.")

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        """
        Validate that timezone is a real IANA timezone before tool execution.
        """

        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("Invalid IANA timezone.") from exc
        return value


class AssertionConstraints(BaseModel):
    """
    Boolean and CTA constraints used by the eval harness.
    """

    model_config = ConfigDict(extra="forbid")

    no_pii_leak: OptionalJsonBoolean = Field(None, description="Whether PII leakage is forbidden.")
    no_sensitive_discrimination: OptionalJsonBoolean = Field(
        None,
        description="Whether protected-class targeting is forbidden.",
    )
    include_opt_out_instructions: OptionalJsonBoolean = Field(
        None,
        description="Whether opt-out language must be present.",
    )
    primary_cta: ShortText | None = Field(
        None,
        description="Required primary CTA intent.",
    )
    brand_style_notes: LongText | None = Field(
        None,
        description="Case-specific brand voice or style notes for the composer LLM.",
    )
    compliance_suffix: LongText | None = Field(
        None,
        description="Exact trailing compliance line appended after the composed body "
        "when include_opt_out_instructions is true; avoids hardcoded opt-out copy in code.",
    )


class AssertionsRecord(BaseModel):
    """
    Eval assertions that describe required behavioral states and constraints.
    """

    required_states: list[ShortText] = Field(
        default_factory=list,
        max_length=20,
        description="Named states the run should satisfy.",
    )
    constraints: AssertionConstraints = Field(
        default_factory=AssertionConstraints,
        description="Output constraints for compliance and CTA behavior.",
    )


class ThresholdsRecord(BaseModel):
    """
    Numeric pass/fail thresholds used by the eval harness.
    """

    model_config = ConfigDict(extra="forbid")

    p95_latency_ms: OptionalJsonInt = Field(None, description="Maximum allowed p95 latency.")
    personalization_score_min: OptionalJsonFloat = Field(
        None,
        description="Minimum semantic personalization score.",
    )
    reply_classification_f1_min: OptionalJsonFloat = Field(
        None,
        description="Minimum reply classification F1 score.",
    )
    safety_violations_max: OptionalJsonInt = Field(
        None,
        description="Maximum allowed safety violations.",
    )


class CtaPayload(BaseModel):
    """
    Bounded call-to-action payload attached to an outbound message.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    type: ShortText = Field(..., description="CTA category.")
    options: list[ShortText] | None = Field(
        None,
        max_length=5,
        description="Short reply options for SMS CTAs.",
    )
    link: MediumText | None = Field(None, description="CTA link for email CTAs.")


class ComposerCtaLlmOutput(BaseModel):
    """
    CTA object inside compose_message LLM JSON only.

    Allowed keys: type (required string), options (optional string array, max 5),
    link (optional string). No other keys. Types must be JSON-native to each field
    (strict validation — no string-to-int coercion).
    """

    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)

    type: ShortText = Field(..., description="CTA category from the model.")
    options: list[ShortText] | None = Field(
        None,
        max_length=5,
        description="Reply options; each entry must be a non-empty string.",
    )
    link: MediumText | None = Field(
        None,
        description="URL string for email-style CTAs when present.",
    )


class ComposerLlmOutput(BaseModel):
    """
    Exact JSON contract for the compose_message LLM (parse with strict=True).

    Expected top-level keys only: subject, body, cta, message_reason — no extras.

    Types (must match JSON types exactly under strict validation):
    - subject: string | null (required key may be null; for sms/voice must be null;
      for email must be a non-empty string)
    - body: string (non-empty after strip, max 2000 chars)
    - cta: object matching ComposerCtaLlmOutput
    - message_reason: string (non-empty after strip, max 500 chars)

    Passing a number, array, or object where a string is required fails validation.
    """

    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)

    subject: MediumText | None = Field(
        None,
        description="Email subject: null/omit for sms and voice only.",
    )
    body: LongText = Field(..., description="Primary message body from the model.")
    cta: ComposerCtaLlmOutput = Field(..., description="Nested CTA; fixed shape.")
    message_reason: ComposerReasonText = Field(
        ...,
        description="Non-empty rationale for the composition.",
    )

    @field_validator("subject", mode="before")
    @classmethod
    def normalize_blank_subject(cls, value: object) -> object:
        """
        Treat blank subject as missing so optional subject validates cleanly.
        """

        if value is None or value == "":
            return None
        return value

    @field_validator("body")
    @classmethod
    def body_disallows_nul(cls, value: str) -> str:
        """
        Reject NUL bytes and other disallowed control characters in model output.
        """

        if "\x00" in value:
            raise ValueError("composer_body_contains_nul_byte")
        for char in value:
            o = ord(char)
            if o < 32 and char not in "\n\r\t":
                raise ValueError("composer_body_contains_disallowed_control_character")
        return value

    @model_validator(mode="after")
    def subject_matches_channel(self, info: ValidationInfo) -> Self:
        """
        Enforce subject presence rules using validation context channel from the caller.
        """

        channel = (info.context or {}).get("channel")
        if channel in ("sms", "voice") and self.subject is not None:
            raise ValueError("composer_subject_must_be_null_for_sms_or_voice")
        if channel == "email" and self.subject is None:
            raise ValueError("composer_email_subject_required")
        return self


class PersonalizationJudgeLlmOutput(BaseModel):
    """
    Exact JSON contract for the personalization quality LLM judge.

    score ranges from 0.0 (fully generic) to 1.0 (highly personalized). No strict mode
    so integer scores like 1 are coerced to 1.0 without failing validation.
    """

    model_config = ConfigDict(extra="forbid")

    score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Personalization quality from 0.0 (generic) to 1.0 (highly tailored).",
    )
    reasoning: str = Field(
        ...,
        min_length=1,
        description="One-sentence rationale explaining the score.",
    )


class FairHousingJudgeLlmOutput(BaseModel):
    """
    Exact JSON contract for the Fair Housing LLM judge: only {\"passed\": <boolean>}.
    """

    model_config = ConfigDict(extra="forbid", strict=True)

    passed: bool = Field(
        ...,
        description="True or false from the model — not strings or 1/0.",
    )


class MessageOutput(BaseModel):
    """
    Single outbound message selected and composed by the outreach pipeline.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    channel: Channel = Field(..., description="Selected outreach channel.")
    send_at: ShortText = Field(
        ...,
        description="Scheduled send timestamp.",
    )
    subject: MediumText | None = Field(
        None,
        description="Email subject, if applicable.",
    )
    body: LongText = Field(..., description="Message body.")
    cta: CtaPayload = Field(..., description="Primary CTA payload.")


class NextAction(BaseModel):
    """
    Follow-up action recommended after this outreach decision.
    """

    model_config = ConfigDict(extra="allow", str_strip_whitespace=True)

    type: ShortText = Field(..., description="Action category.")
    name: MediumText | None = Field(
        None,
        description="Named cadence or workflow.",
    )
    value: int | ShortText | None = Field(
        None,
        description="Action value such as delay days.",
    )


class AgentOutput(BaseModel):
    """
    Final decision returned by the agent for one outreach case.

    Error details are never returned here — failures produce send=false with empty
    fields. Internal error codes and summaries go to logs/agent_audit.ndjson only.
    """

    send: bool = Field(..., description="Whether a message should be sent.")
    next_message: MessageOutput | None = Field(
        None,
        description="Message to send when send is true.",
    )
    next_action: NextAction | None = Field(
        None,
        description="Recommended follow-up action.",
    )
    body: str = Field(
        default="",
        max_length=2000,
        description="Denormalized message body: mirrors next_message.body when send; "
        "empty when no message is composed.",
    )

    @model_validator(mode="after")
    def sync_body_from_message(self) -> Self:
        """
        Keep body aligned with next_message for API consumers and empty when absent.
        """

        if self.next_message is not None:
            self.body = self.next_message.body
        else:
            self.body = ""
        return self


class ExpectedOutput(BaseModel):
    """
    Expected result attached to a JSONL case for eval comparison.
    """

    next_message: MessageOutput | None = Field(
        None,
        description="Expected message output.",
    )
    next_action: NextAction | None = Field(
        None,
        description="Expected follow-up action.",
    )


class TestCase(BaseModel):
    """
    One JSONL eval case containing input facts, assertions, and expected output.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    task_id: MediumText = Field(
        ...,
        description="Stable case identifier.",
    )
    persona: ShortText = Field(
        ...,
        description="Recipient persona.",
    )
    lifecycle_stage: ShortText = Field(
        ...,
        description="Recipient journey stage.",
    )
    consent: ConsentRecord = Field(..., description="Channel consent flags.")
    channel_preferences: list[Channel] = Field(
        ...,
        min_length=1,
        max_length=3,
        description="Ordered channel preferences.",
    )
    input: InputRecord = Field(..., description="Outreach context.")
    assertions: AssertionsRecord = Field(..., description="Eval assertions.")
    thresholds: ThresholdsRecord = Field(..., description="Eval thresholds.")
    expected: ExpectedOutput = Field(..., description="Expected output.")


class RunRequest(TestCase):
    """
    API request model for running one outreach JSONL case.
    """


class RunResponse(BaseModel):
    """
    API response model containing generated output and run metadata.
    """

    output: AgentOutput = Field(..., description="Generated agent output.")
    tools_used: list[ShortText] = Field(
        default_factory=list,
        max_length=20,
        description="Tool or node names used during execution.",
    )
    latency_ms: int = Field(..., ge=0, description="End-to-end runtime in milliseconds.")


class HealthResponse(BaseModel):
    """
    API response model for backend health checks.
    """

    status: ShortText = Field(
        ...,
        description="Health status string.",
    )
