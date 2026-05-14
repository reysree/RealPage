"""
File: input_security.py
Purpose: Regex-based security screening of all input text fields before pipeline execution.
Author: Sreeram
"""

import logging
import re
from typing import NamedTuple

from backend.core.content_policy import analyze_inappropriate_content
from backend.core.url_security import analyze_url_security, extract_http_urls_from_text
from backend.schemas import ToolResultEnvelope

logger = logging.getLogger(__name__)

_DANGEROUS_SCHEME = re.compile(
    r"\b(?:javascript|data|vbscript)\s*:",
    re.IGNORECASE,
)


class _PatternGroup(NamedTuple):
    flag_type: str
    risk_level: str  # "high" | "medium" | "low"
    patterns: list[re.Pattern[str]]


# ── High-risk: block immediately ──────────────────────────────────────────────

_PROMPT_INJECTION = _PatternGroup(
    flag_type="PROMPT_INJECTION",
    risk_level="high",
    patterns=[
        re.compile(r"\bignore\s+(previous|all|prior|above)\s+instructions?\b", re.I),
        re.compile(r"\byou\s+are\s+now\s+\w", re.I),
        re.compile(r"\[\[SYSTEM\]\]", re.I),
        re.compile(r"</?system>", re.I),
        re.compile(r"\bact\s+as\s+if\s+you\s+(have\s+no|are\s+not|don.t\s+have)", re.I),
        re.compile(r"\bpretend\s+(you\s+(have|are|can)|that\s+you)", re.I),
        re.compile(r"\bforget\s+(everything|all|your)\s+(previous|prior|above|prior)", re.I),
        re.compile(r"\b(override|disregard)\s+(your|the|all)\s+(\w+\s+)?(instructions?|rules?|guidelines?|constraints?)\b", re.I),
        re.compile(r"\bjailbreak\b", re.I),
        re.compile(r"\bdo\s+anything\s+now\b", re.I),
        re.compile(r"\bdeveloper\s+mode\b", re.I),
        re.compile(r"\b(enable|activate|switch\s+to)\s+(unrestricted|unsafe|unlimited|unfiltered)\s+mode\b", re.I),
        re.compile(r"\byour\s+(true|real|actual)\s+(self|identity|purpose|instructions?)\b", re.I),
        re.compile(r"\bnew\s+(persona|identity)\b", re.I),
        re.compile(r"\bassume\s+(the\s+role|you\s+are)\b", re.I),
    ],
)

_MALICIOUS_CODE = _PatternGroup(
    flag_type="MALICIOUS_CODE",
    risk_level="high",
    patterns=[
        # SQL injection
        re.compile(r"\b(DROP|TRUNCATE)\s+TABLE\b", re.I),
        re.compile(r"\bUNION\s+(ALL\s+)?SELECT\b", re.I),
        re.compile(r"\bSELECT\s+\*\s+FROM\b", re.I),
        re.compile(r"\bDELETE\s+FROM\b", re.I),
        re.compile(r"\bINSERT\s+INTO\b", re.I),
        re.compile(r"'?\s*(OR|AND)\s+'?\d+'?\s*=\s*'?\d+'?", re.I),  # ' OR '1'='1
        re.compile(r"--\s*(DROP|SELECT|INSERT|DELETE|EXEC)\b", re.I),
        # Script / HTML injection
        re.compile(r"<script[\s/>]", re.I),
        re.compile(r"\bon\w{2,20}\s*=\s*[\"']?\s*(java|alert|eval|document|window)", re.I),
        re.compile(r"javascript\s*:", re.I),
        re.compile(r"\beval\s*\(", re.I),
        re.compile(r"\bdocument\.cookie\b", re.I),
        # Shell injection
        re.compile(r"\brm\s+-rf\b", re.I),
        re.compile(r"\bchmod\s+[0-7]{3,4}\b", re.I),
        re.compile(r"\$\([^)]{1,80}\)"),   # command substitution $()
        re.compile(r"`[^`]{1,80}`"),        # backtick substitution
        re.compile(r"\|\s*(bash|sh|zsh|cmd|powershell|python|perl|ruby)\b", re.I),
        re.compile(r";\s*(curl|wget|nc|ncat|netcat)\s", re.I),
    ],
)

_JAILBREAK = _PatternGroup(
    flag_type="JAILBREAK",
    risk_level="high",
    patterns=[
        re.compile(r"\bwithout\s+(any\s+)?(restrictions?|limitations?|filters?|safety\s+guidelines?)\b", re.I),
        re.compile(r"\b(bypass|circumvent)\s+(safety|filter|restriction|rule|guideline|compliance)\b", re.I),
        re.compile(r"\bno\s+(rules?|restrictions?|filters?|limitations?|guidelines?)\s+(apply|here|now)\b", re.I),
        re.compile(r"\bhypothetically\b.{0,60}\b(you\s+(can|could|would|should)|it.s\s+(ok|fine|allowed|permitted))\b", re.I),
        re.compile(r"\b(simulate|emulate)\s+(being|an?\s+AI|a\s+system)\s+(with(out)?|that|who)\b", re.I),
    ],
)

