"""
File: test_content_policy.py
Purpose: Tests for outreach content-language screening helpers.
Author: Sreeram
"""

from backend.core.content_policy import analyze_inappropriate_content


def test_detects_isolated_profanity_token() -> None:
    """
    Whole-word matching must flag common profanity without embedding-value echo tests.
    """

    assert analyze_inappropriate_content("what the fuck seriously") == ["PROFANITY_OR_SLUR"]


def test_allows_substrings_that_are_not_whole_words() -> None:
    """
    Substrings such as inside longer tokens must not false-positive.
    """

    assert analyze_inappropriate_content("Shitake kitchens") == []
    assert analyze_inappropriate_content("grapevine tours") == []


def test_detects_extremism_phrase_case_insensitive() -> None:
    """
    Configured hate slogans are rejected regardless of casing.
    """

    assert analyze_inappropriate_content("historical sieg heil reference") == [
        "VIOLENT_EXTREMISM_PHRASE",
    ]
