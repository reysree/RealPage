"""
File: message_composer.py
Purpose: Tool for composing channel-specific outreach messages and CTAs.
Author: Sreeram
"""

import json
import logging
import os
from typing import Any
from urllib.parse import urlparse

from pydantic import TypeAdapter, ValidationError

from backend.core.audit_log import append_agent_audit
from backend.core.constants import BRAND_STYLE_GUIDE, FAIR_HOUSING_RULES
from backend.schemas import ComposerLlmOutput, LongText, ToolResultEnvelope

logger = logging.getLogger(__name__)

_COMPOSER_MAX_ATTEMPTS = 3
_DEFAULT_MAX_COMPLETION_TOKENS_BY_CHANNEL = {
    "sms": 220,
    "voice": 220,
    "email": 300,
}

_long_text_adapter = TypeAdapter(LongText)


def _env_flag(name: str, *, default: bool = False) -> bool:
    """
    Read a boolean feature flag from the environment.

    Args:
        name: Environment variable name.
        default: Value used when the variable is absent.
    Returns:
        Boolean flag value.
    """

    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, *, default: float) -> float:
    """
    Read a bounded float option from the environment.

    Args:
        name: Environment variable name.
        default: Value used when the variable is absent or invalid.
    Returns:
        Parsed float value.
    """

    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning("[%s] invalid float value=%r; using default=%s", name, raw, default)
        return default


def _env_int(name: str) -> int | None:
    """
    Read an optional positive integer option from the environment.

    Args:
        name: Environment variable name.
    Returns:
        Parsed integer or None when absent/invalid.
    """

    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return None
    try:
        value = int(raw)
    except ValueError:
        logger.warning("[%s] invalid integer value=%r; ignoring", name, raw)
        return None
    return value if value > 0 else None


def _max_completion_tokens_for_channel(channel: str) -> int:
    """
    Resolve the completion-token cap used to avoid unbounded generation latency.

    Args:
        channel: Selected outreach channel.
    Returns:
        Environment override or a channel-specific safe default.
    """

    override = _env_int("REALPAGE_COMPOSER_MAX_TOKENS")
    if override is not None:
        return override
    return _DEFAULT_MAX_COMPLETION_TOKENS_BY_CHANNEL.get(channel, 300)


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


def _suffix_applies_to_channel(suffix: str, channel: str) -> bool:
    """
    Return False when the suffix explicitly references email but the channel is not email.

    Args:
        suffix: Compliance suffix string from case constraints.
        channel: Selected outreach channel.
    Returns:
        True when the suffix is safe to append on this channel.
    """

    if channel == "email":
        return True
    lower = suffix.lower()
    # Suffixes that mention "email" or "unsubscribe" are email-specific and must not
    # be appended to SMS/voice bodies; the composer LLM will generate channel-appropriate
    # opt-out copy instead via the opt_out_rule prompt.
    return "email" not in lower and "unsubscribe" not in lower


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
    suffix_str = str(suffix).strip()
    if not _suffix_applies_to_channel(suffix_str, channel):
        return body
    sep = "\n" if channel == "email" else " "
    return f"{body.rstrip()}{sep}{suffix_str}"


def _normalize_allowlist_host(domain_entry: str) -> str:
    """
    Normalize one allowed-link domain entry to a bare hostname.

    Args:
        domain_entry: Raw domain string from constraints (may include scheme or path).
    Returns:
        Lowercase hostname, or empty when unusable.
    """

    stripped = domain_entry.strip()
    if not stripped:
        return ""
    lower = stripped.lower()
    if "://" in lower:
        parsed = urlparse(lower)
        return (parsed.hostname or "").lower()
    return lower.split("/")[0].strip()


def _booking_path_for_primary_cta(primary_cta: str) -> str:
    """
    Map primary_cta intent to a path under an allowed booking domain.

    Args:
        primary_cta: Constraint primary_cta string (e.g. book_tour).
    Returns:
        URL path beginning with / suitable for https://{host}{path}.
    """

    normalized = (primary_cta or "book_tour").strip().strip("/").replace("_", "-")
    if normalized == "book-tour":
        return "/tour"
    return f"/{normalized}"


