"""Board MCP tools."""

from __future__ import annotations

from clawteam.board.collector import BoardCollector
from clawteam.mcp.helpers import to_payload


def board_overview() -> list[dict]:
    """List lightweight board summaries for all teams."""
    return to_payload(BoardCollector().collect_overview())


def board_team(team_name: str) -> dict:
    """Get the full board view for one team."""
    return to_payload(BoardCollector().collect_team(team_name))
