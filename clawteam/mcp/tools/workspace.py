"""Workspace MCP tools."""

from __future__ import annotations

import json

from clawteam.mcp.helpers import to_payload
from clawteam.workspace.context import agent_diff, agent_summary, cross_branch_log, file_owners


def workspace_agent_diff(team_name: str, agent_name: str, repo: str | None = None) -> dict:
    """Get git diff statistics for one agent branch."""
    return to_payload(agent_diff(team_name, agent_name, repo=repo))


def workspace_file_owners(team_name: str, repo: str | None = None) -> dict:
    """List modified files grouped by agent owners."""
    return to_payload(file_owners(team_name, repo=repo))


def workspace_cross_branch_log(team_name: str, limit: int = 50, repo: str | None = None) -> str:
    """Get recent cross-branch commit activity as JSON text."""
    entries = to_payload(cross_branch_log(team_name, limit=limit, repo=repo))
    return json.dumps(entries, indent=2)


def workspace_agent_summary(team_name: str, agent_name: str, repo: str | None = None) -> dict:
    """Get a human-readable git activity summary for one agent."""
    return {"agentName": agent_name, "summary": agent_summary(team_name, agent_name, repo=repo)}
