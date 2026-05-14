"""
File: timing.py
Purpose: Tool for scheduling outreach at the next local morning send window.
Author: Sreeram
"""

import json
import logging
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)


def determine_send_time(
    timezone: str,
    last_interaction: str,
    lifecycle_stage: str,
) -> str:
    """
    TOOL: determine_send_time
    Purpose: Compute the next-day 9:00 AM local send timestamp.
    When called: After a sendable channel is selected and before returning a message.
    Returns: {"error": str | null, "result": {"send_at": str, "rationale": str}}
    Note: Atomic — computes timing only; it does not select channels or compose messages.

    Args:
        timezone: Recipient IANA timezone.
        last_interaction: Last interaction timestamp in ISO 8601 format.
        lifecycle_stage: Recipient lifecycle stage, included for audit rationale.
    Returns:
        JSON string with ISO 8601 send timestamp and rationale.
    """

    try:
        logger.info("[determine_send_time] timezone=%s stage=%s", timezone, lifecycle_stage)
        parsed = last_interaction.replace("Z", "+00:00")
        interaction_utc = datetime.fromisoformat(parsed)
        if interaction_utc.tzinfo is None:
            interaction_utc = interaction_utc.replace(tzinfo=UTC)

        recipient_zone = ZoneInfo(timezone)
        local_interaction = interaction_utc.astimezone(recipient_zone)
        next_day = local_interaction.date() + timedelta(days=1)
        send_at = datetime.combine(
            next_day,
            time(hour=9),
            tzinfo=recipient_zone,
        )
        return json.dumps(
            {
                "error": None,
                "result": {
                    "send_at": send_at.isoformat(),
                    "rationale": "Scheduled for 9:00 AM recipient local time the day after last interaction.",
                },
            }
        )
    except Exception as exc:
        logger.error("[determine_send_time] error=%s", exc, exc_info=True)
        return json.dumps({"error": str(exc), "result": None})
