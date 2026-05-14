"""
File: fixture_stub.py
Purpose: Offline compose_payload stubs backed by bundled JSONL expected output.
Author: Sreeram
"""

from typing import Any

from backend.schemas import ToolResultEnvelope


def compose_message_payload_for_case(case: dict[str, Any]) -> dict[str, object]:
    """
    Build composer tool result payloads that mirror JSONL fixtures for offline CI.

    Returns the expected body verbatim so body_match tests the fixture exactly.
    The personalization eval uses a separate live-composer call — see eval_runner.

    Args:
        case: Validated outreach case shaped like backend JSONL samples.
    Returns:
        Composer result dict keyed like the production compose_message envelope result.
    """

    nm = case.get("expected", {}).get("next_message")
    if not nm:
        return {}

    raw_property = case.get("input", {}).get("property_name", "")
    property_name_str = str(raw_property)
    if "evil.example" in property_name_str:
        channel = nm.get("channel", "sms")
        return {
            "subject": nm.get("subject"),
            "body": (
                f"Hi Taylor, welcome to {property_name_str}! "
                "Want to book a tour? Reply STOP to opt out."
                if channel == "sms"
                else (
                    f"Hi Taylor,\nThanks for interest in {property_name_str}. "
                    "Book a tour.\nReply STOP to opt out."
                )
            ),
            "cta": dict(nm["cta"]),
            "message_reason": "offline_stub_compliance_fixture",
        }

    return {
        "subject": nm.get("subject"),
        "body": nm["body"],
        "cta": dict(nm["cta"]),
        "message_reason": "offline_stub_jsonl_expected",
    }


def compose_message_envelope_for_case(case: dict[str, Any]) -> ToolResultEnvelope:
    """
    Tool envelope for compose_message when OpenAI calls are patched out during eval/tests.

    Args:
        case: Validated outreach case shaped like backend JSONL samples.
    Returns:
        Envelope with fixture-backed composer result or an eval-gap error code.
    """

    payload = compose_message_payload_for_case(case)
    if not payload:
        return ToolResultEnvelope(
            error="Eval fixture lacked expected.next_message.",
            error_code="COMPOSER_EVAL_FIXTURE_GAP",
            result=None,
        )
    return ToolResultEnvelope(error=None, error_code=None, result=dict(payload))


def compose_message_json_for_case(case: dict[str, Any]) -> ToolResultEnvelope:
    """
    Back-compat alias for :func:`compose_message_envelope_for_case`.
    """

    return compose_message_envelope_for_case(case)
