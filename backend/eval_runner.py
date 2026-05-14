"""
File: eval_runner.py
Purpose: JSONL eval runner for bundled outreach decision cases.
Author: Sreeram
"""

import argparse
import json
import logging
import os
from pathlib import Path
from time import perf_counter
from typing import Any

from backend.tools.compliance import check_compliance

logger = logging.getLogger(__name__)


def _load_dotenv() -> None:
    """
    Load backend/.env into os.environ before eval runs so API keys are available.

    Uses python-dotenv when present (transitive dep of pydantic-settings).
    Falls back to a simple line parser so evals work even without the package.
    Does not override variables already set in the environment.
    """

    env_path = Path(__file__).parent / ".env"
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
Score how personalized this message feels for the given recipient profile.

Scoring rubric — award points when each criterion is clearly met:
- Recipient's first name is used correctly: 0.3 points
- A specific profile interest is referenced — this includes city_interest (target location or city),
  amenity_interest (named amenities like pool, fitness), or move timeline: 0.3 points
- The property name is mentioned naturally: 0.2 points
- The overall tone feels tailored to this specific person rather than a generic template: 0.2 points

Channel-aware tone rule: SMS messages are limited to a short character count by format.
For SMS, award the full 0.2 tone points when all available profile fields are present and
the message is conversational in register — do not penalise brevity as a lack of personalisation.
For email or voice, apply the tone criterion at full strictness.

Return JSON only: {"score": <number 0.0 to 1.0>, "reasoning": "<one sentence>"}
"""

DEFAULT_SAMPLE_PATH = Path(__file__).parent / "data" / "sample.jsonl"
EVAL_DATA_DIR = Path(__file__).parent / "data"
MAX_EVAL_FILE_BYTES = 1_000_000


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
    Load JSONL eval cases from disk in file order.

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


def _compose_for_personalization(case: dict[str, Any]) -> str:
    """
    Call the real compose_message to get a live-generated body for personalization scoring.

    Structural eval checks (channel, compliance, body_match) use the fixture stub.
    This call runs the real LLM so the personalization judge scores actual output,
    not the fixture body. Returns empty string when the LLM is unavailable.

    Args:
        case: Parsed JSONL case.
    Returns:
        Live-generated message body, or empty string when LLM is unavailable.
    """

    if not os.getenv("OPENAI_API_KEY"):
        return ""

    try:
        from backend.tools.message_composer import compose_message

        nm = (case.get("expected") or {}).get("next_message") or {}
        channel = str(nm.get("channel") or "sms")
        case_input = case.get("input") or {}
        constraints = ((case.get("assertions") or {}).get("constraints")) or {}

        raw = compose_message(
            channel=channel,
            persona=str(case.get("persona") or ""),
            lifecycle_stage=str(case.get("lifecycle_stage") or ""),
            profile=case_input.get("profile") or {},
            property_name=str(case_input.get("property_name") or ""),
            primary_cta=str(constraints.get("primary_cta") or "book_tour"),
            constraints=constraints,
        )
        parsed = json.loads(raw)
        return str((parsed.get("result") or {}).get("body") or "")
    except Exception as exc:
        logger.warning("[compose_for_personalization] unavailable: %s", exc)
        return ""


def _score_personalization(
    body: str,
    profile: dict[str, Any],
    property_name: str,
    channel: str = "",
) -> float | None:
    """
    Call an LLM judge to score message personalization on a 0.0–1.0 scale.

    Args:
        body: Generated message body to evaluate.
        profile: Recipient profile facts (first_name, amenity_interest, etc.).
        property_name: Property being marketed.
        channel: Selected outreach channel (sms, email, voice) — passed to the judge
            so the channel-aware tone rule is applied precisely, not inferred.
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
                            "channel": channel,
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


def _without_none(value: dict[str, Any] | None) -> dict[str, Any] | None:
    """
    Remove None-valued fields before comparing sparse expected objects.

    Args:
        value: Dictionary to normalize.
    Returns:
        Dictionary without None values, or None.
    """

    if value is None:
        return None
    return {key: item for key, item in value.items() if item is not None}


def _run_case_via_api(case: dict[str, Any]) -> dict[str, Any]:
    """
    Run one case through the FastAPI `/run` route.

    Args:
        case: Parsed JSONL case.
    Returns:
        Agent output from the API response.
    """

    from unittest.mock import patch

    from fastapi.testclient import TestClient

    from backend.compose_fixture_stub import compose_message_json_for_case
    from backend.main import create_app

    with patch(
        "backend.agent.compose_message",
        side_effect=lambda *_, **__: compose_message_json_for_case(case),
    ):
        client = TestClient(create_app())
        response = client.post("/run", json=case)
    if response.status_code != 200:
        raise RuntimeError(f"/run failed during eval: status={response.status_code}")
    payload = response.json()
    return payload["output"]


