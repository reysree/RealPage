"""
File: schemas_llm.py
Purpose: Pydantic models for LLM JSON output contracts used by tools and the eval judge.
Author: Sreeram
"""

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

from backend.schemas_types import ComposerReasonText, LongText, MediumText, ShortText


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