def _ensure_cta_link_from_allowlist(
    cta: dict[str, object],
    constraints: dict[str, object] | None,
    primary_cta: str,
) -> None:
    """
    Set cta.link when constraints authorize domains but the model omitted a URL.

    Args:
        cta: Composer CTA dict (mutated in place when applicable).
        constraints: Case constraint payload; reads allowed_link_domains.
        primary_cta: Declared CTA intent used to choose a default path.
    """

    if not constraints:
        return
    raw_domains = constraints.get("allowed_link_domains")
    if not isinstance(raw_domains, list) or not raw_domains:
        return
    first = raw_domains[0]
    if not isinstance(first, str):
        return
    host = _normalize_allowlist_host(first)
    if not host:
        return
    existing = cta.get("link")
    if isinstance(existing, str) and existing.strip():
        return
    path = _booking_path_for_primary_cta(str(constraints.get("primary_cta") or primary_cta))
    cta["link"] = f"https://{host}{path}"


def _profile_interest_text(profile: dict[str, object]) -> str:
    """
    Convert optional profile interest fields into concise message text.

    Args:
        profile: Schema-approved profile facts.
    Returns:
        Natural-language interest text, or an empty string.
    """

    city = profile.get("city_interest")
    if isinstance(city, str) and city.strip():
        return city.strip()
    amenities = profile.get("amenity_interest")
    if isinstance(amenities, list):
        clean = [str(item).strip() for item in amenities if str(item).strip()]
        if len(clean) == 1:
            return clean[0]
        if len(clean) > 1:
            return ", ".join(clean[:-1]) + f" and {clean[-1]}"
    return ""


def _fast_path_allowed(
    channel: str,
    persona: str,
    lifecycle_stage: str,
    primary_cta: str,
    constraints: dict[str, object] | None,
) -> bool:
    """
    Decide whether deterministic composition is safe for this case.

    Args:
        channel: Selected channel.
        persona: Recipient persona.
        lifecycle_stage: Recipient lifecycle stage.
        primary_cta: Required CTA intent.
        constraints: Assertion constraints from the case.
    Returns:
        True when the case falls in the common, low-risk outreach path.
    """

    if persona != "prospect" or lifecycle_stage not in {"new", "open"}:
        return False
    if channel not in {"sms", "email", "voice"}:
        return False
    if primary_cta != "book_tour":
        return False
    if constraints and constraints.get("brand_style_notes"):
        return False
    return True


