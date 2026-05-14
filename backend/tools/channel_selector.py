"""
File: channel_selector.py
Purpose: Tool for selecting the first consented channel from user preferences.
Author: Sreeram
"""

import logging

from backend.schemas import ToolResultEnvelope
from backend.tools.consent import check_consent

logger = logging.getLogger(__name__)


def select_channel(channel_preferences: list[str], consent: dict[str, bool]) -> ToolResultEnvelope:
    """
    TOOL: select_channel
    Purpose: Select the highest-ranked preferred channel that is consented.
    When called: After consent flags are available and before composing a message.
    Returns: ToolResultEnvelope with selection payload or error populated.
    Note: Atomic — selects a channel only; it does not compose, schedule, or check compliance.

    Args:
        channel_preferences: Ordered list of preferred channels.
        consent: Consent flags keyed as `{channel}_opt_in`.
    Returns:
        Envelope with selected channel, fallback channel, rationale, and send flag.
    """

    try:
        logger.info("[select_channel] preferences_count=%s", len(channel_preferences))
        blocked_reasons: list[str] = []
        for index, channel in enumerate(channel_preferences):
            consent_env = check_consent(channel, consent)
            if consent_env.error:
                blocked_reasons.append(str(consent_env.error))
                channel_result = {}
            else:
                channel_result = consent_env.result or {}
            if channel_result.get("eligible") is True:
                fallback_channel = channel if index > 0 else None
                rationale = (
                    f"{channel} selected: opted in and ranked #{index + 1} in preferences."
                )
                return ToolResultEnvelope(
                    error=None,
                    result={
                        "selected_channel": channel,
                        "fallback_channel": fallback_channel,
                        "rationale": rationale,
                        "send": True,
                    },
                )
            blocked_reasons.append(str(channel_result.get("reason", "")))

        return ToolResultEnvelope(
            error=None,
            result={
                "selected_channel": None,
                "fallback_channel": None,
                "rationale": "No eligible preferred channel. "
                + " ".join(reason for reason in blocked_reasons if reason),
                "send": False,
            },
        )
    except Exception as exc:
        logger.error("[select_channel] error=%s", exc, exc_info=True)
        return ToolResultEnvelope(error=str(exc), result=None)
