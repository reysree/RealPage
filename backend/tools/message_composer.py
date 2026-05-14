"""
File: message_composer.py
Purpose: Tool for composing channel-specific outreach messages and CTAs.
Author: Sreeram
"""

import json
import logging
import os
import time
from typing import Any

from pydantic import TypeAdapter, ValidationError

from backend.core.audit_log import append_agent_audit
from backend.core.constants import BRAND_STYLE_GUIDE, FAIR_HOUSING_RULES
from backend.schemas import ComposerLlmOutput, LongText, ToolResultEnvelope

logger = logging.getLogger(__name__)

_COMPOSER_MAX_ATTEMPTS = 3

_long_text_adapter = TypeAdapter(LongText)


def _validate_composer_llm_payload(
    parsed: dict[str, Any],
    channel: str,
) -> dict[str, object]:
    """
    Validate compose_message LLM JSON: exact keys/types (strict), channel subject rules.

    Args:
        parsed: Raw object from the model's JSON response.
        channel: sms, email, or voice — required for subject rules in context.
    Returns:
        Normalized payload dict including nested cta as plain dict.
    Raises:
        ValueError: When validation fails (wrapped details in ValidationError string).
    """

    try:
        model = ComposerLlmOutput.model_validate(
            parsed,
            strict=True,
            context={"channel": channel},
        )
    except ValidationError as exc:
        raise ValueError(f"composer_llm_invalid: {exc}") from exc
    return {
        "subject": model.subject,
        "body": model.body,
        "cta": model.cta.model_dump(mode="python", exclude_none=True),
        "message_reason": model.message_reason,
    }


def _validate_final_composer_body(body: str) -> None:
    """
    Ensure full body after suffix append still satisfies length bounds.

    Args:
        body: Final outbound body string.
    Raises:
        ValueError: When body is empty or invalid under LongText rules.
    """

    _long_text_adapter.validate_python(body)


def _compose_suffix_append(
    channel: str,
    body: str,
    constraints: dict[str, object] | None,
) -> str:
    """
    Append case-supplied compliance text after the LLM draft when required.

    Args:
        channel: Selected channel (controls separator before appended suffix).
        body: Model-generated body before suffix.
        constraints: Case constraints; compliance_suffix comes from data, not code.
    Returns:
        Full body with optional suffix joined for the compliance checker.
    """

    if not constraints or constraints.get("include_opt_out_instructions") is not True:
        return body
    suffix = constraints.get("compliance_suffix")
    if suffix is None or not str(suffix).strip():
        return body
    sep = "\n" if channel == "email" else " "
    return f"{body.rstrip()}{sep}{str(suffix).strip()}"


def _call_openai_composer_once(
    channel: str,
    persona: str,
    lifecycle_stage: str,
    profile: dict[str, object],
    property_name: str,
    primary_cta: str,
    constraints: dict[str, object] | None,
    consent_verification: dict[str, object] | None,
) -> dict[str, object]:
    """
    Perform a single OpenAI chat completion and parse the composer JSON payload.

    Args:
        channel: Selected outreach channel.
        persona: Recipient persona.
        lifecycle_stage: Recipient lifecycle stage.
        profile: Schema-approved profile facts.
        property_name: Property being marketed.
        primary_cta: Required CTA intent.
        constraints: Case assertion constraints for style and suffix behavior.
        consent_verification: Result of check_consent for the selected channel.
    Returns:
        Composer payload dictionary with subject, body, cta, message_reason.
    Raises:
        ValueError: When the API response lacks required keys or parsable JSON.
        Exception: Provider or transport errors surfaced to retry logic.
    """

    from openai import OpenAI

    constraints = constraints or {}
    brand_extra = constraints.get("brand_style_notes")
    suffix_supplied = (
        constraints.get("include_opt_out_instructions") is True
        and constraints.get("compliance_suffix")
    )
    opt_out_rule = (
        "Do not end the body with opt-out or compliance closings; a case-provided "
        "suffix will be appended after your body."
        if suffix_supplied
        else (
            "When include_opt_out_instructions is true in constraints, end the body "
            "with an appropriate opt-out line for the channel."
        )
    )

    system_parts = [
        "Compose RealPage outreach. Return JSON only with exactly these keys — no others: "
        "subject, body, cta, message_reason.",
        "Exact structure and JSON types (strict — a field that must be a string cannot "
        "be a number, array, object, or boolean):",
        '{ "subject": string | null, "body": string, "cta": { "type": string, '
        '"options"?: string[] | null, "link"?: string | null }, "message_reason": string }',
        'The cta object may only contain keys: "type" (required), "options" (optional), '
        '"link" (optional).',
        "subject must be JSON null for channels sms and voice; for email it must be a "
        "non-empty string (not null).",
        "body and message_reason must be non-empty strings after trimming whitespace.",
        "Fair Housing and inclusion rules (obey in every message):",
        FAIR_HOUSING_RULES.strip(),
        "Default brand and channel style:",
        BRAND_STYLE_GUIDE.strip(),
        opt_out_rule,
        "Do not include URLs unless explicitly provided in input or constraints.",
        "Personalization contract — each profile field present in the input maps to a required body element. "
        "field 'first_name': recipient must be addressed by name. "
        "field 'city_interest': the city or neighbourhood value must appear verbatim in the body. "
        "field 'amenity_interest': each amenity must be named individually; never collapse to 'amenities'. "
        "A field present in input but absent from the body is a hard failure. "
        "For short channels like SMS, shorten other content rather than omit a profile field.",
    ]
    if brand_extra:
        system_parts.extend(["Case-specific brand notes:", str(brand_extra).strip()])

    client = OpenAI()
    response = client.chat.completions.create(
        model=os.getenv("REALPAGE_COMPOSER_MODEL", "gpt-4o"),
        temperature=0.2,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": "\n\n".join(system_parts)},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "channel": channel,
                        "persona": persona,
                        "lifecycle_stage": lifecycle_stage,
                        "profile": profile,
                        "property_name": property_name,
                        "primary_cta": primary_cta,
                        "constraints": constraints,
                        "consent_verification": consent_verification,
                    }
                ),
            },
        ],
    )
    content = response.choices[0].message.content or "{}"
    parsed = json.loads(content)
    if "body" not in parsed or "cta" not in parsed:
        raise ValueError("composer_response_missing_required_keys")
    return parsed