def _compose_fast_path_payload(
    channel: str,
    persona: str,
    lifecycle_stage: str,
    profile: dict[str, object],
    property_name: str,
    primary_cta: str,
    constraints: dict[str, object] | None,
) -> dict[str, object] | None:
    """
    Compose common outreach cases without an LLM when the fast path is enabled.

    Args:
        channel: Selected outreach channel.
        persona: Recipient persona.
        lifecycle_stage: Recipient lifecycle stage.
        profile: Schema-approved profile facts.
        property_name: Property being marketed.
        primary_cta: Required CTA intent.
        constraints: Assertion constraints from the case.
    Returns:
        Composer payload, or None when the case should fall back to the LLM path.
    """

    constraints = constraints or {}
    if not _fast_path_allowed(channel, persona, lifecycle_stage, primary_cta, constraints):
        return None

    first_name = str(profile.get("first_name") or "there").strip() or "there"
    interest = _profile_interest_text(profile)
    interest_fragment = f" about {interest}" if interest else ""
    property_display = property_name.strip() or "your community"

    if channel == "email":
        host = ""
        domains = constraints.get("allowed_link_domains")
        if isinstance(domains, list) and domains:
            first = domains[0]
            if isinstance(first, str):
                host = _normalize_allowlist_host(first)
        link = f"https://{host}{_booking_path_for_primary_cta(primary_cta)}" if host else None
        body_lines = [
            f"Hi {first_name},",
            "",
            (
                f"Thanks for your interest in {property_display}{interest_fragment}. "
                "Would you like to book a tour?"
            ),
        ]
        if link:
            body_lines.extend(["", f"Book a tour: {link}"])
        cta: dict[str, object] = {"type": "book_tour"}
        if link:
            cta["link"] = link
        return {
            "subject": f"Tour {property_display}",
            "body": "\n".join(body_lines),
            "cta": cta,
            "message_reason": "deterministic_fast_path_common_outreach",
        }

    if channel == "voice":
        return {
            "subject": None,
            "body": (
                f"Hi {first_name}. This is {property_display}. "
                "Press 1 to book a tour or 2 to ask a question. Press 3 to opt out."
            ),
            "cta": {"type": "schedule_tour", "options": ["1. Book a tour", "2. Ask a question"]},
            "message_reason": "deterministic_fast_path_common_outreach",
        }

    return {
        "subject": None,
        "body": (
            f"Hi {first_name}, thanks for your interest in {property_display}{interest_fragment}. "
            "Reply 1 to book a tour."
        ),
        "cta": {"type": "schedule_tour", "options": ["1. Book a tour"]},
        "message_reason": "deterministic_fast_path_common_outreach",
    }


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
    raw_suffix = str(constraints.get("compliance_suffix") or "").strip()
    suffix_supplied = (
        constraints.get("include_opt_out_instructions") is True
        and bool(raw_suffix)
        and _suffix_applies_to_channel(raw_suffix, channel)
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
        "cta.link must be JSON null for channels sms and voice; only email messages may "
        "include a link.",
        "body and message_reason must be non-empty strings after trimming whitespace.",
        "Fair Housing and inclusion rules (obey in every message):",
        FAIR_HOUSING_RULES.strip(),
        "Default brand and channel style:",
        BRAND_STYLE_GUIDE.strip(),
        opt_out_rule,
        "Do not invent unrelated URLs. Use listing_url only when present on an allowed "
        "host. When constraints include allowed_link_domains (non-empty array), set "
        "cta.link to https://{hostname}{path} where hostname is the first listed domain "
        "(exact host match) and path is /tour when primary_cta is book_tour, otherwise "
        "a short path derived from primary_cta.",
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
    request: dict[str, object] = {
        "model": os.getenv("REALPAGE_COMPOSER_MODEL", "gpt-4o"),
        "temperature": _env_float("REALPAGE_COMPOSER_TEMPERATURE", default=0.0),
        "response_format": {"type": "json_object"},
        "messages": [
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
    }
    request["max_completion_tokens"] = _max_completion_tokens_for_channel(channel)

    response = client.chat.completions.create(
        **request,
    )
    choice = response.choices[0]
    finish_reason = getattr(choice, "finish_reason", None)
    if finish_reason == "length":
        raise ValueError("composer_response_truncated_by_max_completion_tokens")
    content = choice.message.content or "{}"
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

    constraints = constraints or {}
    if _env_flag("REALPAGE_COMPOSER_FAST_PATH"):
        fast_payload = _compose_fast_path_payload(
            channel,
            persona,
            lifecycle_stage,
            profile,
            property_name,
            primary_cta,
            constraints,
        )
        if fast_payload is not None:
            composed = dict(_validate_composer_llm_payload(fast_payload, channel))
            _ensure_cta_link_from_allowlist(
                composed["cta"],
                constraints,
                primary_cta,
            )
            composed["body"] = _compose_suffix_append(
                channel,
                str(composed["body"]),
                constraints,
            )
            _validate_final_composer_body(str(composed["body"]))
            return ToolResultEnvelope(error=None, error_code=None, result=composed)

    missing_key = not os.getenv("OPENAI_API_KEY")

    logger.info(
        "[compose_message] channel=%s persona=%s stage=%s cta=%s",
        channel,
        persona,
        lifecycle_stage,
        primary_cta,
    )

    if missing_key:
        code = "OPENAI_API_KEY_MISSING"
        msg = (
            "OPENAI_API_KEY is not set. Put it in backend/.env or export it in your shell "
            "(same key the OpenAI SDK uses)."
        )
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
                _ensure_cta_link_from_allowlist(
                    composed["cta"],
                    constraints,
                    primary_cta,
                )
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
