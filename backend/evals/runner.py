"""
File: runner.py
Purpose: JSONL eval runner with explicit integrity metadata (stub vs live compose, latency semantics).
Author: Sreeram
"""

import argparse
import json
import logging
import math
import os
from pathlib import Path
from time import perf_counter
from typing import Any

from backend.tools.compliance import OPT_OUT_PATTERN, check_compliance

logger = logging.getLogger(__name__)


def _load_dotenv() -> None:
    """
    Load backend/.env into os.environ before eval runs so API keys are available.

    Uses python-dotenv when present (transitive dep of pydantic-settings).
    Falls back to a simple line parser so evals work even without the package.
    Does not override variables already set in the environment.
    """

    env_path = Path(__file__).parents[1] / ".env"
    if not env_path.exists():
        return
    try:
        from dotenv import load_dotenv

        load_dotenv(env_path, override=False)
        logger.debug("[eval_runner] loaded .env via python-dotenv")
    except ImportError:
        for raw in env_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))
        logger.debug("[eval_runner] loaded .env via fallback parser")


_load_dotenv()

_PERSONALIZATION_JUDGE_PROMPT = """You are a message quality judge for property management outreach.
Score how well the message uses the profile fields provided in the input.

Scoring rubric:
- Recipient's first name is used correctly: 0.30 points
- The property name is mentioned naturally: 0.25 points
- At least one present interest field is used — city_interest named, at least one amenity named,
  or move timeline acknowledged: 0.30 points
- Each additional present interest field also used beyond the first: +0.075 points each,
  capped at 0.15 bonus

A message that correctly uses every profile field present in the input scores 0.85 or above.
Deduct proportionally for any present field that is absent from the body.
Do not award or deduct points for tone, style, channel format, or message length.

Return JSON only: {"score": <number 0.0 to 1.0>, "reasoning": "<one sentence>"}
"""

DEFAULT_SAMPLE_PATH = Path(__file__).parents[1] / "data" / "sample.jsonl"
EVAL_DATA_DIR = Path(__file__).parents[1] / "data"
MAX_EVAL_FILE_BYTES = 1_000_000
DEFAULT_CLI_LATENCY_RUNS = 20

def _percentile_linear(samples: list[int], pct: float) -> float:
    """
    Nearest-rank style linear interpolation percentile on ``pct`` in [0, 100].

    Matches common treatment (e.g. NumPy ``percentile`` with default method) for P95.

    Args:
        samples: Unordered timing samples in milliseconds.
        pct: Percentile to compute (use 95.0 for P95).
    Returns:
        Interpolated percentile in milliseconds; 0.0 when ``samples`` is empty.
    """

    if not samples:
        return 0.0
    if len(samples) == 1:
        return float(samples[0])
    ordered = sorted(samples)
    n = len(ordered)
    rank = (pct / 100.0) * (n - 1)
    lo = int(math.floor(rank))
    hi = int(math.ceil(rank))
    if lo == hi:
        return float(ordered[lo])
    return float(ordered[lo] + (rank - lo) * (ordered[hi] - ordered[lo]))


def _resolve_latency_sample_count(explicit: int | None) -> int:
    """
    Return how many timed repetitions to run for P95 latency (at least one).

    Args:
        explicit: Call-site override, e.g. CLI ``--latency-runs``.
    Returns:
        Repetition count, >= 1.
    """

    if explicit is not None:
        return max(1, int(explicit))
    raw = os.getenv("REALPAGE_EVAL_LATENCY_RUNS", "1")
    try:
        return max(1, int(raw))
    except ValueError:
        return 1


def _validate_case_path(path: str | Path) -> Path:
    """
    Validate that an eval file is a bundled JSONL file under the eval data directory.

    Args:
        path: Candidate JSONL path.
    Returns:
        Resolved safe JSONL path.
    """

    jsonl_path = Path(path).resolve()
    data_dir = EVAL_DATA_DIR.resolve()
    if jsonl_path.parent != data_dir:
        raise ValueError("Eval files must live under backend/data.")
    if jsonl_path.suffix != ".jsonl":
        raise ValueError("Eval files must use the .jsonl extension.")
    if jsonl_path.stat().st_size > MAX_EVAL_FILE_BYTES:
        raise ValueError("Eval file is too large for local PoC runner.")
    return jsonl_path


