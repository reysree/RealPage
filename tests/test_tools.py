"""
File: test_tools.py
Purpose: Behavior tests for outreach decision tools.
Author: Sreeram
"""

import json

from unittest.mock import patch

import pytest
from pydantic import ValidationError

from backend.schemas_llm import ComposerLlmOutput, FairHousingJudgeLlmOutput
from backend.tools import ALL_TOOLS
from backend.tools.channel_selector import select_channel
from backend.tools.compliance import check_compliance
from backend.tools.consent import check_consent
from backend.tools.input_security import check_input_security
from backend.tools.message_composer import compose_message
from backend.tools.timing import determine_send_time


def parse_tool_result(result: str) -> dict:
    """
    Parse a structured JSON tool result for behavior assertions.

    Args:
        result: JSON string returned by a tool.
    Returns:
        Parsed tool result dictionary.
    """

    return json.loads(result)


def test_consent_and_channel_selection_follow_preference_order() -> None:
    """
    Verify consent filtering and fallback channel selection are deterministic.
    """

    consent_result = parse_tool_result(
        check_consent("sms", {"sms_opt_in": True, "email_opt_in": False})
    )
    assert consent_result["result"]["eligible"] is True

    selection = parse_tool_result(
        select_channel(
            ["sms", "email"],
            {"sms_opt_in": False, "email_opt_in": True, "voice_opt_in": False},
        )
    )

    assert selection["result"]["selected_channel"] == "email"
    assert selection["result"]["fallback_channel"] == "email"
    assert selection["result"]["send"] is True


def test_timing_returns_next_day_morning_in_recipient_timezone() -> None:
    """
    Verify send timing is scheduled for the next local morning.
    """

    result = parse_tool_result(
        determine_send_time("America/Chicago", "2025-12-08T15:04:00Z", "new")
    )

    assert result["result"]["send_at"] == "2025-12-09T09:00:00-06:00"


def test_compliance_blocks_missing_opt_out_language() -> None:
    """
    Verify compliance rejects messages without required opt-out instructions.
    """

    result = parse_tool_result(
        check_compliance(
            "Hi Taylor, book a tour this week.",
            {"include_opt_out_instructions": True, "no_pii_leak": True},
        )
    )

    assert result["result"]["passed"] is False
    assert "missing_opt_out" in result["result"]["violations"]


def test_compliance_blocks_pii_urls_and_protected_class_language() -> None:
    """
    Verify compliance rejects unsafe content beyond missing opt-out text.
    """

    pii_result = parse_tool_result(
        check_compliance(
            "Hi Taylor, call 555-123-4567 or visit https://bad.example. Reply STOP to opt out.",
            {
                "include_opt_out_instructions": True,
                "no_pii_leak": True,
                "allowed_link_domains": ["oakridge.example"],
            },
        )
    )
    assert pii_result["result"]["passed"] is False
    assert "pii_leak" in pii_result["result"]["violations"]
    assert "unapproved_link" in pii_result["result"]["violations"]

    fair_housing_result = parse_tool_result(
        check_compliance(
            "This building is perfect for families with children. Reply STOP to opt out.",
            {
                "include_opt_out_instructions": True,
                "no_sensitive_discrimination": True,
            },
        )
    )
    assert fair_housing_result["result"]["passed"] is False
    assert "protected_class_language" in fair_housing_result["result"]["violations"]


def test_compliance_blocks_broader_pii_and_url_spoofing() -> None:
    """
    Verify compliance catches broader PII and parses URL hosts safely.
    """

    pii_result = parse_tool_result(
        check_compliance(
            "DOB 01/02/1990, SSN 123-45-6789, income $45000. Reply STOP to opt out.",
            {"include_opt_out_instructions": True, "no_pii_leak": True},
        )
    )
    assert pii_result["result"]["passed"] is False
    assert "pii_leak" in pii_result["result"]["violations"]

    spoofed_url_result = parse_tool_result(
        check_compliance(
            "Visit https://oakridge.example@evil.example/tour. Reply STOP to opt out.",
            {
                "include_opt_out_instructions": True,
                "allowed_link_domains": ["oakridge.example"],
            },
        )
    )
    assert spoofed_url_result["result"]["passed"] is False
    assert "unapproved_link" in spoofed_url_result["result"]["violations"]


