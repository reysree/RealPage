"""
File: channel_selector.py
Purpose: Tool for selecting the first consented channel from user preferences.
Author: Sreeram
"""

import json
import logging

from backend.tools.consent import check_consent

logger = logging.getLogger(__name__)


def select_channel(channel_preferences: list[str], consent: dict[str, bool]) -> str:
    """
    TOOL: select_channel
    Purpose: Select the highest-ranked preferred channel that is consented.
    When called: After consent flags are available and before composing a message.
    Returns: {"error": str | null, "result": {"selected_channel": str | null, "fallback_channel": str | null, "rationale": str, "send": bool}}
    Note: Atomic — selects a channel only; it does not compose, schedule, or check compliance.

    Args:
        channel_preferences: Ordered list of preferred channels.
        consent: Consent flags keyed as `{channel}_opt_in`.
    Returns:
        JSON string with selected channel, fallback channel, rationale, and send flag.
    """

    try:
        logger.info("[select_channel] preferences_count=%s", len(channel_preferences))
        blocked_reasons: list[str] = []
        for index, channel in enumerate(channel_preferences):
            consent_result = json.loads(check_consent(channel, consent))
            channel_result = consent_result.get("result") or {}
            if channel_result.get("eligible") is True:
                fallback_channel = channel if index > 0 else None
                rationale = (
                    f"{channel} selected: opted in and ranked #{index + 1} in preferences."
                )
                return json.dumps(
                    {
                        "error": None,
                        "result": {
                            "selected_channel": channel,
                            "fallback_channel": fallback_channel,
                            "rationale": rationale,
                            "send": True,
                        },
                    }
                )
            blocked_reasons.append(str(channel_result.get("reason", "")))

        return json.dumps(
            {
                "error": None,
                "result": {
                    "selected_channel": None,
                    "fallback_channel": None,
                    "rationale": "No eligible preferred channel. "
                    + " ".join(reason for reason in blocked_reasons if reason),
                    "send": False,
                },
            }
        )
    except Exception as exc:
        logger.error("[select_channel] error=%s", exc, exc_info=True)
        return json.dumps({"error": str(exc), "result": None})