def load_cases(path: str | Path) -> list[dict[str, Any]]:
    """
    Load JSONL (NDJSON) eval cases from disk in file order.

    Production contract: exactly one JSON object per physical line, UTF-8.
    Do not embed literal ``\\n`` between records on a single line; use real line breaks.

    Args:
        path: JSONL file path.
    Returns:
        Parsed case dictionaries.
    """

    jsonl_path = _validate_case_path(path)
    cases: list[dict[str, Any]] = []
    for line in jsonl_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            cases.append(json.loads(line))
    return cases


def _score_personalization(
    body: str,
    profile: dict[str, Any],
    property_name: str,
) -> float | None:
    """
    Call an LLM judge to score message personalization on a 0.0–1.0 scale.

    Args:
        body: Generated message body to evaluate.
        profile: Recipient profile facts (first_name, amenity_interest, etc.).
        property_name: Property being marketed.
    Returns:
        Personalization score between 0.0 and 1.0, or None when LLM is unavailable.
    """

    if not os.getenv("OPENAI_API_KEY"):
        logger.warning("[score_personalization] OPENAI_API_KEY not set — skipping judge")
        return None

    try:
        from openai import OpenAI

        from backend.schemas import PersonalizationJudgeLlmOutput

        client = OpenAI()
        response = client.chat.completions.create(
            model=os.getenv("REALPAGE_EVAL_MODEL", "gpt-4o"),
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": _PERSONALIZATION_JUDGE_PROMPT},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "body": body,
                            "profile": profile,
                            "property_name": property_name,
                        }
                    ),
                },
            ],
        )
        content = response.choices[0].message.content or "{}"
        parsed = PersonalizationJudgeLlmOutput.model_validate_json(content)
        logger.info(
            "[score_personalization] score=%.2f reasoning=%s",
            parsed.score,
            parsed.reasoning,
        )
        return parsed.score
    except Exception as exc:
        logger.warning("[score_personalization] judge unavailable: %s", exc)
        return None


def _run_case_via_api(case: dict[str, Any]) -> dict[str, Any]:
    """
    Run one case through the FastAPI ``/run`` route (production compose in ``compose_message``).

    Scores are derived from constraints and thresholds on the composed output; optional
    personalization uses an OpenAI judge on that body when ``personalization_score_min``
    is set — not golden ``expected`` text from the JSONL sample.

    Args:
        case: Parsed JSONL case.
    Returns:
        Agent output from the API response.
    """

    from fastapi.testclient import TestClient

    from backend.main import create_app

    client = TestClient(create_app())
    response = client.post("/run", json=case)
    if response.status_code != 200:
        raise RuntimeError(f"/run failed during eval: status={response.status_code}")
    payload = response.json()
    return payload["output"]


