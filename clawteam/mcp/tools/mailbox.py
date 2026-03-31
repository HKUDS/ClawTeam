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

