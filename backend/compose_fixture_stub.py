"""
File: compose_fixture_stub.py
Purpose: Offline compose_payload stubs backed by bundled JSONL expected output.
Author: Sreeram
"""

from __future__ import annotations

import json
from typing import Any


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


def compose_message_json_for_case(case: dict[str, Any]) -> str:
    """
    JSON tool string for compose_message when OpenAI calls are patched out.

    Args:
        case: Validated outreach case shaped like backend JSONL samples.
    Returns:
        Tool JSON envelope with error None and fixture-backed result payload.
    """

    payload = compose_message_payload_for_case(case)
    if not payload:
        return json.dumps(
            {
                "error": "Eval fixture lacked expected.next_message.",
                "error_code": "COMPOSER_EVAL_FIXTURE_GAP",
                "result": None,
            }
        )
    return json.dumps({"error": None, "error_code": None, "result": payload})