def score_output(
    generated: dict[str, Any],
    assertions: dict[str, Any] | None = None,
    thresholds: dict[str, Any] | None = None,
    *,
    profile: dict[str, Any] | None = None,
    property_name: str = "",
) -> dict[str, bool]:
    """
    Score generated agent output using assertion constraints and case thresholds only.

    The JSONL ``expected`` block is not consulted: it may document a golden sample but
    must not gate quality for a non-deterministic composer.

    Args:
        generated: Agent output dictionary from ``/run``.
        assertions: Optional ``assertions.constraints`` from the JSONL case.
        thresholds: Optional JSONL thresholds; drives personalization and safety checks.
        profile: Recipient profile facts for the personalization judge.
        property_name: Property name for the personalization judge.
    Returns:
        Boolean score dimensions. When ``personalization_score_min`` is set and the agent
        sends, ``personalization_pass`` is present (false if the judge cannot run).
    """

    generated_message = generated.get("next_message") or {}
    body = str(generated_message.get("body") or "")
    sending = bool(generated.get("send"))
    assertion_constraints = (assertions or {}).get("constraints", {})
    if sending:
        compliance_env = check_compliance(body, assertion_constraints)
        compliance_payload = compliance_env.result or {}
        constraints_pass = bool(compliance_payload.get("passed", False))
    else:
        compliance_payload = {"violations": []}
        constraints_pass = True
    scores: dict[str, bool] = {
        "compliance_pass": (OPT_OUT_PATTERN.search(body) is not None) if sending else True,
        "constraints_pass": constraints_pass,
    }

    resolved_thresholds = thresholds or {}

    safety_max = resolved_thresholds.get("safety_violations_max")
    if safety_max is not None:
        if sending:
            violations = compliance_payload.get("violations") or []
            scores["safety_violations_pass"] = len(violations) <= int(safety_max)
        else:
            scores["safety_violations_pass"] = True

    personalization_min = resolved_thresholds.get("personalization_score_min")
    if personalization_min is not None and sending:
        p_score = _score_personalization(body, profile or {}, property_name) if body else None
        scores["personalization_pass"] = p_score is not None and p_score >= float(personalization_min)

    return scores


def run_case(case: dict[str, Any], *, latency_sample_count: int | None = None) -> dict[str, Any]:
    """
    Run one eval case through the agent and score the output.

    **Latency:** ``p95_latency_ms`` in the case JSON gates the **P95** of POST ``/run``
    wall times (``agent_elapsed_ms`` samples). With multiple samples, the harness repeats
    ``/run`` then runs **one** scoring pass (composed body + judge when thresholds require) so **P95**
    latency is not confounded by repeated non-deterministic judge calls.

    **Integrity:** ``eval_integrity`` records how compose and personalization are wired.

    Args:
        case: Parsed JSONL case.
        latency_sample_count: Repetitions for latency (default: env ``REALPAGE_EVAL_LATENCY_RUNS``
            or ``1``).

    Returns:
        Eval result with scores, P95 latency fields, and ``eval_integrity``.
    """

    thresholds = case.get("thresholds") or {}
    case_input = case.get("input", {})
    n = _resolve_latency_sample_count(latency_sample_count)
    sampling_mode = "full_cycle" if n <= 1 else "repeated_api_then_single_score"

    # Repeat POST /run n times to collect agent wall-time samples for P95.
    agent_samples: list[int] = []
    generated: dict[str, Any] = {}
    for _ in range(n):
        t0 = perf_counter()
        generated = _run_case_via_api(case)
        agent_samples.append(int((perf_counter() - t0) * 1000))

    # Single scoring pass on the last generated output (constraints + optional OpenAI judge).
    t0 = perf_counter()
    scores = score_output(
        generated,
        assertions=case.get("assertions"),
        thresholds=thresholds,
        profile=case_input.get("profile") or {},
        property_name=str(case_input.get("property_name") or ""),
    )
    scoring_ms = int((perf_counter() - t0) * 1000)

    agent_p95 = _percentile_linear(agent_samples, 95.0)
    p95_budget = thresholds.get("p95_latency_ms")
    scores["latency_pass"] = agent_p95 <= float(int(p95_budget)) if p95_budget is not None else True

    # latency_pass is a performance metric — excluded from the correctness gate.
    non_gating = {"latency_pass"}
    correctness_scores = {k: v for k, v in scores.items() if k not in non_gating}
    total_wall = sum(agent_samples) + scoring_ms

    logger.info(
        "[eval] task_id=%s sampling_mode=%s samples=%s",
        case.get("task_id"),
        sampling_mode,
        n,
    )

    return {
        "task_id": case["task_id"],
        "generated": generated,
        "scores": scores,
        "passed": all(correctness_scores.values()),
        "elapsed_ms": int(round(total_wall)),
        "agent_elapsed_ms": int(round(agent_p95)),
        "latency": {
            "samples": n,
            "sampling_mode": sampling_mode,
            "agent_elapsed_ms_all": agent_samples,
            "agent_p95_ms": agent_p95,
            "post_sample_scoring_ms": scoring_ms,
            "case_wall_clock_ms": total_wall,
            "total_p95_ms": agent_p95,
        },
        "eval_integrity": {
            "compose_message": "openapi_chat_via_run_agent compose_message tool",
            "personalization_when_threshold_set": (
                "openai_chat_judge on composed body (_score_personalization)"
                if thresholds.get("personalization_score_min") is not None
                else "none — personalization_score_min omitted"
            ),
            "correctness_gate": sorted(correctness_scores.keys()),
            "informational_only": sorted(non_gating - {"latency_pass"}),
            "latency_sampling_mode": sampling_mode,
            "p95_latency_interpretation": (
                "P95 of POST /run durations only; compare to case p95_latency_ms. "
                "post_sample_scoring_ms is reported separately (not in that gate)."
            ),
        },
    }


