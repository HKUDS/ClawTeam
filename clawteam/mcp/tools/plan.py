"""Plan MCP tools."""

from __future__ import annotations

from clawteam.mcp.helpers import plan_manager


def plan_submit(
    team_name: str,
    agent_name: str,
    leader_name: str,
    plan_content: str,
    summary: str = "",
) -> dict:
    """Submit a plan for leader review."""
    plan_id = plan_manager(team_name).submit_plan(
        agent_name=agent_name,
        leader_name=leader_name,
        plan_content=plan_content,
        summary=summary,
    )
    return {"planId": plan_id}


def plan_get(team_name: str, plan_id: str, agent_name: str) -> dict:
    """Get the stored content for a submitted plan."""
    content = plan_manager(team_name).get_plan(plan_id, agent_name, team_name)
    return {"planId": plan_id, "agentName": agent_name, "content": content}


def plan_approve(
    team_name: str,
    leader_name: str,
    plan_id: str,
    agent_name: str,
    feedback: str = "",
) -> dict:
    """Approve a submitted plan."""
    plan_manager(team_name).approve_plan(leader_name, plan_id, agent_name, feedback=feedback)
    return {"ok": True, "planId": plan_id}


def plan_reject(
    team_name: str,
    leader_name: str,
    plan_id: str,
    agent_name: str,
    feedback: str = "",
) -> dict:
    """Reject a submitted plan."""
    plan_manager(team_name).reject_plan(leader_name, plan_id, agent_name, feedback=feedback)
    return {"ok": True, "planId": plan_id}
