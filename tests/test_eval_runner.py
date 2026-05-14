"""
File: test_eval_runner.py
Purpose: Behavior tests for the JSONL eval runner.
Author: Sreeram
"""

from pathlib import Path

import pytest

from backend.eval_runner import load_cases, run_all, run_case, score_output


SAMPLE_PATH = Path(__file__).parents[1] / "backend" / "data" / "sample.jsonl"


@pytest.fixture(autouse=True)
def _eval_tests_no_openai_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Eval runner loads backend/.env at import time; these tests expect deterministic
    offline scoring without live composer or judge calls.
    """

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


def test_load_cases_reads_jsonl_records() -> None:
    """
    Verify the eval runner loads bundled JSONL cases in order.
    """

    cases = load_cases(SAMPLE_PATH)

    assert [case["task_id"] for case in cases] == [
        "prospect_welcome_day0",
        "prospect_long_horizon_day3",
    ]


def test_run_case_scores_generated_output_against_expected() -> None:
    """
    Verify one case returns generated output and a passing score summary.
    """

    case = load_cases(SAMPLE_PATH)[0]
    result = run_case(case)

    assert result["task_id"] == "prospect_welcome_day0"
    assert result["passed"] is True
    assert result["scores"]["channel_match"] is True
    assert result["scores"]["next_action_match"] is True


def test_run_all_reports_aggregate_pass_for_bundled_samples() -> None:
    """
    Verify all bundled sample cases pass the eval runner checks.
    """

    result = run_all(SAMPLE_PATH)

    assert result["total"] == 2
    assert result["passed"] == 2
    assert result["failed"] == 0


def test_load_cases_rejects_paths_outside_eval_data(tmp_path: Path) -> None:
    """
    Verify eval loading is restricted to bundled JSONL data files.
    """

    outside_jsonl = tmp_path / "outside.jsonl"
    outside_jsonl.write_text('{"task_id": "outside"}\n', encoding="utf-8")

    with pytest.raises(ValueError):
        load_cases(outside_jsonl)


def test_score_output_reports_mismatches() -> None:
    """
    Verify scoring reports failed dimensions instead of false positives.
    """

    case = load_cases(SAMPLE_PATH)[0]
    result = run_case(case)
    expected = dict(result["expected"])
    expected["next_message"] = dict(expected["next_message"])
    expected["next_message"]["channel"] = "email"

    scores = score_output(
        result["generated"],
        expected,
        assertions=case["assertions"],
        thresholds=case["thresholds"],
    )

    assert scores["channel_match"] is False
    assert all(scores.values()) is False


def test_score_output_reports_body_cta_and_compliance_failures() -> None:
    """
    Verify scoring catches body, CTA, and constraint violations.
    """

    case = load_cases(SAMPLE_PATH)[0]
    result = run_case(case)
    generated = dict(result["generated"])
    generated["next_message"] = dict(generated["next_message"])
    generated["next_message"]["body"] = "Call 555-123-4567"
    generated["next_message"]["cta"] = {"type": "wrong_cta"}

    scores = score_output(
        generated,
        result["expected"],
        assertions=case["assertions"],
        thresholds=case["thresholds"],
    )

    assert scores["body_match"] is False
    assert scores["cta_match"] is False
    assert scores["constraints_pass"] is False
