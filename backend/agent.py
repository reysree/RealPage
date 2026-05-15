"""
File: agent.py
Purpose: Outreach agent orchestration over validated case inputs and tools.
Author: Sreeram
"""

import logging
from datetime import datetime, timezone
from typing import Any

from backend.core.audit_log import append_agent_audit
from backend.schemas import AgentOutput, AuditTrailEntry, MessageOutput, NextAction, RunRequest, ToolResultEnvelope
from backend.tools.channel_selector import select_channel
from backend.tools.compliance import check_compliance
from backend.tools.consent import check_consent
from backend.tools.input_security import check_input_security
from backend.tools.message_composer import compose_message
from backend.tools.timing import determine_send_time

logger = logging.getLogger(__name__)


def _unwrap_tool_result(envelope: ToolResultEnvelope, tool_name: str) -> dict[str, Any]:
    """
    Normalize one tool envelope and raise when the tool reported an execution error.

    Args:
        envelope: Structured response from an in-process tool.
        tool_name: Tool name for error context.
    Returns:
        The tool's ``result`` payload dict.
    """

    err = envelope.error
    if err:
        raise ValueError(f"{tool_name} failed: {err}")
    result = envelope.result
    if not isinstance(result, dict):
        raise ValueError(f"{tool_name} returned no result payload")
    return result


def _unwrap_compose_tool(envelope: ToolResultEnvelope) -> dict[str, Any] | None:
    """
    Extract compose_message result dict, or None when composition failed.

    Failures are logged and audited internally. The caller returns a blocked ``AgentOutput``
    when ``None`` is returned — no error details propagate to the API response.

    Args:
        envelope: compose_message return value.
    Returns:
        Result payload dict, or None when the composer reported an error.
    """

    err = envelope.error
    result = envelope.result
    if err or not isinstance(result, dict):
        code = str(envelope.error_code or "COMPOSER_FAILED")
        append_agent_audit(
            component="run_agent",
            error_code=code,
            message=str(err or "composer returned no result payload"),
            detail={},
        )
        logger.warning("[run_agent] composer_failed code=%s", code)
        return None
    return result