def run_all(
    path: str | Path = DEFAULT_SAMPLE_PATH,
    *,
    latency_sample_count: int | None = None,
) -> dict[str, Any]:
    """
    Run all JSONL eval cases and aggregate pass/fail counts.

    Args:
        path: JSONL file path.
        latency_sample_count: Repetitions per case for P95 latency (``None`` = env or ``1``).
    Returns:
        Aggregate eval report.
    """

    n = _resolve_latency_sample_count(latency_sample_count)
    results = [run_case(case, latency_sample_count=n) for case in load_cases(path)]
    passed = sum(1 for result in results if result["passed"])
    return {
        "total": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "results": results,
    }


def _summarize_report(report: dict[str, Any]) -> dict[str, Any]:
    """
    Remove full message bodies from CLI output while preserving pass/fail detail.

    Args:
        report: Full eval report.
    Returns:
        Redacted summary safe for terminal logs.
    """

    return {
        "total": report["total"],
        "passed": report["passed"],
        "failed": report["failed"],
        "results": [
            {
                "task_id": result["task_id"],
                "passed": result["passed"],
                "scores": result["scores"],
                "elapsed_ms": result["elapsed_ms"],
                "agent_elapsed_ms": result["agent_elapsed_ms"],
                "eval_integrity": result["eval_integrity"],
                "latency": {
                    "samples": result["latency"]["samples"],
                    "sampling_mode": result["latency"]["sampling_mode"],
                    "agent_p95_ms": round(result["latency"]["agent_p95_ms"], 2),
                    "post_sample_scoring_ms": result["latency"]["post_sample_scoring_ms"],
                    "case_wall_clock_ms": result["latency"]["case_wall_clock_ms"],
                },
            }
            for result in report["results"]
        ],
    }


def main() -> None:
    """
    CLI entry point for running bundled JSONL eval cases.
    """

    parser = argparse.ArgumentParser(description="Run outreach JSONL eval cases.")
    parser.add_argument(
        "path",
        nargs="?",
        default=str(DEFAULT_SAMPLE_PATH),
        help="Path to JSONL eval file.",
    )
    parser.add_argument(
        "--latency-runs",
        type=int,
        default=None,
        help=(
            "Timed repetitions per case for P95 vs p95_latency_ms in the case JSON. "
            f"Default: env REALPAGE_EVAL_LATENCY_RUNS or {DEFAULT_CLI_LATENCY_RUNS}."
        ),
    )
    args = parser.parse_args()
    n = args.latency_runs
    if n is None:
        n = int(os.getenv("REALPAGE_EVAL_LATENCY_RUNS", str(DEFAULT_CLI_LATENCY_RUNS)))
    n = max(1, int(n))
    logger.info(
        "[eval] Harness runs POST /run with production compose_message (OpenAI chat). "
        "Pass/fail uses case constraints/thresholds; personalization_min invokes OpenAI judge on the composed body."
    )
    print(json.dumps(_summarize_report(run_all(args.path, latency_sample_count=n)), indent=2))


if __name__ == "__main__":
    main()
