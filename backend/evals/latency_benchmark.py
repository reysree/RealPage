"""
File: latency_benchmark.py
Purpose: Stage-level latency benchmark helper for outreach eval cases.
Author: Sreeram
"""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path
from time import perf_counter
from typing import Any, Iterator

from fastapi.testclient import TestClient

import backend.agent as agent_module
import backend.tools.message_composer as composer_module
from backend.evals.runner import _percentile_linear
from backend.main import create_app


_ENV_KEYS = (
    "REALPAGE_COMPOSER_FAST_PATH",
    "REALPAGE_COMPOSER_MODEL",
    "REALPAGE_COMPOSER_TEMPERATURE",
    "REALPAGE_COMPOSER_MAX_TOKENS",
)


def _elapsed_ms(started_at: float) -> int:
    """
    Convert perf_counter elapsed time to whole milliseconds.

    Args:
        started_at: Start time from perf_counter().
    Returns:
        Elapsed milliseconds.
    """

    return int((perf_counter() - started_at) * 1000)


def _load_cases(path: Path) -> list[dict[str, Any]]:
    """
    Load JSON array, JSON object, or JSONL cases for benchmarking.

    Args:
        path: Input file path.
    Returns:
        Parsed case dictionaries.
    """

    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        return []
    if path.suffix == ".jsonl":
        return [json.loads(line) for line in raw.splitlines() if line.strip()]
    parsed = json.loads(raw)
    return parsed if isinstance(parsed, list) else [parsed]


@contextmanager
def _temporary_env(overrides: dict[str, str | None]) -> Iterator[None]:
    """
    Temporarily override benchmark-related environment variables.

    Args:
        overrides: Environment variable values; None clears the variable.
    """

    original = {key: os.environ.get(key) for key in _ENV_KEYS}
    try:
        for key, value in overrides.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        yield
    finally:
        for key, value in original.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


@contextmanager
def _stage_probe(current: dict[str, Any]) -> Iterator[None]:
    """
    Monkeypatch agent stages to collect timings without changing API output.

    Args:
        current: Mutable row populated during one /run call.
    """

    originals: dict[str, Callable[..., Any]] = {
        "check_input_security": agent_module.check_input_security,
        "select_channel": agent_module.select_channel,
        "check_consent": agent_module.check_consent,
        "determine_send_time": agent_module.determine_send_time,
        "compose_message": agent_module.compose_message,
        "check_compliance": agent_module.check_compliance,
        "_call_openai_composer_once": composer_module._call_openai_composer_once,
    }

    def timed_stage(name: str, fn: Callable[..., Any]) -> Callable[..., Any]:
        """
        Wrap one stage and accumulate elapsed time in current.
        """

        def wrapper(*args: Any, **kwargs: Any) -> Any:
            started_at = perf_counter()
            try:
                return fn(*args, **kwargs)
            finally:
                current[name] = int(current.get(name, 0)) + _elapsed_ms(started_at)

        return wrapper

    def timed_openai(*args: Any, **kwargs: Any) -> Any:
        """
        Wrap the outbound OpenAI composer call.
        """

        current["openai_attempts"] = int(current.get("openai_attempts", 0)) + 1
        started_at = perf_counter()
        try:
            return originals["_call_openai_composer_once"](*args, **kwargs)
        finally:
            current["openai_ms"] = int(current.get("openai_ms", 0)) + _elapsed_ms(started_at)

    try:
        agent_module.check_input_security = timed_stage(
            "input_security_ms",
            originals["check_input_security"],
        )
        agent_module.select_channel = timed_stage(
            "channel_selector_ms",
            originals["select_channel"],
        )
        agent_module.check_consent = timed_stage("consent_ms", originals["check_consent"])
        agent_module.determine_send_time = timed_stage("timing_ms", originals["determine_send_time"])
        agent_module.compose_message = timed_stage("compose_total_ms", originals["compose_message"])
        agent_module.check_compliance = timed_stage("compliance_ms", originals["check_compliance"])
        composer_module._call_openai_composer_once = timed_openai
        yield
    finally:
        agent_module.check_input_security = originals["check_input_security"]
        agent_module.select_channel = originals["select_channel"]
        agent_module.check_consent = originals["check_consent"]
        agent_module.determine_send_time = originals["determine_send_time"]
        agent_module.compose_message = originals["compose_message"]
        agent_module.check_compliance = originals["check_compliance"]
        composer_module._call_openai_composer_once = originals["_call_openai_composer_once"]


