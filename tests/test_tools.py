"""
File: test_tools.py
Purpose: Behavior tests for outreach decision tools.
Author: Sreeram
"""

from unittest.mock import patch

import pytest
from pydantic import ValidationError

from backend.schemas import ToolResultEnvelope
from backend.schemas import ComposerLlmOutput, FairHousingJudgeLlmOutput
from backend.schemas.models import RunRequest, ThresholdsRecord
from backend.tools import ALL_TOOLS
from backend.tools.channel_selector import select_channel
from backend.tools.compliance import check_compliance
from backend.tools.consent import check_consent
from backend.tools.input_security import check_input_security
import backend.tools.message_composer as message_composer
from backend.tools.message_composer import _suffix_applies_to_channel, compose_message
from backend.tools.timing import determine_send_time

# Minimal valid case dict reused across schema-level tests.
_MINIMAL_CASE: dict = {
    "task_id": "schema_test",
    "persona": "prospect",
    "lifecycle_stage": "new",
    "consent": {"email_opt_in": True, "sms_opt_in": True, "voice_opt_in": False},
    "channel_preferences": ["sms"],
    "input": {
        "property_name": "Oak Ridge Apartments",
        "move_date_target": "2026-02-15",
        "last_interaction": "2025-12-06T11:30:00Z",
        "timezone": "America/Chicago",
        "language": "en",
        "profile": {"first_name": "Taylor"},
    },
    "assertions": {
        "required_states": [
            "consent_verified",
            "fair_housing_check_passed",
            "brand_style_applied",
        ],
        "constraints": {
            "no_pii_leak": True,
            "include_opt_out_instructions": True,
            "primary_cta": "book_tour",
            "compliance_suffix": "Reply STOP to opt out.",
        },
    },
}


def parse_tool_result(result: ToolResultEnvelope) -> dict:
    """
    Dump a structured tool envelope for behavior assertions.

    Args:
        result: Envelope returned by an in-process tool.
    Returns:
        Tool result dictionary shaped like the prior JSON tool contract.
    """

    return result.model_dump(mode="python")


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
    assert result["error_code"] == "OPENAI_API_KEY_MISSING"


def test_composer_fast_path_bypasses_openai_for_common_sms_case(monkeypatch) -> None:
    """
    Verify the opt-in deterministic fast path can produce common SMS output without OpenAI.
    """

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("REALPAGE_COMPOSER_FAST_PATH", "1")

    raw = compose_message(
        channel="sms",
        persona="prospect",
        lifecycle_stage="new",
        profile={"first_name": "Taylor", "city_interest": "Richardson, TX"},
        property_name="Oak Ridge Apartments",
        primary_cta="book_tour",
        constraints={
            "include_opt_out_instructions": True,
            "compliance_suffix": "Reply STOP to opt out.",
        },
    )

    result = parse_tool_result(raw)
    assert result["error"] is None
    assert result["result"]["subject"] is None
    assert "Taylor" in result["result"]["body"]
    assert "Richardson, TX" in result["result"]["body"]
    assert "Reply STOP to opt out." in result["result"]["body"]
    assert result["result"]["message_reason"] == "deterministic_fast_path_common_outreach"


def test_composer_fast_path_falls_back_for_brand_notes_without_api_key(monkeypatch) -> None:
    """
    Verify complex brand-note cases still require the LLM composer path.
    """

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("REALPAGE_COMPOSER_FAST_PATH", "1")

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
            "brand_style_notes": "Use a special campaign voice.",
        },
    )

    result = parse_tool_result(raw)
    assert result["result"] is None
    assert result["error_code"] == "OPENAI_API_KEY_MISSING"