def _compute_follow_up_spacing_days(days_until_move: int) -> int:
    """
    Turn move-horizon days into a bounded follow-up delay for open-stage prospects.

    Args:
        days_until_move: Whole days from last-interaction date to move-date target.
    Returns:
        Days until the next nurture touch (clamped between 3 and 21).
    """

    return max(3, min(21, days_until_move // 20))


def _build_next_action(request: RunRequest) -> NextAction:
    """
    Build the recommended next action from persona, lifecycle, and move-date horizon.

    Args:
        request: Validated outreach run request.
    Returns:
        Next action for follow-up automation.
    """

    move_date = request.input.move_date_target
    interaction_date = request.input.last_interaction.date()
    days_until_move = (move_date - interaction_date).days

    if days_until_move < 45:
        return NextAction(
            type="start_cadence",
            name="prospect_welcome_short_horizon",
        )

    if request.lifecycle_stage == "open":
        return NextAction(
            type="follow_up_in_days",
            value=_compute_follow_up_spacing_days(days_until_move),
        )

    return NextAction(
        type="start_cadence",
        name="prospect_welcome_long_horizon",
    )


def _dump_output(agent_output: AgentOutput) -> dict[str, Any]:
    """
    Serialize agent output for APIs and persistence, keeping explicit null branches.

    Args:
        agent_output: Completed agent decision payload.
    Returns:
        Boundary-safe dictionary with nulls retained for skipped message fields.
    """

    return agent_output.model_dump(mode="python", exclude_none=False)


def _extract_text_fields(request: RunRequest) -> dict[str, str]:
    """
    Collect all free-text fields from a validated request for security screening.

    Args:
        request: Validated outreach run request.
    Returns:
        Flat dict of field_name to string value covering every user-supplied text field.
    """

    fields: dict[str, str] = {
        "persona": request.persona,
        "lifecycle_stage": request.lifecycle_stage,
        "property_name": request.input.property_name,
        "profile.first_name": request.input.profile.first_name,
    }
    if request.input.profile.city_interest:
        fields["profile.city_interest"] = request.input.profile.city_interest
    if request.input.profile.amenity_interest:
        for i, item in enumerate(request.input.profile.amenity_interest):
            fields[f"profile.amenity_interest[{i}]"] = item
    if request.input.listing_url:
        fields["input.listing_url"] = str(request.input.listing_url)
    if request.assertions.constraints.brand_style_notes:
        fields["constraints.brand_style_notes"] = request.assertions.constraints.brand_style_notes
    if request.assertions.constraints.compliance_suffix:
        fields["constraints.compliance_suffix"] = request.assertions.constraints.compliance_suffix
    if request.assertions.constraints.primary_cta:
        fields["constraints.primary_cta"] = request.assertions.constraints.primary_cta
    return fields


def _get_timestamp() -> str:
    """
    Get current timestamp in ISO8601 format.

    Returns:
        ISO8601 formatted timestamp.
    """
    return datetime.now(timezone.utc).isoformat()


def run_agent(case_input: dict[str, Any]) -> dict[str, Any]:
    """
    Run one stateless outreach case through selection, composition, and compliance.

    Args:
        case_input: Raw JSONL record shaped like `RunRequest`.
    Returns:
        Agent output dictionary with send decision, message, and next action.
    """

    request = RunRequest.model_validate(case_input)
    constraints = request.assertions.constraints.model_dump(exclude_none=True)
    audit_trail: list[AuditTrailEntry] = []

    security_result = _unwrap_tool_result(
        check_input_security(_extract_text_fields(request)),
        "check_input_security",
    )
    if security_result.get("passed") is not True:
        audit_trail.append(
            AuditTrailEntry(
                node="input_security",
                decision=False,
                reasoning=f"Security screen blocked input: {security_result.get('risk_level')}",
                timestamp=_get_timestamp(),
            )
        )
        logger.warning(
            "[run_agent] input blocked by security screen: risk_level=%s flags=%s",
            security_result.get("risk_level"),
            security_result.get("flags"),
        )
        output = AgentOutput(
            send=False,
            next_message=None,
            next_action=NextAction(
                type="human_in_the_loop",
                name="pipeline_blocked",
                value=None,
            ),
            audit_trail=audit_trail,
        )
        return _dump_output(output)

    audit_trail.append(
        AuditTrailEntry(
            node="input_security",
            decision=True,
            reasoning="Input passed security screening",
            timestamp=_get_timestamp(),
        )
    )

    channel_result = _unwrap_tool_result(
        select_channel(request.channel_preferences, request.consent.model_dump()),
        "select_channel",
    )
    if channel_result.get("send") is not True:
        audit_trail.append(
            AuditTrailEntry(
                node="channel_selector",
                decision=False,
                reasoning=f"No eligible channel in preferences: {request.channel_preferences}",
                timestamp=_get_timestamp(),
            )
        )
        output = AgentOutput(
            send=False,
            next_message=None,
            next_action=NextAction(
                type="human_in_the_loop",
                name="pipeline_blocked",
                value=None,
            ),
            audit_trail=audit_trail,
        )
        return _dump_output(output)

    selected_channel = str(channel_result["selected_channel"])
    audit_trail.append(
        AuditTrailEntry(
            node="channel_selector",
            decision=True,
            reasoning=f"Selected channel: {selected_channel}",
            timestamp=_get_timestamp(),
        )
    )

    consent_for_channel = _unwrap_tool_result(
        check_consent(selected_channel, request.consent.model_dump()),
        "check_consent",
    )
    if consent_for_channel.get("eligible") is not True:
        audit_trail.append(
            AuditTrailEntry(
                node="consent",
                decision=False,
                reasoning=f"Channel {selected_channel} not consented",
                timestamp=_get_timestamp(),
            )
        )
        output = AgentOutput(
            send=False,
            next_message=None,
            next_action=NextAction(
                type="human_in_the_loop",
                name="pipeline_blocked",
                value=None,
            ),
            audit_trail=audit_trail,
        )
        return _dump_output(output)

    audit_trail.append(
        AuditTrailEntry(
            node="consent",
            decision=True,
            reasoning=f"Consent verified for {selected_channel}",
            timestamp=_get_timestamp(),
        )
    )

    timing_result = _unwrap_tool_result(
        determine_send_time(
            request.input.timezone,
            request.input.last_interaction.isoformat(),
            request.lifecycle_stage,
        ),
        "determine_send_time",
    )
    audit_trail.append(
        AuditTrailEntry(
            node="timing",
            decision=True,
            reasoning=f"Scheduled for {timing_result.get('send_at')}",
            timestamp=_get_timestamp(),
        )
    )

    compose_envelope = compose_message(
        channel=selected_channel,
        persona=request.persona,
        lifecycle_stage=request.lifecycle_stage,
        profile=request.input.profile.model_dump(exclude_none=True),
        property_name=request.input.property_name,
        primary_cta=constraints.get("primary_cta", "book_tour"),
        constraints=constraints,
        consent_verification={
            "channel": consent_for_channel.get("channel"),
            "eligible": consent_for_channel.get("eligible"),
            "reason": consent_for_channel.get("reason"),
        },
    )
    composer_result = _unwrap_compose_tool(compose_envelope)
    if composer_result is None:
        audit_trail.append(
            AuditTrailEntry(
                node="compose_message",
                decision=False,
                reasoning="Message composition failed",
                timestamp=_get_timestamp(),
            )
        )
        output = AgentOutput(
            send=False,
            next_message=None,
            next_action=NextAction(
                type="human_in_the_loop",
                name="pipeline_blocked",
                value=None,
            ),
            audit_trail=audit_trail,
        )
        return _dump_output(output)

    audit_trail.append(
        AuditTrailEntry(
            node="compose_message",
            decision=True,
            reasoning="Message drafted successfully",
            timestamp=_get_timestamp(),
        )
    )

    compliance_result = _unwrap_tool_result(
        check_compliance(str(composer_result["body"]), constraints),
        "check_compliance",
    )
    if compliance_result.get("passed") is not True:
        audit_trail.append(
            AuditTrailEntry(
                node="compliance",
                decision=False,
                reasoning=f"Compliance violations: {compliance_result.get('violations')}",
                timestamp=_get_timestamp(),
            )
        )
        output = AgentOutput(
            send=False,
            next_message=None,
            next_action=NextAction(
                type="human_in_the_loop",
                name="pipeline_blocked",
                value=None,
            ),
            audit_trail=audit_trail,
        )
        return _dump_output(output)

    audit_trail.append(
        AuditTrailEntry(
            node="compliance",
            decision=True,
            reasoning="Message passed compliance checks",
            timestamp=_get_timestamp(),
        )
    )

    output = AgentOutput(
        send=True,
        next_message=MessageOutput(
            channel=selected_channel,
            send_at=str(timing_result["send_at"]),
            subject=composer_result.get("subject"),
            body=str(composer_result["body"]),
            cta=composer_result["cta"],
        ),
        next_action=_build_next_action(request),
        audit_trail=audit_trail,
    )
    return _dump_output(output)
