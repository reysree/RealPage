"""
File: test_latency_benchmark.py
Purpose: Behavior tests for stage-level latency benchmark helpers.
Author: Sreeram
"""

from backend.evals.latency_benchmark import format_markdown, run_stage_benchmark


_CASE = {
    "task_id": "latency_benchmark_case",
    "persona": "prospect",
    "lifecycle_stage": "new",
    "consent": {"email_opt_in": True, "sms_opt_in": True, "voice_opt_in": False},
    "channel_preferences": ["sms", "email"],
    "input": {
        "property_name": "Oak Ridge Apartments",
        "move_date_target": "2026-01-10",
        "last_interaction": "2025-12-08T15:04:00Z",
        "timezone": "America/Chicago",
        "language": "en",
        "profile": {"first_name": "Taylor", "city_interest": "Richardson, TX"},
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
    "thresholds": {"p95_latency_ms": 2000},
    "expected": {},
}


def test_stage_benchmark_reports_rows_without_openai_when_fast_path_enabled(monkeypatch) -> None:
    """
    Verify stage benchmarking can measure /run without changing the API response contract.
    """

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    report = run_stage_benchmark(
        _CASE,
        samples=2,
        env_overrides={"REALPAGE_COMPOSER_FAST_PATH": "1"},
    )

    assert report["task_id"] == "latency_benchmark_case"
    assert report["samples"] == 2
    assert len(report["rows"]) == 2
    for row in report["rows"]:
        assert row["status"] == 200
        assert row["send"] is True
        assert row["openai_attempts"] == 0
        assert row["compose_total_ms"] >= 0
        assert row["post_ms"] >= row["compose_total_ms"]


def test_stage_benchmark_formats_markdown_table(monkeypatch) -> None:
    """
    Verify benchmark reports can be rendered for client-readable analysis.
    """

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    report = run_stage_benchmark(
        _CASE,
        samples=1,
        env_overrides={"REALPAGE_COMPOSER_FAST_PATH": "1"},
    )
    rendered = format_markdown(report, label="fast-path latency benchmark")

    assert "## fast-path latency benchmark" in rendered
    assert "| Call | POST /run ms |" in rendered
    assert "| P95 POST /run ms |" in rendered
