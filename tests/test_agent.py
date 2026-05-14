"""
File: test_agent.py
Purpose: Behavior tests for outreach agent orchestration.
Author: Sreeram
"""

import json
from pathlib import Path
from unittest.mock import patch

from backend.agent import run_agent
from backend.evals.fixture_stub import compose_message_json_for_case
from backend.schemas import RunRequest


def load_sample_record(index: int) -> dict:
    """
    Load one bundled JSONL sample record for public agent tests.

    Args:
        index: Zero-based sample line index.
    Returns:
        Parsed JSON record.
    """

    sample_path = Path(__file__).parents[1] / "backend" / "data" / "sample.jsonl"
    return json.loads(sample_path.read_text(encoding="utf-8").splitlines()[index])


def _run_agent_with_case_jsonl_fixture(record: dict) -> dict:
    """
    Run the agent while substituting bundled JSONL expected message payloads.

    Args:
        record: Parsed JSON case including expected output for offline stubs.
    Returns:
        Agent output dictionary from run_agent().
    """

    with patch(
        "backend.agent.compose_message",
        side_effect=lambda *args, **kwargs: compose_message_json_for_case(record),
    ):
        return run_agent(record)


def test_run_agent_returns_sms_message_for_eligible_sample() -> None:
    """
    Verify a consented SMS sample returns a sendable message and next action.
    """

    record = load_sample_record(0)
    result = _run_agent_with_case_jsonl_fixture(record)

    assert result["send"] is True
    assert result["next_message"]["channel"] == "sms"
    assert result["next_message"]["send_at"] == "2025-12-09T09:00:00-06:00"
    assert "STOP to opt out" in result["next_message"]["body"]
    assert result["body"] == result["next_message"]["body"]
    assert result["next_action"] == {
        "type": "start_cadence",
        "name": "prospect_welcome_short_horizon",
        "value": None,
    }


def test_run_agent_returns_no_send_when_no_channel_is_eligible() -> None:
    """
    Verify the agent stops before composing when all preferred channels are blocked.
    """

    record = load_sample_record(0)
    record["consent"] = {
        "email_opt_in": False,
        "sms_opt_in": False,
        "voice_opt_in": False,
    }

    result = run_agent(record)

    assert result == {
        "send": False,
        "next_message": None,
        "next_action": {
            "type": "human_in_the_loop",
            "name": "pipeline_blocked",
            "value": None,
        },
        "body": "",
    }


def test_run_agent_returns_email_for_long_horizon_sample() -> None:
    """
    Verify a long-horizon prospect follows the document contract.
    """

    record = load_sample_record(1)
    expected = RunRequest.model_validate(record).expected
    result = _run_agent_with_case_jsonl_fixture(record)

    assert result["send"] is True
    assert result["next_message"]["channel"] == expected.next_message.channel
    assert result["next_message"]["send_at"] == expected.next_message.send_at
    assert "STOP to opt out" in result["next_message"]["body"]
    assert result["next_action"] == expected.next_action.model_dump()


def test_run_agent_returns_no_send_when_compliance_fails() -> None:
    """
    Verify a composed body with a disallowed link domain is blocked before send=True.

    URL domain enforcement only fires when allowed_link_domains is set. This test
    sets an explicit allowlist that excludes the URL the fixture stub injects.
    """

    record = load_sample_record(0)
    record["input"]["property_name"] = "Unsafe https://evil.example"
    record["assertions"]["constraints"]["allowed_link_domains"] = ["oakridge.example"]

    result = _run_agent_with_case_jsonl_fixture(record)

    assert result == {
        "send": False,
        "next_message": None,
        "next_action": {
            "type": "human_in_the_loop",
            "name": "pipeline_blocked",
            "value": None,
        },
        "body": "",
    }
