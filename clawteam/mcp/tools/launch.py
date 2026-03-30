"""Launch MCP tools."""

from __future__ import annotations

from clawteam.mcp.helpers import to_payload
from clawteam.team.launch import launch_team_from_template


def team_launch(
    template_name: str,
    goal: str = "",
    plan_file: str | None = None,
    skill: list[str] | None = None,
    backend: str | None = None,
    profile: str | None = None,
    team_name: str | None = None,
    workspace: bool = False,
    repo: str | None = None,
    command_override: list[str] | None = None,
    user: str | None = None,
) -> dict:
    """Launch a template-backed team with the same flow as `clawteam launch`."""
    return to_payload(
        launch_team_from_template(
            template_name,
            goal=goal,
            plan_file=plan_file,
            skill=skill,
            backend=backend,
            profile=profile,
            team_name=team_name,
            workspace=workspace,
            repo=repo,
            command_override=command_override,
            user=user,
        )
    )