def compose_message(
    channel: str,
    persona: str,
    lifecycle_stage: str,
    profile: dict[str, object],
    property_name: str,
    primary_cta: str,
    constraints: dict[str, object] | None = None,
    consent_verification: dict[str, object] | None = None,
) -> ToolResultEnvelope:
    """
    TOOL: compose_message
    Purpose: Compose a personalized outreach message for one selected channel.
    When called: After channel selection and before compliance validation.
    Returns: ToolResultEnvelope(error, optional error_code, result dict or None).
    Note: Atomic — composes message content only; it does not select, schedule, or approve sending.

    Args:
        channel: Selected outreach channel.
        persona: Recipient persona.
        lifecycle_stage: Recipient lifecycle stage.
        profile: Profile facts approved by the schema boundary.
        property_name: Property being marketed.
        primary_cta: Required CTA intent.
        constraints: Assertion constraints (suffix, brand notes, flags) from the case.
        consent_verification: Structured consent check for the selected channel.
    Returns:
        Envelope containing subject/body/CTA/message_reason on success.
    """

    missing_key = not os.getenv("OPENAI_API_KEY")

    logger.info(
        "[compose_message] channel=%s persona=%s stage=%s cta=%s",
        channel,
        persona,
        lifecycle_stage,
        primary_cta,
    )

    if missing_key:
        code = "COMPOSER_NO_API_KEY"
        msg = "Message drafting credentials are not configured."
        append_agent_audit(
            component="compose_message",
            error_code=code,
            message=msg,
            detail={},
        )
        return ToolResultEnvelope(error=msg, error_code=code, result=None)

    last_problem: Any = None

    try:
        for attempt in range(_COMPOSER_MAX_ATTEMPTS):
            try:
                raw = _call_openai_composer_once(
                    channel,
                    persona,
                    lifecycle_stage,
                    profile,
                    property_name,
                    primary_cta,
                    constraints,
                    consent_verification,
                )
                composed = dict(_validate_composer_llm_payload(raw, channel))
                composed["body"] = _compose_suffix_append(
                    channel,
                    str(composed["body"]),
                    constraints,
                )
                _validate_final_composer_body(str(composed["body"]))
                return ToolResultEnvelope(
                    error=None,
                    error_code=None,
                    result=composed,
                )
            except Exception as exc:
                last_problem = exc
                logger.warning(
                    "[compose_message] attempt=%s/%s error=%s",
                    attempt + 1,
                    _COMPOSER_MAX_ATTEMPTS,
                    exc,
                    exc_info=False,
                )
                if attempt < _COMPOSER_MAX_ATTEMPTS - 1:
                    time.sleep(2**attempt)

        code = "COMPOSER_LLM_RETRY_EXHAUSTED"
        msg = "Message drafting failed after repeated attempts; information could not be retrieved."
        if last_problem is not None:
            detail = {
                "last_error_class": last_problem.__class__.__name__,
                "last_error": str(last_problem),
            }
        else:
            detail = {"last_error": "unknown"}

        append_agent_audit(
            component="compose_message",
            error_code=code,
            message=msg,
            detail=detail,
        )
        logger.error("[compose_message] llm_retry_exhausted last=%s", last_problem, exc_info=True)

        return ToolResultEnvelope(error=msg, error_code=code, result=None)
    except Exception as exc:
        logger.error("[compose_message] unexpected_after_retries error=%s", exc, exc_info=True)
        code = "COMPOSER_UNEXPECTED"
        msg = "Internal error while drafting outreach content."
        append_agent_audit(
            component="compose_message",
            error_code=code,
            message=msg,
            detail={"error_class": exc.__class__.__name__, "error": str(exc)},
        )
        return ToolResultEnvelope(error=msg, error_code=code, result=None)
