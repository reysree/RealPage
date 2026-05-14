"""
File: content_policy.py
Purpose: Detect profanity, slurs, and violent-extremism phrases in user-supplied text.
Author: Sreeram
"""

from __future__ import annotations

import re

# Strong language / slurs — whole-word match only (case-insensitive). Operators may extend.
_DISALLOWED_WORDS: frozenset[str] = frozenset(
    {
        "fuck",
        "fucking",
        "shit",
        "bullshit",
        "bitch",
        "bastard",
        "asshole",
        "cunt",
        "dick",
        "pussy",
        "slut",
        "whore",
        "nigger",
        "faggot",
        "spic",
        "chink",
        "retard",
        "rape",
    }
)
# Pre-compiled at module level — never recompile inside a request path.
_DISALLOWED_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(rf"\b{re.escape(word)}\b", re.I) for word in _DISALLOWED_WORDS
)

# Violent extremism / hate slogans — phrases, not personal names (avoid false positives).
_EXTREMISM_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bheil\s+hitler\b", re.I),
    re.compile(r"\bsieg\s+heil\b", re.I),
    re.compile(r"\b1488\b"),
    re.compile(r"\bkkk\b", re.I),
    re.compile(r"\blynch\s+(them|him|her|all)\b", re.I),
)


def analyze_inappropriate_content(text: str) -> list[str]:
    """
    Return violation codes for text that must not appear in outreach inputs.

    Personal-name denylists are intentionally omitted: they correlate with protected
    classes and produce false positives. Use phrase-based hate markers instead.

    Args:
        text: Single user-supplied field after trimming by callers.
    Returns:
        Stable violation codes (empty when acceptable).
    """

    if not text:
        return []

    violations: list[str] = []
    lowered = text.lower()

    if any(pattern.search(text) for pattern in _DISALLOWED_PATTERNS):
        violations.append("PROFANITY_OR_SLUR")

    for pattern in _EXTREMISM_PATTERNS:
        if pattern.search(lowered):
            violations.append("VIOLENT_EXTREMISM_PHRASE")
            break

    return violations


def outreach_input_must_pass_language_policy(text: str | None) -> None:
    """
    Raise ValueError when input text violates outreach language policy.

    Args:
        text: Field value or None (ignored).
    Returns:
        None
    """

    if text is None:
        return
    codes = analyze_inappropriate_content(text.strip())
    if codes:
        raise ValueError(
            "Input contains language or phrases that are not allowed for outreach."
        )