# ── Medium-risk: block, log for review ────────────────────────────────────────

_SOCIAL_ENGINEERING = _PatternGroup(
    flag_type="SOCIAL_ENGINEERING",
    risk_level="medium",
    patterns=[
        re.compile(r"\b(reveal|leak|expose|output|print|display|show|give)\s+(me\s+)?(your|the)\s+(system\s+prompt|api\s+key|secret|password|credentials?|database\s+schema)\b", re.I),
        re.compile(r"\bwhat\s+(are|is)\s+(your|the)\s+(instructions?|system\s+prompt|api\s+key|rules?)\b", re.I),
        re.compile(r"\b(dump|read|access|extract)\s+(the\s+)?(database|config|environment\s+variables?|\.env\b|secrets?)\b", re.I),
        re.compile(r"\brepeat\s+(everything|all|the\s+above|your\s+(system|instructions?))\b", re.I),
    ],
)

# ── Low-risk: log only, do not block ──────────────────────────────────────────

_SENSITIVE_DATA = _PatternGroup(
    flag_type="SENSITIVE_DATA_LEAK",
    risk_level="low",
    patterns=[
        re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),                       # SSN
        re.compile(r"\b(?:\d{4}[-\s]?){3}\d{4}\b"),                 # credit card (16-digit groups)
        re.compile(r"\b\d{9}\b(?!\s*[-/]\d)"),                      # 9-digit routing number (rough)
    ],
)

_ALL_GROUPS: list[_PatternGroup] = [
    _PROMPT_INJECTION,
    _MALICIOUS_CODE,
    _JAILBREAK,
    _SOCIAL_ENGINEERING,
    _SENSITIVE_DATA,
]

_RISK_ORDER = {"low": 0, "medium": 1, "high": 2}


def check_input_security(text_fields: dict[str, str]) -> ToolResultEnvelope:
    """
    TOOL: check_input_security
    Purpose: Screen all free-text input fields for prompt injection, malicious code,
        social engineering, sensitive-data patterns, and prohibited language.
    When called: First step in run_agent(), before channel selection or message composition.
    Returns: ToolResultEnvelope with passed, risk_level, flags, blocked_fields in result dict.
    Note: Atomic — regex screening only; zero network calls, no API key required.

    Args:
        text_fields: Flat dict of field_name to string value for all free-text input fields.
    Returns:
        Envelope with screening outcome for orchestration callers.
    """

    try:
        flags: list[str] = []
        blocked_fields: list[str] = []
        max_risk = "low"

        for field_name, value in text_fields.items():
            if not value:
                continue

            bad_language = analyze_inappropriate_content(value.strip())
            if bad_language:
                flags.append(
                    f"INAPPROPRIATE_CONTENT:{field_name}:{','.join(bad_language)}"
                )
                if _RISK_ORDER["high"] > _RISK_ORDER[max_risk]:
                    max_risk = "high"
                if field_name not in blocked_fields:
                    blocked_fields.append(field_name)
                continue

            if _DANGEROUS_SCHEME.search(value):
                flags.append(f"DANGEROUS_URL_SCHEME:{field_name}")
                if _RISK_ORDER["high"] > _RISK_ORDER[max_risk]:
                    max_risk = "high"
                if field_name not in blocked_fields:
                    blocked_fields.append(field_name)
                continue

            embedded_bad = False
            for candidate in extract_http_urls_from_text(value):
                url_issues = analyze_url_security(candidate)
                if url_issues:
                    flags.append(f"UNSAFE_URL:{field_name}:{','.join(url_issues)}")
                    if _RISK_ORDER["high"] > _RISK_ORDER[max_risk]:
                        max_risk = "high"
                    if field_name not in blocked_fields:
                        blocked_fields.append(field_name)
                    embedded_bad = True
                    break
            if embedded_bad:
                continue

            for group in _ALL_GROUPS:
                for pattern in group.patterns:
                    if pattern.search(value):
                        flags.append(f"{group.flag_type}:{field_name}")
                        if _RISK_ORDER[group.risk_level] > _RISK_ORDER[max_risk]:
                            max_risk = group.risk_level
                        if group.risk_level in ("high", "medium") and field_name not in blocked_fields:
                            blocked_fields.append(field_name)
                        break  # one flag per group per field is sufficient

        passed = max_risk == "low"

        logger.info(
            "[check_input_security] passed=%s risk_level=%s flags=%s",
            passed,
            max_risk,
            flags,
        )

        return ToolResultEnvelope(
            error=None,
            result={
                "passed": passed,
                "risk_level": max_risk,
                "flags": flags,
                "blocked_fields": blocked_fields,
            },
        )

    except Exception as exc:
        # Fail open: regex failure must not crash the request.
        logger.warning("[check_input_security] screen_error=%s", exc, exc_info=True)
        return ToolResultEnvelope(
            error=None,
            result={
                "passed": True,
                "risk_level": "low",
                "flags": ["SECURITY_CHECK_ERROR: screen failed — failing open; see logs"],
                "blocked_fields": [],
            },
        )
