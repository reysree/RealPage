"""
File: test_audit_log.py
Purpose: Behavior tests for structured agent audit log persistence.
Author: Sreeram
"""

import json
from pathlib import Path

import pytest

import backend.core.audit_log as audit_log


def test_append_agent_audit_writes_one_structured_ndjson_line(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Verify internal agent failures are persisted as one structured NDJSON line.
    """

    audit_path = tmp_path / "agent_audit.ndjson"
    monkeypatch.setattr(audit_log, "_AUDIT_PATH", audit_path)

    audit_log.append_agent_audit(
        component="run_agent",
        error_code="OPENAI_API_KEY_MISSING",
        message="composer unavailable",
        detail={"stage": "compose"},
    )

    lines = audit_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["component"] == "run_agent"
    assert payload["error_code"] == "OPENAI_API_KEY_MISSING"
    assert payload["message"] == "composer unavailable"
    assert payload["detail"] == {"stage": "compose"}
    assert "ts" in payload