def test_openai_composer_uses_latency_tuning_environment(monkeypatch) -> None:
    """
    Verify optimized benchmark knobs flow into the OpenAI request.
    """

    class _FakeCompletions:
        """
        Minimal fake OpenAI completions resource that records create() kwargs.
        """

        def __init__(self) -> None:
            self.kwargs = {}

        def create(self, **kwargs):
            """
            Return a minimal chat completion shape.
            """

            self.kwargs = kwargs
            message = type(
                "Message",
                (),
                {
                    "content": (
                        '{"subject": null, "body": "Hi Taylor. Reply STOP to opt out.", '
                        '"cta": {"type": "schedule_tour"}, "message_reason": "test"}'
                    )
                },
            )
            choice = type("Choice", (), {"message": message, "finish_reason": "stop"})
            return type("Response", (), {"choices": [choice]})

    class _FakeOpenAI:
        """
        Minimal fake OpenAI client.
        """

        def __init__(self) -> None:
            self.completions = _FakeCompletions()
            self.chat = type("Chat", (), {"completions": self.completions})

    fake_client = _FakeOpenAI()
    monkeypatch.setenv("REALPAGE_COMPOSER_MODEL", "gpt-4o-mini")
    monkeypatch.setenv("REALPAGE_COMPOSER_TEMPERATURE", "0")
    monkeypatch.setenv("REALPAGE_COMPOSER_MAX_TOKENS", "220")

    with patch("openai.OpenAI", return_value=fake_client):
        payload = message_composer._call_openai_composer_once(
            channel="sms",
            persona="prospect",
            lifecycle_stage="new",
            profile={"first_name": "Taylor"},
            property_name="Oak Ridge Apartments",
            primary_cta="book_tour",
            constraints={},
            consent_verification={"eligible": True},
        )

    assert payload["body"] == "Hi Taylor. Reply STOP to opt out."
    assert fake_client.completions.kwargs["model"] == "gpt-4o-mini"
    assert fake_client.completions.kwargs["temperature"] == 0.0
    assert fake_client.completions.kwargs["max_completion_tokens"] == 220


def test_openai_composer_uses_dynamic_max_completion_tokens_by_channel(monkeypatch) -> None:
    """
    Verify default token caps are high enough by channel without manual overrides.
    """

    class _FakeCompletions:
        """
        Minimal fake OpenAI completions resource.
        """

        def __init__(self) -> None:
            self.kwargs = {}

        def create(self, **kwargs):
            """
            Return a valid email completion.
            """

            self.kwargs = kwargs
            message = type(
                "Message",
                (),
                {
                    "content": (
                        '{"subject": "Tour Oak Ridge", '
                        '"body": "Hi Taylor, tour Oak Ridge. Reply STOP to opt out.", '
                        '"cta": {"type": "book_tour", "link": "https://oakridge.example/tour"}, '
                        '"message_reason": "test"}'
                    )
                },
            )
            choice = type("Choice", (), {"message": message, "finish_reason": "stop"})
            return type("Response", (), {"choices": [choice]})

    class _FakeOpenAI:
        """
        Minimal fake OpenAI client.
        """

        def __init__(self) -> None:
            self.completions = _FakeCompletions()
            self.chat = type("Chat", (), {"completions": self.completions})

    fake_client = _FakeOpenAI()
    monkeypatch.delenv("REALPAGE_COMPOSER_MAX_TOKENS", raising=False)

    with patch("openai.OpenAI", return_value=fake_client):
        payload = message_composer._call_openai_composer_once(
            channel="email",
            persona="prospect",
            lifecycle_stage="open",
            profile={"first_name": "Taylor", "amenity_interest": ["pool"]},
            property_name="Oak Ridge Apartments",
            primary_cta="book_tour",
            constraints={"allowed_link_domains": ["oakridge.example"]},
            consent_verification={"eligible": True},
        )

    assert payload["subject"] == "Tour Oak Ridge"
    assert fake_client.completions.kwargs["max_completion_tokens"] == 300


