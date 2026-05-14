"""
File: test_eval_runner.py
Purpose: Behavior tests for the JSONL eval runner.
Author: Sreeram
"""

from pathlib import Path
from typing import Any

import pytest

from backend.eval_runner import (
    _percentile_linear,
    load_cases,
    run_all,
    run_case,
    score_output,
)


SAMPLE_PATH = Path(__file__).parents[1] / "backend" / "data" / "sample.jsonl"


@pytest.fixture(autouse=True)
def _eval_runner_ci_safety(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Fast, deterministic eval-runner tests: no live OpenAI, stubbed composer, fixed judge.

    Production ``python -m backend.eval_runner`` does not use this fixture; it uses real
    APIs when configured. The judge stub here is **test-only** so personalization_pass is
    stable without billing OpenAI during pytest.
    """

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("REALPAGE_EVAL_LATENCY_RUNS", "1")
    monkeypatch.setenv("REALPAGE_EVAL_STUB_COMPOSE", "true")

    def _deterministic_personalization_score(
        _body: str,
        _profile: dict[str, Any],
        _property_name: str,
    ) -> float:
        return 0.92

    monkeypatch.setattr(
        "backend.eval_runner._score_personalization",
        _deterministic_personalization_score,
    )


EXPECTED_TASK_IDS = [
    "prospect_welcome_day0",
    "prospect_long_horizon_day3",
]
EXPECTED_TOTAL_CASES = len(EXPECTED_TASK_IDS)


def test_percentile_linear_p95_interpolates() -> None:
    """
    Verify P95 linear interpolation between bracketing samples.
    """

    assert _percentile_linear([10, 20, 30, 40, 50], 95.0) == 48.0


def test_run_case_honors_latency_sample_count() -> None:
    """
    Verify repeated timed cycles populate latency sample lists.
    """

    case = load_cases(SAMPLE_PATH)[0]
    result = run_case(case, latency_sample_count=3)

    assert result["latency"]["samples"] == 3
    assert len(result["latency"]["agent_elapsed_ms_all"]) == 3
    assert result["latency"]["sampling_mode"] == "repeated_api_then_single_score"
    assert "eval_integrity" in result


def test_score_output_personalization_fails_when_judge_returns_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    A set personalization_score_min must not pass by omission when the judge cannot run.
    """

    monkeypatch.setattr("backend.eval_runner._score_personalization", lambda *a, **k: None)
    case = load_cases(SAMPLE_PATH)[0]
    result = run_case(case)
    assert result["scores"].get("personalization_pass") is False


def test_load_cases_reads_jsonl_records() -> None:
    """
    Verify the eval runner loads all bundled JSONL cases in file order.
    """

    cases = load_cases(SAMPLE_PATH)
    task_ids = [case["task_id"] for case in cases]

    assert len(cases) == EXPECTED_TOTAL_CASES
    assert task_ids == EXPECTED_TASK_IDS


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

    assert result["total"] == EXPECTED_TOTAL_CASES
    assert result["passed"] == EXPECTED_TOTAL_CASES
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