def test_compliance_blocks_state_local_and_steering_phrases() -> None:
    """
    Verify compliance catches broader protected-class and steering language.
    """

    result = parse_tool_result(
        check_compliance(
            "Adults only community, ideal for young professionals and no kids. Reply STOP to opt out.",
            {
                "include_opt_out_instructions": True,
                "no_sensitive_discrimination": True,
            },
        )
    )

    assert result["result"]["passed"] is False
    assert "protected_class_language" in result["result"]["violations"]


def test_composer_sms_maps_llm_payload_to_tool_envelope(monkeypatch) -> None:
    """
    Verify SMS compose_message parses the LLM response into the bounded tool envelope.
    """

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key")

    llm_payload = {
        "subject": None,
        "body": (
            "Hi Taylor — Oak Ridge Apartments. Want to tour? Reply STOP to opt out."
        ),
        "cta": {"type": "schedule_tour", "options": ["Thu", "Fri"]},
        "message_reason": "test_stub",
    }

    with patch(
        "backend.tools.message_composer._call_openai_composer_once",
        return_value=llm_payload,
    ):
        raw = compose_message(
            channel="sms",
            persona="prospect",
            lifecycle_stage="new",
            profile={"first_name": "Taylor", "city_interest": "Richardson, TX"},
            property_name="Oak Ridge Apartments",
            primary_cta="book_tour",
        )

    result = parse_tool_result(raw)
    assert result["error"] is None
    assert result["result"]["subject"] is None
    assert "Taylor" in result["result"]["body"]
    assert "STOP" in result["result"]["body"]
    assert result["result"]["cta"]["type"] == "schedule_tour"


def test_composer_email_maps_llm_payload_without_links(monkeypatch) -> None:
    """
    Verify email compose_message keeps URLs absent when stubbed payloads avoid them.
    """

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key")

    llm_payload = {
        "subject": "Tour Oak Ridge Apartments",
        "body": "Hi Taylor,\nThanks for Oak Ridge Apartments.\nReply STOP to opt out.",
        "cta": {"type": "schedule_tour"},
        "message_reason": "test_stub_email",
    }

    with patch(
        "backend.tools.message_composer._call_openai_composer_once",
        return_value=llm_payload,
    ):
        raw = compose_message(
            channel="email",
            persona="prospect",
            lifecycle_stage="open",
            profile={"first_name": "Taylor", "amenity_interest": ["pool", "fitness"]},
            property_name="Oak Ridge Apartments",
            primary_cta="book_tour",
        )

    result = parse_tool_result(raw)
    assert result["error"] is None
    assert "https://" not in result["result"]["body"]
    assert result["result"]["cta"] == {"type": "schedule_tour"}


def test_composer_returns_error_when_api_key_missing(monkeypatch) -> None:
    """
    Verify composer emits a coded error when OpenAI credentials are not configured.
    """

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    raw = compose_message(
        channel="sms",
        persona="prospect",
        lifecycle_stage="new",
        profile={"first_name": "Taylor"},
        property_name="Oak Ridge Apartments",
        primary_cta="book_tour",
    )
    result = parse_tool_result(raw)
    assert result["result"] is None
    assert result["error_code"] == "COMPOSER_NO_API_KEY"


