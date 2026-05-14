"""
File: test_api.py
Purpose: Behavior tests for FastAPI outreach routes.
Author: Sreeram
"""

import json
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from tests.test_support.compose_stub import compose_message_json_for_case
from backend.main import app


def _patched_compose_side_effect(record: dict):
    """
    Match production compose_message(channel=...) so input-only stubs track selected channel.
    """

    def _inner(*_: object, **kwargs: object):
        return compose_message_json_for_case(
            record,
            channel=str(kwargs.get("channel") or "sms"),
        )

    return _inner


def load_sample_record(index: int) -> dict:
    """
    Load one bundled JSONL sample record for API tests.

    Args:
        index: Zero-based sample line index.
    Returns:
        Parsed JSON record.
    """

    sample_path = Path(__file__).parents[1] / "backend" / "data" / "sample.jsonl"
    return json.loads(sample_path.read_text(encoding="utf-8").splitlines()[index])


def test_health_route_returns_status_ok() -> None:
    """
    Verify the health route returns the public health response model.
    """

    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_run_route_returns_agent_output_for_sample_record() -> None:
    """
    Verify POST /run validates a case and returns generated agent output.
    """

    record = load_sample_record(0)
    with patch(
        "backend.agent.compose_message",
        side_effect=_patched_compose_side_effect(record),
    ):
        response = TestClient(app).post("/run", json=record)

    assert response.status_code == 200
    payload = response.json()
    assert payload["output"]["send"] is True
    assert payload["output"]["next_message"]["channel"] == "sms"
    assert "STOP to opt out" in payload["output"]["next_message"]["body"]
    assert payload["latency_ms"] >= 0


def test_run_route_returns_no_send_for_all_opted_out_sample() -> None:
    """
    Verify a canonical no-send fixture crosses the API boundary without composing.
    """

    record = load_sample_record(2)

    response = TestClient(app).post("/run", json=record)

    assert response.status_code == 200
    payload = response.json()["output"]
    assert payload["send"] is False
    assert payload["next_message"] is None
    assert payload["next_action"] == {
        "type": "human_in_the_loop",
        "name": "pipeline_blocked",
        "value": None,
    }


def test_run_route_returns_sanitized_500_when_agent_raises() -> None:
    """
    Verify unexpected agent failures return a generic response without secrets.
    """

    record = load_sample_record(0)

    with patch("backend.main.run_agent", side_effect=RuntimeError("secret-token=abc123")):
        response = TestClient(app).post("/run", json=record)

    assert response.status_code == 500
    assert response.json() == {"error": "Run failed", "message": "Run failed."}
    assert "secret-token" not in response.text


def test_run_route_rejects_non_boolean_consent_flags() -> None:
    """
    Verify POST /run rejects numeric consent flags (JSON must use true/false).
    """

    record = load_sample_record(0)
    record["consent"]["sms_opt_in"] = 1

    response = TestClient(app).post("/run", json=record)

    assert response.status_code == 422


def test_run_route_rejects_string_boolean_in_constraints() -> None:
    """
    Verify assertion constraint flags must be JSON booleans or null, not strings.
    """

    record = load_sample_record(0)
    record["assertions"]["constraints"]["no_pii_leak"] = "true"

    response = TestClient(app).post("/run", json=record)

    assert response.status_code == 422


def test_run_route_rejects_unknown_top_level_keys() -> None:
    """
    Verify eval/API case objects cannot include undeclared top-level properties.
    """

    record = load_sample_record(0)
    record["unexpected_field"] = 1

    response = TestClient(app).post("/run", json=record)

    assert response.status_code == 422


def test_run_route_rejects_unknown_assertions_keys() -> None:
    """
    Verify assertions objects cannot include fields outside the schema contract.
    """

    record = load_sample_record(0)
    record["assertions"]["shadow_audience"] = "test-only"

    response = TestClient(app).post("/run", json=record)

    assert response.status_code == 422


def test_run_route_rejects_unknown_expected_keys() -> None:
    """
    Verify expected-output fixtures cannot carry undeclared keys.
    """

    record = load_sample_record(0)
    record["expected"]["confidence_score"] = 0.99

    response = TestClient(app).post("/run", json=record)

    assert response.status_code == 422


def test_run_route_rejects_profanity_in_profile_first_name() -> None:
    """
    Verify profanity in input text fails validation before the agent runs.
    """

    record = load_sample_record(0)
    record["input"]["profile"]["first_name"] = "fuck"

    response = TestClient(app).post("/run", json=record)

    assert response.status_code == 422
    assert "fuck" not in response.text


def test_run_route_rejects_violent_extremism_phrase_in_property_name() -> None:
    """
    Verify violent-extremism phrases in marketing copy fail validation.
    """

    record = load_sample_record(0)
    record["input"]["property_name"] = "Sieg Heil Memorial Lofts"

    response = TestClient(app).post("/run", json=record)

    assert response.status_code == 422
    assert "Heil" not in response.text


