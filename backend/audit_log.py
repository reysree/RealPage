"""
File: audit_log.py
Purpose: Append structured audit records for operator-visible agent failures.
Author: Sreeram
"""

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_AUDIT_PATH = _REPO_ROOT / "logs" / "agent_audit.ndjson"


def append_agent_audit(
    *,
    component: str,
    error_code: str,
    message: str,
    detail: dict[str, Any] | None = None,
) -> None:
    """
    Log an internal audit record and persist one NDJSON line under logs/agent_audit.ndjson.

    Args:
        component: Subsystem identifier (for example compose_message).
        error_code: Stable correlation code surfaced to operators.
        message: Short human-readable description (no PII).
        detail: Optional extra JSON-safe fields for operators.
    """

    payload = {
        "ts": datetime.now(UTC).isoformat(timespec="seconds"),
        "component": component,
        "error_code": error_code,
        "message": message,
        "detail": detail or {},
    }
    logger.error(
        "[%s] error_code=%s message=%s detail=%s",
        component,
        error_code,
        message,
        detail or {},
        extra={"audit": payload},
    )
    try:
        _AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _AUDIT_PATH.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except OSError as exc:
        logger.warning("[audit_log] failed to append ndjson path=%s err=%s", _AUDIT_PATH, exc)