def test_openai_composer_rejects_truncated_completion(monkeypatch) -> None:
    """
    Verify finish_reason=length is treated as truncation and never accepted.
    """

    class _FakeCompletions:
        """
        Fake OpenAI resource that simulates a token-limit stop.
        """

        def create(self, **_kwargs):
            """
            Return syntactically valid JSON with a length finish reason.
            """

            message = type(
                "Message",
                (),
                {
                    "content": (
                        '{"subject": null, "body": "Hi Taylor.", '
                        '"cta": {"type": "schedule_tour"}, "message_reason": "cut"}'
                    )
                },
            )
            choice = type("Choice", (), {"message": message, "finish_reason": "length"})
            return type("Response", (), {"choices": [choice]})

    class _FakeOpenAI:
        """
        Minimal fake OpenAI client.
        """

        def __init__(self) -> None:
            self.chat = type("Chat", (), {"completions": _FakeCompletions()})

    with patch("openai.OpenAI", return_value=_FakeOpenAI()):
        with pytest.raises(ValueError, match="truncated"):
            message_composer._call_openai_composer_once(
                channel="sms",
                persona="prospect",
                lifecycle_stage="new",
                profile={"first_name": "Taylor"},
                property_name="Oak Ridge Apartments",
                primary_cta="book_tour",
                constraints={},
                consent_verification={"eligible": True},
            )