def test_run_route_rejects_non_public_listing_url() -> None:
    """
    Optional listing_url must be a safe public http(s) target when present.
    """

    record = load_sample_record(0)
    record["input"]["listing_url"] = "http://127.0.0.1/internal"

    response = TestClient(app).post("/run", json=record)

    assert response.status_code == 422


def test_run_route_accepts_optional_https_listing_url() -> None:
    """
    Verify a normal optional listing URL validates and the pipeline can succeed.
    """

    record = load_sample_record(0)
    record["input"]["listing_url"] = "https://oakridge.example/tours"

    with patch(
        "backend.agent.compose_message",
        side_effect=_patched_compose_side_effect(record),
    ):
        response = TestClient(app).post("/run", json=record)

    assert response.status_code == 200
    assert response.json()["output"]["send"] is True


def test_run_route_blocks_embedded_private_url_in_constraint_notes() -> None:
    """
    Embedded malicious/private URLs in screened fields must stop the agent (no send).
    """

    record = load_sample_record(0)
    record["assertions"]["constraints"]["brand_style_notes"] = (
        "See specials at https://10.0.0.5/admin — urgent."
    )

    with patch(
        "backend.agent.compose_message",
        side_effect=_patched_compose_side_effect(record),
    ):
        response = TestClient(app).post("/run", json=record)

    assert response.status_code == 200
    payload = response.json()["output"]
    assert payload["send"] is False
    assert payload["next_action"] == {
        "type": "human_in_the_loop",
        "name": "pipeline_blocked",
        "value": None,
    }


def test_run_route_rejects_localhost_in_allowed_link_domains() -> None:
    """
    Hostname allowlists must not reference loopback or non-public hosts.
    """

    record = load_sample_record(0)
    record["assertions"]["constraints"]["allowed_link_domains"] = ["localhost"]

    response = TestClient(app).post("/run", json=record)

    assert response.status_code == 422


def test_run_route_rejects_missing_property_name_with_plain_response() -> None:
    """
    Verify missing required input fields return only generic error plus human message.
    """

    record = load_sample_record(0)
    del record["input"]["property_name"]

    response = TestClient(app).post("/run", json=record)

    assert response.status_code == 422
    assert response.json() == {
        "error": "Run failed",
        "message": "Required field missing: input.property_name.",
    }


def test_run_route_sanitizes_validation_errors() -> None:
    """
    Verify validation errors do not echo submitted PII-like values.
    """

    record = load_sample_record(0)
    record["input"]["profile"]["familial_status"] = "has children"
    record["input"]["timezone"] = "Not/AZone"

    response = TestClient(app).post("/run", json=record)

    assert response.status_code == 422
    payload = response.json()
    assert payload["error"] == "Run failed"
    assert "message" in payload
    assert isinstance(payload["message"], str)
    assert "has children" not in response.text
    assert "Not/AZone" not in response.text


# ── Optional eval fields: thresholds and expected ────────────────────────────


def test_run_route_accepts_empty_thresholds() -> None:
    """
    Verify POST /run returns 200 when thresholds is {}, not a 422 for missing sub-fields.
    """

    record = load_sample_record(0)
    record["thresholds"] = {}

    with patch(
        "backend.agent.compose_message",
        side_effect=_patched_compose_side_effect(record),
    ):
        response = TestClient(app).post("/run", json=record)

    assert response.status_code == 200
    assert response.json()["output"]["send"] is True


def test_run_route_accepts_empty_expected() -> None:
    """
    Verify POST /run returns 200 when expected is {} — compose stub derives text from input only.
    """

    record = load_sample_record(0)
    record["expected"] = {}

    with patch(
        "backend.agent.compose_message",
        side_effect=_patched_compose_side_effect(record),
    ):
        response = TestClient(app).post("/run", json=record)

    assert response.status_code == 200
    assert response.json()["output"]["send"] is True


def test_run_route_accepts_both_eval_fields_empty() -> None:
    """
    Verify POST /run returns 200 when both thresholds and expected are {}.
    """

    record = load_sample_record(0)
    record["thresholds"] = {}
    record["expected"] = {}

    with patch(
        "backend.agent.compose_message",
        side_effect=_patched_compose_side_effect(record),
    ):
        response = TestClient(app).post("/run", json=record)

    assert response.status_code == 200
    assert response.json()["output"]["send"] is True


def test_run_route_accepts_omitted_thresholds_and_expected() -> None:
    """
    Verify POST /run returns 200 when thresholds and expected keys are absent entirely.
    """

    record = load_sample_record(0)
    record.pop("thresholds", None)
    record.pop("expected", None)

    with patch(
        "backend.agent.compose_message",
        side_effect=_patched_compose_side_effect(record),
    ):
        response = TestClient(app).post("/run", json=record)

    assert response.status_code == 200
    assert response.json()["output"]["send"] is True
