"""
File: consent.py
Purpose: Tool for checking whether a requested outreach channel is consented.
Author: Sreeram
"""

import logging

from backend.schemas import ToolResultEnvelope

logger = logging.getLogger(__name__)


def check_consent(channel: str, consent: dict[str, bool]) -> ToolResultEnvelope:
    """
    TOOL: check_consent
    Purpose: Determine whether one outreach channel is eligible from consent flags.
    When called: Before selecting or using any outbound communication channel.
    Returns: ToolResultEnvelope with eligibility payload or error populated.
    Note: Atomic — checks exactly one channel and does not select among channels.

    Args:
        channel: Outreach channel to check.
        consent: Consent flags keyed as `{channel}_opt_in`.
    Returns:
        Envelope with channel, eligibility, and reason strings.
    """

    try:
        logger.info("[check_consent] channel=%s", channel)
        consent_key = f"{channel}_opt_in"
        eligible = bool(consent.get(consent_key, False))
        reason = (
            f"{channel} eligible: {consent_key} is true."
            if eligible
            else f"{channel} blocked: {consent_key} is false or missing."
        )
        return ToolResultEnvelope(
            error=None,
            result={
                "channel": channel,
                "eligible": eligible,
                "reason": reason,
            },
        )
    except Exception as exc:
        logger.error("[check_consent] error=%s", exc, exc_info=True)
        return ToolResultEnvelope(error=str(exc), result=None)
