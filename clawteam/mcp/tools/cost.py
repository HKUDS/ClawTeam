"""Cost MCP tools."""

from __future__ import annotations

from clawteam.mcp.helpers import cost_store, to_payload


def cost_summary(team_name: str) -> dict:
    """Get aggregated token and cost totals for a team."""
    return to_payload(cost_store(team_name).summary())