@patch("backend.tools.message_composer.time.sleep")
def test_composer_retries_openai_then_succeeds(mock_sleep, monkeypatch) -> None:
    """
    Verify backoff retries execute before accepting a recovered LLM payload.
    """

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key")

    success = {
        "subject": None,
        "body": "Hi Taylor. Reply STOP to opt out.",
        "cta": {"type": "schedule_tour"},
        "message_reason": "after_retries",
    }
    failures = [ValueError("transient_a"), ValueError("transient_b")]

    def side_effect(*_a, **_k):
        if failures:
            raise failures.pop(0)
        return success

    with patch(
        "backend.tools.message_composer._call_openai_composer_once",
        side_effect=side_effect,
    ):
        raw = compose_message(
            channel="sms",
            persona="prospect",
            lifecycle_stage="new",
            profile={"first_name": "Taylor"},
            property_name="Oak Ridge Apartments",
            primary_cta="book_tour",
        )

    parsed = parse_tool_result(raw)
    assert parsed["error"] is None
    assert parsed["result"]["cta"]["type"] == "schedule_tour"
    assert mock_sleep.call_count == 2
    mock_sleep.assert_any_call(1)
    mock_sleep.assert_any_call(2)


def test_composer_appends_case_compliance_suffix(monkeypatch) -> None:
    """
    Verify compliance_suffix from case constraints is appended after the LLM draft.
    """

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key")

    llm_payload = {
        "subject": None,
        "body": "Hi Taylor — Oak Ridge tour this week.",
        "cta": {"type": "schedule_tour", "options": ["Thu", "Fri"]},
        "message_reason": "suffix_fixture",
    }

    with patch(
        "backend.tools.message_composer._call_openai_composer_once",
        return_value=llm_payload,
    ):
        raw = compose_message(
            channel="sms",
            persona="prospect",
            lifecycle_stage="new",
            profile={"first_name": "Taylor"},
            property_name="Oak Ridge Apartments",
            primary_cta="book_tour",
            constraints={
                "include_opt_out_instructions": True,
                "compliance_suffix": "Reply STOP to opt out.",
            },
        )

    result = parse_tool_result(raw)
    assert result["error"] is None
    assert result["result"]["body"] == (
        "Hi Taylor — Oak Ridge tour this week. Reply STOP to opt out."
    )


@patch("backend.tools.message_composer.time.sleep")
def test_composer_rejects_blank_required_fields(mock_sleep, monkeypatch) -> None:
    """
    Verify whitespace-only body fails Pydantic validation and surfaces as tool error.
    """

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key")

    bad_payload = {
        "subject": None,
        "body": "   ",
        "cta": {"type": "schedule_tour"},
        "message_reason": "bad_body",
    }

    with patch(
        "backend.tools.message_composer._call_openai_composer_once",
        return_value=bad_payload,
    ):
        raw = compose_message(
            channel="sms",
            persona="prospect",
            lifecycle_stage="new",
            profile={"first_name": "Taylor"},
            property_name="Oak Ridge Apartments",
            primary_cta="book_tour",
        )

    result = parse_tool_result(raw)
    assert result["result"] is None
    assert result["error_code"] == "COMPOSER_LLM_RETRY_EXHAUSTED"


@patch("backend.tools.message_composer.time.sleep")
def test_composer_requires_email_subject(mock_sleep, monkeypatch) -> None:
    """
    Verify email channel rejects missing or blank subject after LLM response.
    """

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key")

    bad_payload = {
        "subject": None,
        "body": "Hi Taylor, body here.",
        "cta": {"type": "schedule_tour"},
        "message_reason": "no_subject",
    }

    with patch(
        "backend.tools.message_composer._call_openai_composer_once",
        return_value=bad_payload,
    ):
        raw = compose_message(
            channel="email",
            persona="prospect",
            lifecycle_stage="open",
            profile={"first_name": "Taylor"},
            property_name="Oak Ridge Apartments",
            primary_cta="book_tour",
        )

    result = parse_tool_result(raw)
    assert result["result"] is None
    assert result["error_code"] == "COMPOSER_LLM_RETRY_EXHAUSTED"


