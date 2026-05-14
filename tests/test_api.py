"""
File: test_api.py
Purpose: Behavior tests for FastAPI outreach routes.
Author: Sreeram
"""

import json
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.compose_fixture_stub import compose_message_json_for_case
from backend.main import app


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
        side_effect=lambda *args, **kwargs: compose_message_json_for_case(record),
    ):
        response = TestClient(app).post("/run", json=record)

    assert response.status_code == 200
    payload = response.json()
    assert payload["output"]["send"] is True
    assert payload["output"]["next_message"]["channel"] == "sms"
    assert "STOP to opt out" in payload["output"]["next_message"]["body"]
    assert payload["latency_ms"] >= 0


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


def test_run_route_sanitizes_validation_errors() -> None:
    """
    Verify validation errors do not echo submitted PII-like values.
    """

    record = load_sample_record(0)
    record["input"]["profile"]["familial_status"] = "has children"
    record["input"]["timezone"] = "Not/AZone"

    response = TestClient(app).post("/run", json=record)

    assert response.status_code == 422
    assert "has children" not in response.text
    assert "Not/AZone" not in response.text
