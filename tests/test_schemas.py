"""
File: test_schemas.py
Purpose: Behavior tests for validating outreach JSONL records at the schema boundary.
Author: Sreeram
"""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.constants import BRAND_STYLE_GUIDE, FAIR_HOUSING_RULES
from backend.schemas import AgentOutput, MessageOutput, RunRequest, RunResponse


def test_run_request_validates_sample_jsonl_record() -> None:
    """
    Verify that a real JSONL case can cross the API boundary as typed models.
    """

    sample_path = Path(__file__).parents[1] / "backend" / "data" / "sample.jsonl"
    record = json.loads(sample_path.read_text(encoding="utf-8").splitlines()[0])

    request = RunRequest.model_validate(record)

    assert request.task_id == "prospect_welcome_day0"
    assert request.consent.sms_opt_in is True
    assert request.channel_preferences == ["sms", "email"]
    assert request.input.profile.first_name == "Taylor"
    assert request.expected.next_message.channel == "sms"

    output = AgentOutput(
        send=True,
        next_message=MessageOutput(
            channel="sms",
            send_at="2025-12-09T09:00:00-06:00",
            subject=None,
            body="Reply STOP to opt out.",
            cta={"type": "schedule_tour"},
        ),
        next_action={"type": "start_cadence", "name": "prospect_welcome_short_horizon"},
    )

    assert output.next_message is not None
    assert output.next_message.cta.type == "schedule_tour"


def test_all_sample_records_and_policy_constants_are_loadable() -> None:
    """
    Verify that all bundled sample cases and shared policy constants are usable.
    """

    sample_path = Path(__file__).parents[1] / "backend" / "data" / "sample.jsonl"
    records = [
        RunRequest.model_validate(json.loads(line))
        for line in sample_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    assert [record.task_id for record in records] == [
        "prospect_welcome_day0",
        "prospect_long_horizon_day3",
    ]
    assert "Fair Housing Act" in FAIR_HOUSING_RULES
    assert "Always end with opt-out instruction" in BRAND_STYLE_GUIDE


def test_run_request_rejects_unexpected_profile_fields_and_channels() -> None:
    """
    Verify that unsafe or unsupported boundary fields are rejected early.
    """

    sample_path = Path(__file__).parents[1] / "backend" / "data" / "sample.jsonl"
    record = json.loads(sample_path.read_text(encoding="utf-8").splitlines()[0])

    record["input"]["profile"]["familial_status"] = "has children"
    with pytest.raises(ValidationError):
        RunRequest.model_validate(record)

    record = json.loads(sample_path.read_text(encoding="utf-8").splitlines()[0])
    record["channel_preferences"] = ["fax"]
    with pytest.raises(ValidationError):
        RunRequest.model_validate(record)


def test_run_request_rejects_unbounded_free_form_payloads() -> None:
    """
    Verify that oversized text and arbitrary CTA keys cannot cross boundaries.
    """

    sample_path = Path(__file__).parents[1] / "backend" / "data" / "sample.jsonl"
    record = json.loads(sample_path.read_text(encoding="utf-8").splitlines()[1])

    record["input"]["profile"]["amenity_interest"] = ["x" * 121]
    with pytest.raises(ValidationError):
        RunRequest.model_validate(record)

    record = json.loads(sample_path.read_text(encoding="utf-8").splitlines()[1])
    record["expected"]["next_message"]["cta"]["tracking_pixel"] = "https://example.invalid/pixel"
    with pytest.raises(ValidationError):
        RunRequest.model_validate(record)

    with pytest.raises(ValidationError):
        RunResponse(
            output=AgentOutput(send=False, next_message=None, next_action=None),
            tools_used=["x" * 121],
            latency_ms=1,
        )
