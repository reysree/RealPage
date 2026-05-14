"""
File: url_security.py
Purpose: Validate outreach URLs and hostname allowlist entries for SSRF-safe, public targets.
Author: Sreeram
"""

from __future__ import annotations

import ipaddress
import re
from urllib.parse import urlparse

# Loose extraction for scanning prose fields (not a full RFC 3986 parser).
_URL_TOKEN = re.compile(r"https?://[^\s<>\"{}|\\^`\[\]]+", re.IGNORECASE)


def extract_http_urls_from_text(text: str) -> list[str]:
    """
    Find probable http(s) URLs embedded in arbitrary text for security screening.

    Args:
        text: Free-form field value.
    Returns:
        Candidate URL strings with common trailing punctuation trimmed.
    """

    out: list[str] = []
    for match in _URL_TOKEN.finditer(text):
        raw = match.group(0).rstrip(".,);>]})\"'")
        out.append(raw)
    return out


def analyze_url_security(url: str) -> list[str]:
    """
    Return violation codes for malicious or unsafe HTTP(S) URLs.

    Rules: http/https only, no embedded credentials, no localhost / loopback /
    private / link-local / multicast / reserved IPs, no NUL bytes.

    Args:
        url: Absolute URL string (typically from pydantic AnyHttpUrl).
    Returns:
        Stable violation codes; empty list when acceptable for outbound marketing context.
    """

    violations: list[str] = []
    if "\x00" in url:
        violations.append("NUL_BYTE")
        return violations

    parsed = urlparse(url.strip())
    scheme = (parsed.scheme or "").lower()
    if scheme not in {"http", "https"}:
        violations.append("UNSUPPORTED_SCHEME")
        return violations

    host = parsed.hostname
    if not host:
        violations.append("MISSING_HOST")
        return violations

    if parsed.username is not None or parsed.password is not None:
        violations.append("URL_CREDENTIALS")

    host_lower = host.lower()
    if host_lower == "localhost" or host_lower.endswith(".localhost"):
        violations.append("LOCALHOST")

    try:
        ip = ipaddress.ip_address(host_lower.strip("[]"))
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            violations.append("NON_PUBLIC_HOST")
    except ValueError:
        pass

    return violations


def analyze_plain_hostname(hostname: str) -> list[str]:
    """
    Validate a hostname token used in allowlists (no scheme or path).

    Args:
        hostname: Lowercase or mixed-case hostname such as leasing.example.com.
    Returns:
        Violation codes; empty when acceptable.
    """

    violations: list[str] = []
    h = hostname.strip().lower()
    if not h:
        violations.append("EMPTY_HOST")
        return violations
    if ".." in h or "/" in h or "\\" in h or "://" in h:
        violations.append("MALFORMED_HOST")
        return violations
    if h.endswith("."):
        h = h[:-1]
    if h == "localhost" or h.endswith(".localhost"):
        violations.append("LOCALHOST")
    try:
        ip = ipaddress.ip_address(h)
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            violations.append("NON_PUBLIC_HOST")
    except ValueError:
        pass
    return violations
