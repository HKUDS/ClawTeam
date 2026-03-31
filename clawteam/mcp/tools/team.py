"""Team MCP tools."""

from __future__ import annotations

from clawteam.mcp.helpers import require_team, to_payload
from clawteam.team.manager import TeamManager


def team_list() -> list[dict]:
    """List team summaries for overview views."""
    return to_payload(TeamManager.discover_teams())


def team_get(team_name: str) -> dict:
    """Get the full configuration for one team."""
    return to_payload(require_team(team_name))


def team_members_list(team_name: str) -> list[dict]:
    """List the members registered in one team."""
    require_team(team_name)
    return to_payload(TeamManager.list_members(team_name))


def team_create(
    team_name: str,
    leader_name: str,
    leader_id: str,
    description: str = "",
    user: str = "",
    leader_agent_type: str = "leader",
) -> dict:
    """Create a team with its leader, inbox, and task workspace."""
    return to_payload(
        TeamManager.create_team(
            name=team_name,
            leader_name=leader_name,
            leader_id=leader_id,
            description=description,
            user=user,
            leader_agent_type=leader_agent_type,
        )
    )


def team_member_add(
    team_name: str,
    member_name: str,
    agent_id: str,
    agent_type: str = "general-purpose",
    user: str = "",
) -> dict:
    """Add a member to a team and provision its inbox."""
    return to_payload(
        TeamManager.add_member(
            team_name=team_name,
            member_name=member_name,
            agent_id=agent_id,
            agent_type=agent_type,
            user=user,
        )
    )