def test_composer_retries_openai_then_succeeds(monkeypatch) -> None:
    """
    Verify immediate retries execute before accepting a recovered LLM payload.
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


def test_composer_rejects_blank_required_fields(monkeypatch) -> None:
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


def test_composer_requires_email_subject(monkeypatch) -> None:
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


# ── ThresholdsRecord optional fields ─────────────────────────────────────────


def test_thresholds_record_accepts_empty_dict() -> None:
    """
    Verify ThresholdsRecord validates {} with all fields defaulting to None.
    """

    t = ThresholdsRecord.model_validate({})

    assert t.p95_latency_ms is None
    assert t.personalization_score_min is None
    assert t.safety_violations_max is None
    assert t.reply_classification_f1_min is None


def test_thresholds_record_accepts_full_eval_values() -> None:
    """
    Verify full threshold values still validate correctly after making fields optional.
    """

    t = ThresholdsRecord.model_validate(
        {"p95_latency_ms": 2000, "personalization_score_min": 0.8, "safety_violations_max": 0}
    )

    assert t.p95_latency_ms == 2000
    assert t.personalization_score_min == 0.8
    assert t.safety_violations_max == 0


def test_thresholds_record_rejects_boolean_for_numeric_fields() -> None:
    """
    Verify boolean values are rejected for integer threshold fields.
    """

    with pytest.raises(ValidationError):
        ThresholdsRecord.model_validate({"p95_latency_ms": True})


def test_run_request_schema_accepts_empty_thresholds_and_expected() -> None:
    """
    Verify RunRequest accepts {} for both eval-only fields without a validation error.
    """

    r = RunRequest.model_validate({**_MINIMAL_CASE, "thresholds": {}, "expected": {}})

    assert r.thresholds is not None
    assert r.thresholds.p95_latency_ms is None
    assert r.expected is not None
    assert r.expected.next_message is None


def test_run_request_schema_accepts_omitted_thresholds_and_expected() -> None:
    """
    Verify RunRequest accepts a payload where thresholds and expected are absent.
    """

    r = RunRequest.model_validate(_MINIMAL_CASE)

    assert r.thresholds is None
    assert r.expected is None


# ── Compliance suffix channel filtering ───────────────────────────────────────


def test_suffix_blocked_for_email_specific_text_on_sms() -> None:
    """
    Verify an email-specific compliance suffix is not applied to an SMS body.
    """

    assert _suffix_applies_to_channel(
        "To opt out of emails, click here or reply STOP to opt out.", "sms"
    ) is False


def test_suffix_blocked_for_email_specific_text_on_voice() -> None:
    """
    Verify an email-specific compliance suffix is not applied to a voice body.
    """

    assert _suffix_applies_to_channel(
        "To opt out of emails, click here or reply STOP to opt out.", "voice"
    ) is False


def test_suffix_blocked_for_unsubscribe_text_on_sms() -> None:
    """
    Verify a suffix containing 'unsubscribe' is treated as email-specific and skipped for SMS.
    """

    assert _suffix_applies_to_channel("Click here to unsubscribe.", "sms") is False


def test_suffix_allowed_for_generic_text_on_sms() -> None:
    """
    Verify a generic opt-out suffix is applied to SMS and voice.
    """

    assert _suffix_applies_to_channel("Reply STOP to opt out.", "sms") is True
    assert _suffix_applies_to_channel("Reply STOP to opt out.", "voice") is True


def test_suffix_always_allowed_for_email() -> None:
    """
    Verify any suffix is allowed on email regardless of content.
    """

    assert _suffix_applies_to_channel(
        "To opt out of emails, click here or reply STOP to opt out.", "email"
    ) is True


# ── Voice and SMS CTA link validation ────────────────────────────────────────


def test_composer_cta_link_rejected_for_sms() -> None:
    """
    Verify CTA link must be null for sms — schema validation enforces it.
    """

    payload = {
        "subject": None,
        "body": "Hi Taylor, book a tour. Reply STOP to opt out.",
        "cta": {"type": "schedule_tour", "link": "https://oakridge.example/tour"},
        "message_reason": "test",
    }

    with pytest.raises(ValidationError):
        ComposerLlmOutput.model_validate(payload, strict=True, context={"channel": "sms"})


def test_composer_cta_link_rejected_for_voice() -> None:
    """
    Verify CTA link must be null for voice — voice is phone-keypad only.
    """

    payload = {
        "subject": None,
        "body": "Hi Taylor, press 1 to book a tour. Press 2 to skip.",
        "cta": {"type": "schedule_tour", "link": "https://oakridge.example/tour"},
        "message_reason": "test",
    }

    with pytest.raises(ValidationError):
        ComposerLlmOutput.model_validate(payload, strict=True, context={"channel": "voice"})


def test_composer_cta_link_allowed_for_email() -> None:
    """
    Verify CTA link is accepted for email channel.
    """

    payload = {
        "subject": "Tour Oak Ridge",
        "body": "Hi Taylor, book a tour this week.",
        "cta": {"type": "schedule_tour", "link": "https://oakridge.example/tour"},
        "message_reason": "test",
    }

    result = ComposerLlmOutput.model_validate(payload, strict=True, context={"channel": "email"})

    assert result.cta.link == "https://oakridge.example/tour"


def test_composer_voice_subject_must_be_null() -> None:
    """
    Verify voice channel rejects a non-null subject (same rule as SMS).
    """

    payload = {
        "subject": "Tour Oak Ridge",
        "body": "Hi Taylor, press 1 to book.",
        "cta": {"type": "schedule_tour", "options": ["1. Yes", "2. No"]},
        "message_reason": "test",
    }

    with pytest.raises(ValidationError):
        ComposerLlmOutput.model_validate(payload, strict=True, context={"channel": "voice"})


def test_channel_selector_handles_empty_preferences() -> None:
    """
    Verify behavior when channel_preferences is [].
    """
    result = parse_tool_result(
        select_channel([], {"sms_opt_in": True, "email_opt_in": True})
    )
    assert result["result"]["send"] is False


@pytest.mark.parametrize("tz,expected_hour", [
    ("America/New_York", "09"),
    ("America/Los_Angeles", "09"),
    ("Europe/London", "09"),
    ("Asia/Tokyo", "09"),
    ("Australia/Sydney", "09"),
    ("UTC", "09"),
])
def test_send_time_correct_in_recipient_timezone(tz: str, expected_hour: str) -> None:
    """
    Verify next-day 9am in recipient timezone across major zones.
    """
    result = parse_tool_result(
        determine_send_time(tz, "2025-12-08T15:04:00Z", "new")
    )
    send_at = result["result"]["send_at"]
    # Extract hour from ISO8601 timestamp (format: YYYY-MM-DDTHH:MM:SS±HH:MM)
    hour = send_at.split("T")[1][:2]
    assert hour == expected_hour