def run_stage_benchmark(
    case: dict[str, Any],
    *,
    samples: int,
    env_overrides: dict[str, str | None] | None = None,
) -> dict[str, Any]:
    """
    Run a case repeatedly through /run while collecting stage timings.

    Args:
        case: Outreach case shaped like RunRequest.
        samples: Number of sequential /run calls.
        env_overrides: Composer environment overrides for this benchmark.
    Returns:
        Benchmark report with rows and aggregate latency metrics.
    """

    rows: list[dict[str, Any]] = []
    current: dict[str, Any] = {}
    with _temporary_env(env_overrides or {}), _stage_probe(current):
        client = TestClient(create_app())
        for index in range(1, max(1, samples) + 1):
            current.clear()
            started_at = perf_counter()
            response = client.post("/run", json=case)
            post_ms = _elapsed_ms(started_at)
            payload = response.json()
            output = payload.get("output", {}) if isinstance(payload, dict) else {}
            local_non_compose = sum(
                int(current.get(key, 0))
                for key in (
                    "input_security_ms",
                    "channel_selector_ms",
                    "consent_ms",
                    "timing_ms",
                    "compliance_ms",
                )
            )
            rows.append(
                {
                    "call": index,
                    "status": response.status_code,
                    "send": output.get("send"),
                    "post_ms": post_ms,
                    "api_latency_ms": payload.get("latency_ms") if isinstance(payload, dict) else None,
                    "openai_ms": int(current.get("openai_ms", 0)),
                    "compose_total_ms": int(current.get("compose_total_ms", 0)),
                    "openai_attempts": int(current.get("openai_attempts", 0)),
                    "local_non_compose_ms": local_non_compose,
                }
            )

    samples_ms = [int(row["post_ms"]) for row in rows]
    return {
        "task_id": case.get("task_id"),
        "threshold_ms": (case.get("thresholds") or {}).get("p95_latency_ms"),
        "samples": len(rows),
        "rows": rows,
        "summary": {
            "min_post_ms": min(samples_ms) if samples_ms else 0,
            "max_post_ms": max(samples_ms) if samples_ms else 0,
            "mean_post_ms": (sum(samples_ms) / len(samples_ms)) if samples_ms else 0.0,
            "p95_post_ms": _percentile_linear(samples_ms, 95.0),
            "calls_over_threshold": sum(
                1
                for item in samples_ms
                if (case.get("thresholds") or {}).get("p95_latency_ms") is not None
                and item > int((case.get("thresholds") or {})["p95_latency_ms"])
            ),
        },
    }


def format_markdown(report: dict[str, Any], *, label: str) -> str:
    """
    Format one benchmark report as Markdown tables.

    Args:
        report: Benchmark report from run_stage_benchmark().
        label: Human-readable benchmark label.
    Returns:
        Markdown report.
    """

    lines = [
        f"## {label}",
        "",
        "| Field | Value |",
        "|-------|-------|",
        f"| task_id | `{report['task_id']}` |",
        f"| samples | {report['samples']} |",
        f"| threshold_ms | {report['threshold_ms']} |",
        "",
        "| Call | POST /run ms | API latency_ms | OpenAI ms | Compose total ms | Attempts | Local non-compose ms | Status | Send |",
        "|------|--------------|----------------|-----------|------------------|----------|----------------------|--------|------|",
    ]
    for row in report["rows"]:
        lines.append(
            "| {call} | {post_ms} | {api_latency_ms} | {openai_ms} | {compose_total_ms} | "
            "{openai_attempts} | {local_non_compose_ms} | {status} | {send} |".format(**row)
        )
    summary = report["summary"]
    lines.extend(
        [
            "",
            "| Metric | Value |",
            "|--------|-------|",
            f"| Min POST /run ms | {summary['min_post_ms']} |",
            f"| Max POST /run ms | {summary['max_post_ms']} |",
            f"| Mean POST /run ms | {summary['mean_post_ms']:.2f} |",
            f"| P95 POST /run ms | {summary['p95_post_ms']:.2f} |",
            f"| Calls over threshold | {summary['calls_over_threshold']} / {report['samples']} |",
            "",
        ]
    )
    return "\n".join(lines)


def _mode_env(args: argparse.Namespace) -> dict[str, str | None]:
    """
    Build composer environment overrides for a CLI mode.
    """

    overrides: dict[str, str | None] = {
        "REALPAGE_COMPOSER_FAST_PATH": "1" if args.mode == "fast-path" else None,
    }
    if args.mode == "optimized":
        overrides["REALPAGE_COMPOSER_MODEL"] = args.model
        overrides["REALPAGE_COMPOSER_TEMPERATURE"] = str(args.temperature)
        overrides["REALPAGE_COMPOSER_MAX_TOKENS"] = str(args.max_tokens)
    return overrides


def main() -> None:
    """
    CLI entry point for stage-level latency benchmarking.
    """

    parser = argparse.ArgumentParser(description="Benchmark one eval case with stage timings.")
    parser.add_argument("--case-path", default="sample.json", help="JSON, JSON array, or JSONL file.")
    parser.add_argument("--case-index", type=int, default=0, help="Zero-based case index.")
    parser.add_argument("--samples", type=int, default=10, help="Number of /run samples.")
    parser.add_argument(
        "--mode",
        choices=("baseline", "optimized", "fast-path"),
        default="baseline",
        help="Benchmark mode.",
    )
    parser.add_argument("--model", default="gpt-4o-mini", help="Optimized mode composer model.")
    parser.add_argument("--temperature", type=float, default=0.0, help="Optimized mode temperature.")
    parser.add_argument("--max-tokens", type=int, default=220, help="Optimized mode max_tokens.")
    args = parser.parse_args()

    cases = _load_cases(Path(args.case_path))
    if not cases:
        raise SystemExit("No benchmark cases found.")
    case = cases[args.case_index]
    report = run_stage_benchmark(case, samples=args.samples, env_overrides=_mode_env(args))
    print(format_markdown(report, label=f"{args.mode} latency benchmark"))


if __name__ == "__main__":
    main()
