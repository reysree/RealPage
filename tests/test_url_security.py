"""
File: test_url_security.py
Purpose: Unit tests for URL and hostname safety helpers.
Author: Sreeram
"""

from backend.url_security import (
    analyze_plain_hostname,
    analyze_url_security,
    extract_http_urls_from_text,
)


def test_public_https_url_has_no_violations() -> None:
    """
    Normal marketing URLs must pass security analysis.
    """

    assert analyze_url_security("https://leasing.example.com/tours") == []


def test_rejects_loopback_and_private_ips() -> None:
    """
    SSRF-style targets must be flagged.
    """

    assert "NON_PUBLIC_HOST" in analyze_url_security("http://127.0.0.1/admin")
    assert "NON_PUBLIC_HOST" in analyze_url_security("https://192.168.4.2/")
    assert "LOCALHOST" in analyze_url_security("http://localhost/")


def test_rejects_credentials_in_netloc() -> None:
    """
    URLs with embedded basic-auth credentials must not be accepted.
    """

    assert "URL_CREDENTIALS" in analyze_url_security("http://user:pass@evil.example/page")


def test_plain_hostname_allowlist_rejects_paths_and_localhost() -> None:
    """
    Allowlist tokens are hostnames only and must be public.
    """

    assert analyze_plain_hostname("leasing.example.com") == []
    assert analyze_plain_hostname("localhost") == ["LOCALHOST"]
    assert analyze_plain_hostname("evil.com/path") == ["MALFORMED_HOST"]


def test_extract_urls_from_text_trims_trailing_punctuation() -> None:
    """
    URL extraction should drop trailing sentence punctuation.
    """

    hits = extract_http_urls_from_text("Visit https://example.com/path.")
    assert hits == ["https://example.com/path"]