def test_input_security_blocks_embedded_private_url() -> None:
    """
    Verify prose fields carrying http(s) links to non-public hosts fail screening.
    """

    payload = parse_tool_result(
        check_input_security(
            {"constraints.brand_style_notes": "Compare rates at https://192.168.1.10/x"},
        )
    )

    assert payload["result"]["passed"] is False
    assert any("UNSAFE_URL" in flag for flag in payload["result"]["flags"])


def test_input_security_blocks_dangerous_scheme_tokens() -> None:
    """
    Verify javascript:/data: style payloads are blocked even without http parsing.
    """

    payload = parse_tool_result(
        check_input_security({"property_name": 'Click javascript:alert(1) now'}),
    )

    assert payload["result"]["passed"] is False
    assert any("DANGEROUS_URL_SCHEME" in flag for flag in payload["result"]["flags"])


def test_all_tools_exports_every_phase2_tool() -> None:
    """
    Verify the tool registry exposes all planned Phase 2 tools.
    """

    tool_names = [tool.__name__ for tool in ALL_TOOLS]

    assert tool_names == [
        "check_input_security",
        "check_consent",
        "select_channel",
        "compose_message",
        "determine_send_time",
        "check_compliance",
    ]


def test_composer_llm_schema_strict_types_and_shape() -> None:
    """
    Verify compose_message LLM JSON must match exact types (strict) and allowed keys.
    """

    base = {
        "subject": None,
        "body": "valid body text here",
        "cta": {"type": "schedule_tour"},
        "message_reason": "reason",
    }
    ComposerLlmOutput.model_validate(
        base,
        strict=True,
        context={"channel": "sms"},
    )

    with pytest.raises(ValidationError):
        ComposerLlmOutput.model_validate(
            {**base, "body": 123},
            strict=True,
            context={"channel": "sms"},
        )

    with pytest.raises(ValidationError):
        ComposerLlmOutput.model_validate(
            {**base, "unexpected": True},
            strict=True,
            context={"channel": "sms"},
        )

    with pytest.raises(ValidationError):
        ComposerLlmOutput.model_validate(
            {
                **base,
                "cta": {"type": "schedule_tour", "extra": "nope"},
            },
            strict=True,
            context={"channel": "sms"},
        )

    with pytest.raises(ValidationError):
        ComposerLlmOutput.model_validate(
            {
                **base,
                "subject": "should not appear on sms",
            },
            strict=True,
            context={"channel": "sms"},
        )


def test_composer_llm_schema_rejects_disallowed_control_chars_in_body() -> None:
    """
    Verify model output body cannot include NUL or other C0 controls (except tab/cr/lf).
    """

    with pytest.raises(ValidationError):
        ComposerLlmOutput.model_validate(
            {
                "subject": None,
                "body": "bad\x00byte",
                "cta": {"type": "schedule_tour"},
                "message_reason": "x",
            },
            strict=True,
            context={"channel": "sms"},
        )

    with pytest.raises(ValidationError):
        ComposerLlmOutput.model_validate(
            {
                "subject": None,
                "body": "bad\x01control",
                "cta": {"type": "schedule_tour"},
                "message_reason": "x",
            },
            strict=True,
            context={"channel": "sms"},
        )


def test_fair_housing_judge_llm_schema_strict_boolean_only() -> None:
    """
    Verify judge JSON is exactly passed: boolean with no extra keys or string booleans.
    """

    assert (
        FairHousingJudgeLlmOutput.model_validate({"passed": False}, strict=True).passed
        is False
    )

    with pytest.raises(ValidationError):
        FairHousingJudgeLlmOutput.model_validate({"passed": "true"}, strict=True)

    with pytest.raises(ValidationError):
        FairHousingJudgeLlmOutput.model_validate({"passed": 1}, strict=True)

    with pytest.raises(ValidationError):
        FairHousingJudgeLlmOutput.model_validate(
            {"passed": True, "rationale": "no"},
            strict=True,
        )
