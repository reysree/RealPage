"""
File: test_eval_runner.py
Purpose: Behavior tests for the JSONL eval runner.
Author: Sreeram
"""

from pathlib import Path
from typing import Any

import pytest

import backend.evals.runner as eval_runner
from backend.evals.runner import (
    _percentile_linear,
    _score_output_bundle,
    load_cases,
    run_all,
    run_case,
    score_output,
)


SAMPLE_PATH = Path(__file__).parents[1] / "backend" / "data" / "sample.jsonl"


@pytest.fixture(autouse=True)
def _eval_runner_ci_safety(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Fast eval-runner behavior tests: patched compose yields input-shaped payloads only.

    Harness itself always calls production ``compose_message`` (OpenAI) when invoked via CLI.
    Judge calls are mocked to a fixed score so personalization thresholds pass without billing.
    """

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("REALPAGE_EVAL_LATENCY_RUNS", "1")

    def _compose_shim(*_: object, **kwargs: Any):
        """
        Mirrors ``compose_message`` kwargs into ``tests.test_support.compose_stub`` — no golden JSON ``expected``.
        """

        from tests.test_support.compose_stub import compose_message_envelope_from_compose_kwargs

        raw_constraints = kwargs.get("constraints")
        cons = raw_constraints if isinstance(raw_constraints, dict) else {}

        return compose_message_envelope_from_compose_kwargs(
            channel=str(kwargs.get("channel") or "sms"),
            profile=dict(kwargs.get("profile") or {}),
            property_name=str(kwargs.get("property_name") or ""),
            constraints=cons,
        )

    monkeypatch.setattr("backend.agent.compose_message", _compose_shim)

    def _deterministic_personalization_score(
        _body: str,
        _profile: dict[str, Any],
        _property_name: str,
    ) -> float:
        return 0.92

    monkeypatch.setattr(
        "backend.evals.runner._score_personalization",
        _deterministic_personalization_score,
    )


EXPECTED_TASK_IDS = [
    "prospect_welcome_day0",
    "prospect_long_horizon_day3",
    "prospect_all_opted_out",
    "prospect_voice_only",
    "prospect_open_engagement",
    "prospect_new_email_fallback",
    "prospect_open_sms_fallback",
    "prospect_open_all_opted_out",
    "prospect_open_voice_only",
    "prospect_prompt_injection_blocked",
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

    monkeypatch.setattr("backend.evals.runner._score_personalization", lambda *a, **k: None)
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


def test_run_case_scores_generated_output_without_golden_expected() -> None:
    """
    Verify one case returns generated output and passes using constraints and thresholds only.
    """

    case = load_cases(SAMPLE_PATH)[0]
    result = run_case(case)

    assert result["task_id"] == "prospect_welcome_day0"
    assert result["passed"] is True
    assert result["scores"]["constraints_pass"] is True
    assert result["scores"].get("personalization_pass") is True


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


def test_load_cases_rejects_malformed_jsonl_line(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Verify malformed JSONL fixtures fail before eval execution starts.
    """

    malformed_jsonl = tmp_path / "malformed.jsonl"
    malformed_jsonl.write_text('{"task_id": "ok"}\n{bad json}\n', encoding="utf-8")
    monkeypatch.setattr(eval_runner, "EVAL_DATA_DIR", tmp_path)

    with pytest.raises(ValueError):
        load_cases(malformed_jsonl)


def test_score_output_does_not_use_expected_block_for_pass_fail() -> None:
    """
    Scoring must not compare generated output to the JSONL ``expected`` field.
    """

    case = load_cases(SAMPLE_PATH)[0]
    result = run_case(case)
    scores = score_output(
        result["generated"],
        assertions=case["assertions"],
        thresholds=case["thresholds"],
    )
    assert scores["constraints_pass"] is True


def test_run_case_includes_safety_violations_rule_eval() -> None:
    """
    Each eval case returns a structured SafetyViolationsRuleEval alongside boolean scores.
    """

    case = load_cases(SAMPLE_PATH)[0]
    result = run_case(case)
    se = result["safety_violations_rule_eval"]
    assert se["sending"] is True
    assert se["violation_tags"] == []
    assert se["violation_count"] == 0
    assert se["max_allowed"] == 0
    assert se["within_violation_budget"] is True
    assert result["personalization_judge_score"] == pytest.approx(0.92)

    opted = load_cases(SAMPLE_PATH)[2]
    r2 = run_case(opted)
    se2 = r2["safety_violations_rule_eval"]
    assert se2["sending"] is False
    assert se2["violation_count"] == 0
    assert se2["max_allowed"] is None
    assert se2["within_violation_budget"] is None
    assert r2["personalization_judge_score"] is None


def test_score_output_reports_constraint_violations_on_generated_body() -> None:
    """
    Verify constraint checks run on the generated message body (e.g. PII).
    """

    case = load_cases(SAMPLE_PATH)[0]
    result = run_case(case)
    generated = dict(result["generated"])
    generated["next_message"] = dict(generated["next_message"])
    generated["next_message"]["body"] = "Call 555-123-4567"
    generated["next_message"]["cta"] = {"type": "wrong_cta"}

    scores = score_output(
        generated,
        assertions=case["assertions"],
        thresholds=case["thresholds"],
    )
    _bundle_scores, safety, _ = _score_output_bundle(
        generated,
        assertions=case["assertions"],
        thresholds=case["thresholds"],
    )

    assert scores["constraints_pass"] is False
    assert "pii_leak" in safety.violation_tags


def test_run_case_surfaces_latency_failure_as_non_gating_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Verify latency threshold failures are reported but do not fail correctness.
    """

    monkeypatch.setattr(eval_runner, "_percentile_linear", lambda *_args, **_kwargs: 25.0)
    case = load_cases(SAMPLE_PATH)[2]
    case["thresholds"] = {"p95_latency_ms": 1}

    result = run_case(case)

    assert result["scores"]["latency_pass"] is False
    assert result["passed"] is True
