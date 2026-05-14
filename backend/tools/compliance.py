"""
File: compliance.py
Purpose: Tool for checking message compliance constraints before send.
Author: Sreeram
"""

import json
import logging
import os
import re
from urllib.parse import urlparse

from pydantic import ValidationError

from backend.constants import FAIR_HOUSING_RULES
from backend.schemas_llm import FairHousingJudgeLlmOutput

logger = logging.getLogger(__name__)

EMAIL_PATTERN = re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b")
PHONE_PATTERN = re.compile(r"(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}")
URL_PATTERN = re.compile(r"https?://[^\s)]+")
SSN_PATTERN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
DOB_PATTERN = re.compile(
    r"\b(?:dob|date\s+of\s+birth)\b|\b\d{1,2}/\d{1,2}/\d{2,4}\b",
    re.IGNORECASE,
)
ADDRESS_PATTERN = re.compile(
    r"\b\d{1,6}\s+[A-Za-z0-9 .'-]+"
    r"\s(?:st|street|ave|avenue|rd|road|dr|drive|ln|lane|blvd|boulevard)\b",
    re.IGNORECASE,
)
FINANCIAL_PATTERN = re.compile(
    r"\b(?:income|salary|bank account|routing number|credit score|payment history)\b",
    re.IGNORECASE,
)
HEALTH_PATTERN = re.compile(
    r"\b(?:medical|diagnosis|therapy|medication|maintenance request)\b",
    re.IGNORECASE,
)
OPT_OUT_PATTERN = re.compile(
    r"\b(?:reply\s+)?stop\s+to\s+opt\s+out\b",
    re.IGNORECASE,
)
PROTECTED_CLASS_TERMS = {
    "adults only",
    "age",
    "elderly",
    "senior only",
    "young professionals",
    "color",
    "gender",
    "gender identity",
    "immigration status",
    "marital status",
    "student status",
    "students only",
    "sexual orientation",
    "sex",
    "race",
    "religion",
    "disabled",
    "disability",
    "children",
    "child",
    "kids",
    "no kids",
    "child-free",
    "families with children",
    "family status",
    "familial status",
    "national origin",
    "source of income",
    "voucher",
    "section 8",
}


def _has_unapproved_links(body: str, allowed_domains: set[str]) -> bool:
    """
    Check message URLs against an explicit hostname allowlist.

    Only called when ``allowed_link_domains`` is present in constraints. When the
    constraint is absent, all URLs are permitted (malformed/unsafe ones are caught
    upstream by ``check_input_security``).

    Args:
        body: Message body to scan.
        allowed_domains: Lowercase host names that are explicitly allowed.
    Returns:
        True when any URL host is absent from the allowlist.
    """

    for match in URL_PATTERN.finditer(body):
        raw = match.group(0).rstrip(".,;:!?)>\"'")
        parsed = urlparse(raw)
        hostname = (parsed.hostname or "").lower()
        if not hostname or hostname not in allowed_domains:
            return True
    return False


def _judge_fair_housing_with_llm(body: str) -> bool | None:
    """
    Run the configured LLM Fair Housing judge when explicitly enabled.

    Args:
        body: Message body to judge.
    Returns:
        True when the LLM says the body passes, False when it fails, or None when disabled.
    """

    if os.getenv("REALPAGE_USE_LLM_COMPLIANCE", "").lower() != "true":
        return None
    if not os.getenv("OPENAI_API_KEY"):
        return None

    try:
        from openai import OpenAI

        client = OpenAI()
        response = client.chat.completions.create(
            model=os.getenv("REALPAGE_COMPLIANCE_MODEL", "gpt-4o"),
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Judge whether the message complies with these Fair Housing "
                        f"rules. Return JSON only: {{\"passed\": true|false}}.\n{FAIR_HOUSING_RULES}"
                    ),
                },
                {"role": "user", "content": body},
            ],
        )
        content = response.choices[0].message.content or "{}"
        parsed = json.loads(content)
        try:
            return FairHousingJudgeLlmOutput.model_validate(parsed, strict=True).passed
        except ValidationError as exc:
            logger.warning(
                "[check_compliance] llm_judge_invalid_output error=%s payload=%r",
                exc,
                parsed,
            )
            return None
    except Exception as exc:
        logger.error("[check_compliance] llm_judge_error=%s", exc, exc_info=True)
        return None


def check_compliance(body: str, constraints: dict[str, object]) -> str:
    """
    TOOL: check_compliance
    Purpose: Validate outbound message text against safety and opt-out constraints.
    When called: After message composition and before a message is returned for sending.
    Returns: {"error": str | null, "result": {"passed": bool, "violations": list[str], "required_additions": list[str]}}
    Note: Atomic — checks compliance only; it does not rewrite messages or choose channels.

    Args:
        body: Message body to validate.
        constraints: Compliance constraints from the eval case.
    Returns:
        JSON string with pass/fail status, violations, and required additions.
    """

    try:
        logger.info("[check_compliance] body_length=%s", len(body))
        body_lower = body.lower()
        violations: list[str] = []
        required_additions: list[str] = []

        if (
            constraints.get("include_opt_out_instructions") is True
            and OPT_OUT_PATTERN.search(body) is None
        ):
            violations.append("missing_opt_out")
            required_additions.append("Add 'Reply STOP to opt out.'")

        pii_patterns = [
            EMAIL_PATTERN,
            PHONE_PATTERN,
            SSN_PATTERN,
            DOB_PATTERN,
            ADDRESS_PATTERN,
            FINANCIAL_PATTERN,
            HEALTH_PATTERN,
        ]
        if constraints.get("no_pii_leak") is True and any(
            pattern.search(body) for pattern in pii_patterns
        ):
            violations.append("pii_leak")

        allowed_raw = constraints.get("allowed_link_domains")
        if isinstance(allowed_raw, list):
            allowed_domain_set = {str(domain).lower() for domain in allowed_raw}
            if _has_unapproved_links(body, allowed_domain_set):
                violations.append("unapproved_link")

        if constraints.get("no_sensitive_discrimination") is True:
            llm_passed = _judge_fair_housing_with_llm(body)
            matched_terms = [
                term for term in PROTECTED_CLASS_TERMS if term in body_lower
            ]
            if matched_terms or llm_passed is False:
                violations.append("protected_class_language")

        return json.dumps(
            {
                "error": None,
                "result": {
                    "passed": not violations,
                    "violations": violations,
                    "required_additions": required_additions,
                },
            }
        )
    except Exception as exc:
        logger.error("[check_compliance] error=%s", exc, exc_info=True)
        return json.dumps({"error": str(exc), "result": None})
