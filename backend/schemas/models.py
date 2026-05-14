"""
File: models.py
Purpose: Pydantic models for outreach API inputs, outputs, and eval cases.
Author: Sreeram
"""

from typing import Any, Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from backend.schemas.types import (
    REQUIRED_ASSERTION_STATES,
    Channel,
    IsoDate,
    IsoDateTime,
    JsonBoolean,
    JsonFloat,
    JsonInt,
    LanguageCode,
    LifecycleKind,
    LongText,
    MediumText,
    OptionalJsonBoolean,
    OptionalJsonFloat,
    PersonaKind,
    ShortText,
)
from backend.core.content_policy import outreach_input_must_pass_language_policy
from backend.core.url_security import analyze_plain_hostname, analyze_url_security


class ToolResultEnvelope(BaseModel):
    """
    Standard in-process wrapper for outreach tools before HTTP or persistence boundaries.

    Callers orchestrate using this model directly; serializers use ``model_dump()`` or
    Pydantic response models rather than embedding ``json.dumps`` in each tool.
    """

    model_config = ConfigDict(extra="forbid")

    error: str | None = Field(None, description="Human-readable failure reason when absent result.")
    error_code: str | None = Field(
        None,
        description="Stable code for auditing (composer failures, configuration gaps).",
    )
    result: dict[str, Any] | None = Field(
        None,
        description="Successful payload when execution completed without logical error.",
    )


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

    first_name: ShortText = Field(..., description="Recipient first name.")
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
    listing_url: AnyHttpUrl | None = Field(
        None,
        description="Optional listing or tour URL (https recommended); must be a public http(s) target.",
    )

    @field_validator("listing_url", mode="before")
    @classmethod
    def listing_url_blank_is_none(cls, value: object) -> object:
        """
        Treat empty strings as absent so optional URLs stay omitted in JSON.
        """

        if value is None or value == "":
            return None
        return value

    @field_validator("listing_url")
    @classmethod
    def listing_url_must_pass_security(cls, value: AnyHttpUrl | None) -> AnyHttpUrl | None:
        """
        Reject malformed URLs and unsafe targets (localhost, private IP, credentials).
        """

        if value is None:
            return None
        if analyze_url_security(str(value)):
            raise ValueError(
                "Listing URL is malformed or points to a non-public or unsafe target."
            )
        return value

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

    no_pii_leak: JsonBoolean = Field(
        ...,
        description="Whether PII leakage is forbidden — must be true for production sends.",
    )
    no_sensitive_discrimination: OptionalJsonBoolean = Field(
        None,
        description="Whether protected-class targeting is forbidden (optional; enable per campaign).",
    )
    include_opt_out_instructions: JsonBoolean = Field(
        ...,
        description="Whether opt-out language must be present — must be true for production sends.",
    )
    primary_cta: ShortText = Field(..., description="Required primary CTA intent.")
    brand_style_notes: LongText | None = Field(
        None,
        description="Case-specific brand voice or style notes for the composer LLM.",
    )
    compliance_suffix: LongText = Field(
        ...,
        description="Exact trailing compliance line appended after the composed body "
        "when include_opt_out_instructions is true; avoids hardcoded opt-out copy in code.",
    )
    allowed_link_domains: list[MediumText] | None = Field(
        None,
        max_length=20,
        description="Hostname allowlist (lowercase) for URLs embedded in the composed body.",
    )

    @field_validator("allowed_link_domains")
    @classmethod
    def allowed_link_domains_are_public_hostnames(
        cls,
        value: list[str] | None,
    ) -> list[str] | None:
        """
        Allowlist entries must be bare public hostnames — no schemes, paths, or unsafe hosts.
        """

        if value is None:
            return None
        for item in value:
            if analyze_plain_hostname(item):
                raise ValueError(
                    "allowed_link_domains must be safe public hostnames only "
                    "(no URL paths, embedded credentials, or non-public hosts)."
                )
        return value


class AssertionsRecord(BaseModel):
    """
    Eval assertions that describe required behavioral states and constraints.
    """

    model_config = ConfigDict(extra="forbid")

    required_states: list[ShortText] = Field(
        default_factory=lambda: list(REQUIRED_ASSERTION_STATES),
        max_length=20,
        description="Canonical pipeline states — must match the fixed triple.",
    )
    constraints: AssertionConstraints = Field(
        ...,
        description="Output constraints for compliance and CTA behavior.",
    )

    @field_validator("required_states", mode="after")
    @classmethod
    def required_states_are_canonical(cls, value: list[str]) -> list[str]:
        """
        Every case carries the same ordered required-states triple; callers cannot substitute.
        """

        if tuple(value) != REQUIRED_ASSERTION_STATES:
            raise ValueError(
                "required_states must be exactly "
                f"{list(REQUIRED_ASSERTION_STATES)} in that order."
            )
        return value


class ThresholdsRecord(BaseModel):
    """
    Numeric pass/fail thresholds used by the eval harness.
    """

    model_config = ConfigDict(extra="forbid")

    p95_latency_ms: JsonInt = Field(..., description="Maximum allowed p95 latency.")
    personalization_score_min: JsonFloat = Field(
        ...,
        description="Minimum semantic personalization score.",
    )
    reply_classification_f1_min: OptionalJsonFloat = Field(
        None,
        description="Minimum reply classification F1 score (optional until reply stack exists).",
    )
    safety_violations_max: JsonInt = Field(
        ...,
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

    model_config = ConfigDict(extra="forbid")

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
    persona: PersonaKind = Field(
        ...,
        description="Recipient persona (PoC: prospect only; extend union when new segments launch).",
    )
    lifecycle_stage: LifecycleKind = Field(
        ...,
        description="Journey stage (PoC: new | open; extend when client adds stages).",
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

    @model_validator(mode="after")
    def enforce_content_language_policy(self) -> Self:
        """
        Reject profanity, slurs, and violent-extremism phrases in caller-supplied text.

        Expected-output fixtures are excluded — only inputs and assertion metadata.
        """

        outreach_input_must_pass_language_policy(self.task_id)
        outreach_input_must_pass_language_policy(self.persona)
        outreach_input_must_pass_language_policy(self.lifecycle_stage)

        inp = self.input
        outreach_input_must_pass_language_policy(inp.property_name)
        outreach_input_must_pass_language_policy(inp.timezone)
        outreach_input_must_pass_language_policy(inp.language)
        if inp.listing_url is not None:
            outreach_input_must_pass_language_policy(str(inp.listing_url))

        profile = inp.profile
        outreach_input_must_pass_language_policy(profile.first_name)
        outreach_input_must_pass_language_policy(profile.city_interest)
        if profile.amenity_interest:
            for item in profile.amenity_interest:
                outreach_input_must_pass_language_policy(item)

        assertions = self.assertions
        for state in assertions.required_states:
            outreach_input_must_pass_language_policy(state)

        constraints = assertions.constraints
        outreach_input_must_pass_language_policy(constraints.primary_cta)
        outreach_input_must_pass_language_policy(constraints.brand_style_notes)
        outreach_input_must_pass_language_policy(constraints.compliance_suffix)
        if constraints.allowed_link_domains:
            for host in constraints.allowed_link_domains:
                outreach_input_must_pass_language_policy(host)

        return self


class RunResponse(BaseModel):
    """
    API response model containing generated output and run metadata.
    """

    output: AgentOutput = Field(..., description="Generated agent output.")
    latency_ms: int = Field(..., ge=0, description="End-to-end runtime in milliseconds.")


class HealthResponse(BaseModel):
    """
    API response model for backend health checks.
    """

    status: ShortText = Field(
        ...,
        description="Health status string.",
    )