def score_output(
    generated: dict[str, Any],
    expected: dict[str, Any],
    assertions: dict[str, Any] | None = None,
    thresholds: dict[str, Any] | None = None,
    *,
    elapsed_ms: int = 0,
    profile: dict[str, Any] | None = None,
    property_name: str = "",
    personalization_body: str = "",
) -> dict[str, bool]:
    """
    Score generated output against expected fields used by the PoC gate.

    Args:
        generated: Agent output dictionary.
        expected: Expected output dictionary from the JSONL case.
        assertions: Optional JSONL assertions to evaluate against generated output.
        thresholds: Optional JSONL thresholds; drives latency, personalization, and safety checks.
        elapsed_ms: End-to-end pipeline latency measured by the caller.
        profile: Recipient profile facts for the personalization judge.
        property_name: Property name for the personalization judge.
        personalization_body: Live-generated body for quality scoring; falls back to
            the generated body when empty (offline/no-LLM mode).
    Returns:
        Boolean score dimensions; personalization_pass is omitted when LLM is unavailable.
    """

    generated_message = generated.get("next_message") or {}
    expected_message = expected.get("next_message") or {}
    generated_action = _without_none(generated.get("next_action"))
    expected_action = _without_none(expected.get("next_action"))
    generated_cta = _without_none(generated_message.get("cta"))
    expected_cta = _without_none(expected_message.get("cta"))
    body = str(generated_message.get("body") or "")
    expected_body = str(expected_message.get("body") or "")
    assertion_constraints = (assertions or {}).get("constraints", {})
    compliance_result = json.loads(check_compliance(body, assertion_constraints))
    compliance_payload = compliance_result.get("result") or {}
    constraints_pass = bool(compliance_payload.get("passed", False))
    required_states = set((assertions or {}).get("required_states", []))
    required_states_match = True
    if "consent_verified" in required_states:
        required_states_match = required_states_match and (
            generated.get("send") is False or bool(generated_message.get("channel"))
        )
    if "fair_housing_check_passed" in required_states:
        required_states_match = required_states_match and constraints_pass
    if "brand_style_applied" in required_states:
        required_states_match = required_states_match and "STOP to opt out" in body
    expected_send = expected_message != {}

    scores: dict[str, bool] = {
        "send_match": generated.get("send") is expected_send,
        "channel_match": generated_message.get("channel")
        == expected_message.get("channel"),
        "send_time_match": generated_message.get("send_at")
        == expected_message.get("send_at"),
        "subject_match": generated_message.get("subject")
        == expected_message.get("subject"),
        "body_match": body == expected_body,
        "cta_match": generated_cta == expected_cta,
        "next_action_match": generated_action == expected_action,
        "compliance_pass": "STOP to opt out" in body,
        "constraints_pass": constraints_pass,
        "required_states_match": required_states_match,
    }

    resolved_thresholds = thresholds or {}

    # p95_latency_ms: pipeline must complete within the threshold
    p95 = resolved_thresholds.get("p95_latency_ms")
    if p95 is not None:
        scores["latency_pass"] = elapsed_ms < int(p95)

    # safety_violations_max: zero tolerance — any violation is a hard fail
    safety_max = resolved_thresholds.get("safety_violations_max")
    if safety_max is not None:
        violations = compliance_payload.get("violations") or []
        scores["safety_violations_pass"] = len(violations) <= int(safety_max)

    # personalization_score_min: LLM judge on live-generated body (not fixture body).
    # personalization_body is the real composer output; falls back to fixture body in
    # offline mode so the check still runs, but may fail if the fixture lacks profile fields.
    personalization_min = resolved_thresholds.get("personalization_score_min")
    if personalization_min is not None and generated.get("send") is True:
        score_body = personalization_body if personalization_body else body
        if score_body:
            p_score = _score_personalization(
                score_body,
                profile or {},
                property_name,
                channel=str(generated_message.get("channel") or ""),
            )
            if p_score is not None:
                scores["personalization_pass"] = p_score >= float(personalization_min)

    return scores


def run_case(case: dict[str, Any]) -> dict[str, Any]:
    """
    Run one eval case through the agent and score the output.

    Args:
        case: Parsed JSONL case.
    Returns:
        Eval result with generated output, expected output, scores, and runtime.
    """

    started_at = perf_counter()
    generated = _run_case_via_api(case)
    elapsed_ms = int((perf_counter() - started_at) * 1000)
    expected = case["expected"]
    case_input = case.get("input", {})
    personalization_body = _compose_for_personalization(case)
    scores = score_output(
        generated,
        expected,
        assertions=case.get("assertions"),
        thresholds=case.get("thresholds"),
        elapsed_ms=elapsed_ms,
        profile=case_input.get("profile") or {},
        property_name=str(case_input.get("property_name") or ""),
        personalization_body=personalization_body,
    )

    return {
        "task_id": case["task_id"],
        "generated": generated,
        "expected": expected,
        "scores": scores,
        "passed": all(scores.values()),
        "elapsed_ms": elapsed_ms,
    }


def run_all(path: str | Path = DEFAULT_SAMPLE_PATH) -> dict[str, Any]:
    """
    Run all JSONL eval cases and aggregate pass/fail counts.

    Args:
        path: JSONL file path.
    Returns:
        Aggregate eval report.
    """

    results = [run_case(case) for case in load_cases(path)]
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
    args = parser.parse_args()
    print(json.dumps(_summarize_report(run_all(args.path)), indent=2))


if __name__ == "__main__":
    main()
