"""Mailbox MCP tools."""

from __future__ import annotations

from clawteam.mcp.helpers import coerce_enum, team_mailbox, to_payload
from clawteam.team.models import MessageType


def mailbox_send(
    team_name: str,
    from_agent: str,
    to: str,
    content: str | None = None,
    msg_type: str | None = None,
    request_id: str | None = None,
    key: str | None = None,
    proposed_name: str | None = None,
    capabilities: str | None = None,
    feedback: str | None = None,
    reason: str | None = None,
    assigned_name: str | None = None,
    agent_id: str | None = None,
    message_team_name: str | None = None,
    plan_file: str | None = None,
    summary: str | None = None,
    plan: str | None = None,
    last_task: str | None = None,
    status: str | None = None,
    update_kind: str | None = None,
    blocker: str | None = None,
    final_delivery: str | None = None,
    artifact_files: list[str] | None = None,
    next_action: str | None = None,
    maker_agent: str | None = None,
    validation_claim: str | None = None,
    validation_evidence: list[str] | None = None,
    validation_verdict: str | None = None,
    validation_follow_up: str | None = None,
) -> dict:
    """Send a message to a team member inbox."""
    return to_payload(
        team_mailbox(team_name).send(
            from_agent=from_agent,
            to=to,
            content=content,
            msg_type=coerce_enum(MessageType, msg_type) or MessageType.message,
            request_id=request_id,
            key=key,
            proposed_name=proposed_name,
            capabilities=capabilities,
            feedback=feedback,
            reason=reason,
            assigned_name=assigned_name,
            agent_id=agent_id,
            team_name=message_team_name,
            plan_file=plan_file,
            summary=summary,
            plan=plan,
            last_task=last_task,
            status=status,
            update_kind=update_kind,
            blocker=blocker,
            final_delivery=final_delivery,
            artifact_files=artifact_files,
            next_action=next_action,
            maker_agent=maker_agent,
            validation_claim=validation_claim,
            validation_evidence=validation_evidence,
            validation_verdict=validation_verdict,
            validation_follow_up=validation_follow_up,
        )
    )


def mailbox_room_update(
    team_name: str,
    from_agent: str,
    to: str,
    content: str | None = None,
    summary: str | None = None,
    status: str | None = None,
    blocker: str | None = None,
    final_delivery: str | None = None,
    artifact_files: list[str] | None = None,
    next_action: str | None = None,
    update_kind: str | None = None,
    request_id: str | None = None,
    key: str | None = None,
) -> dict:
    """Send a structured room update using the existing mailbox transport."""
    return to_payload(
        team_mailbox(team_name).send_room_update(
            from_agent=from_agent,
            to=to,
            content=content,
            summary=summary,
            status=status,
            blocker=blocker,
            final_delivery=final_delivery,
            artifact_files=artifact_files,
            next_action=next_action,
            update_kind=update_kind,
            request_id=request_id,
            key=key,
        )
    )


def mailbox_validation_result(
    team_name: str,
    from_agent: str,
    to: str,
    maker_agent: str,
    claim: str,
    evidence: list[str],
    verdict: str,
    follow_up: str | None = None,
    content: str | None = None,
    summary: str | None = None,
    artifact_files: list[str] | None = None,
    request_id: str | None = None,
    key: str | None = None,
) -> dict:
    """Send a structured independent validation result via the mailbox."""
    return to_payload(
        team_mailbox(team_name).send_validation_result(
            from_agent=from_agent,
            to=to,
            maker_agent=maker_agent,
            claim=claim,
            evidence=evidence,
            verdict=verdict,
            follow_up=follow_up,
            content=content,
            summary=summary,
            artifact_files=artifact_files,
            request_id=request_id,
            key=key,
        )
    )


def mailbox_broadcast(
    team_name: str,
    from_agent: str,
    content: str,
    msg_type: str | None = None,
    key: str | None = None,
    exclude: list[str] | None = None,
) -> list[dict]:
    """Broadcast a message to team inboxes."""
    return to_payload(
        team_mailbox(team_name).broadcast(
            from_agent=from_agent,
            content=content,
            msg_type=coerce_enum(MessageType, msg_type) or MessageType.broadcast,
            key=key,
            exclude=exclude,
        )
    )


def mailbox_receive(team_name: str, agent_name: str, limit: int = 10) -> list[dict]:
    """Receive and consume pending inbox messages."""
    return to_payload(team_mailbox(team_name).receive(agent_name, limit=limit))


def mailbox_peek(team_name: str, agent_name: str) -> list[dict]:
    """Preview pending inbox messages without consuming them."""
    return to_payload(team_mailbox(team_name).peek(agent_name))


def mailbox_peek_count(team_name: str, agent_name: str) -> dict:
    """Get the number of pending inbox messages."""
    return {"agentName": agent_name, "count": team_mailbox(team_name).peek_count(agent_name)}
