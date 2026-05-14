"""
File: compose_stub.py
Purpose: Test-only compose doubles (input + constraints only; never JSONL ``expected`` text).
Author: Sreeram
"""

from typing import Any

from backend.schemas import ToolResultEnvelope


def compose_message_payload_for_case(case: dict[str, Any], *, channel: str) -> dict[str, object]:
    """
    Build composer tool result payloads when ``compose_message`` is patched in pytest.

    Args:
        case: Parsed outreach case shaped like bundled JSONL samples.
        channel: Channel passed to compose_message (sms, email, or voice).

    Returns:
        Result dict keyed like compose_message envelope ``result``.
    """

    inp = case.get("input") if isinstance(case.get("input"), dict) else {}
    profile = inp.get("profile") if isinstance(inp.get("profile"), dict) else {}
    first_name = str(profile.get("first_name") or "there")
    property_name = str(inp.get("property_name") or "your community")
    assertions = case.get("assertions") if isinstance(case.get("assertions"), dict) else {}
    constraints = (
        assertions.get("constraints") if isinstance(assertions.get("constraints"), dict) else {}
    )

    suffix = str(constraints.get("compliance_suffix") or "Reply STOP to opt out.")
    normalized = str(channel or "sms").strip().lower()
    allowed_raw = constraints.get("allowed_link_domains")
    allowed_list: list[str] = []
    if isinstance(allowed_raw, list):
        allowed_list = [str(h).strip().lower() for h in allowed_raw if str(h).strip()]

    if normalized == "email":
        subject = f"Thanks for your interest in {property_name}"
        lines = [
            f"Hi {first_name},",
            "",
            f"Thanks for your interest in {property_name}.",
        ]
        tour_link: str | None = f"https://{allowed_list[0]}/tour" if allowed_list else None
        if tour_link:
            lines.extend(["", f"Book a tour: {tour_link}", ""])
        else:
            lines.extend(["", "Let us know when you would like to tour.", ""])
        lines.append(suffix)
        body = "\n".join(lines)

        cta: dict[str, object] = {
            "type": "book_tour",
            "options": ["Book a tour", "Ask a question"],
        }
        if tour_link:
            cta["link"] = tour_link

        return {
            "subject": subject,
            "body": body,
            "cta": cta,
            "message_reason": "offline_stub_synthetic_input_only",
        }

    opener = (
        f"Hi {first_name}, thanks for your interest in {property_name}. "
        f"Reply 1 to book a tour. {suffix}"
    )
    sms_voice_cta: dict[str, object] = {"type": "schedule_tour", "options": ["1. Book a tour"]}

    return {
        "subject": None,
        "body": opener,
        "cta": sms_voice_cta,
        "message_reason": "offline_stub_synthetic_input_only",
    }


def compose_message_envelope_for_case(
    case: dict[str, Any],
    *,
    channel: str,
) -> ToolResultEnvelope:
    """
    Tool envelope for patched ``compose_message``.

    Args:
        case: Parsed outreach case shaped like bundled JSONL samples.
        channel: Selected channel from agent kwargs (stub must match outbound channel).

    Returns:
        Envelope wrapping :func:`compose_message_payload_for_case`.
    """

    payload = compose_message_payload_for_case(case, channel=channel)
    return ToolResultEnvelope(error=None, error_code=None, result=dict(payload))


def compose_message_json_for_case(
    case: dict[str, Any],
    *,
    channel: str = "sms",
) -> ToolResultEnvelope:
    """
    Prefer passing ``channel`` from the patched ``compose_message`` kwargs.

    Args:
        case: Parsed outreach case.
        channel: Defaults to sms only when kwargs are unavailable.

    Returns:
        Same as :func:`compose_message_envelope_for_case`.
    """

    return compose_message_envelope_for_case(case, channel=channel)


def compose_message_envelope_from_compose_kwargs(
    *,
    channel: str,
    profile: dict[str, object],
    property_name: str,
    constraints: dict[str, object] | None = None,
) -> ToolResultEnvelope:
    """
    Map ``compose_message(...)`` keyword args into :func:`compose_message_payload_for_case` shape.
    """

    pseudo_case: dict[str, Any] = {
        "input": {
            "profile": dict(profile),
            "property_name": property_name,
        },
        "assertions": {"constraints": dict(constraints or {})},
    }
    return compose_message_json_for_case(pseudo_case, channel=channel)
