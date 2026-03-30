"""Shared team launch flow used by CLI and MCP surfaces."""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any

from clawteam.team.manager import TeamManager
from clawteam.team.plan import stage_launch_plan
from clawteam.team.tasks import TaskStore
from clawteam.templates import TemplateDef


def launch_team_from_template(
    template_name: str,
    *,
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
) -> dict[str, Any]:
    """Launch a team from a template and return the machine-readable result."""
    from clawteam.config import get_effective
    from clawteam.spawn import get_backend
    from clawteam.spawn.profiles import apply_profile, load_profile
    from clawteam.spawn.skills import append_guidance_to_prompt, load_skill_bundle, split_guidance_for_command
    from clawteam.spawn.prompt import build_agent_prompt
    from clawteam.templates import load_template, render_task

    tmpl: TemplateDef = load_template(template_name)
    team_user = os.environ.get("CLAWTEAM_USER", "") if user is None else user
    resolved_team_name = team_name or f"{tmpl.name}-{uuid.uuid4().hex[:6]}"
    backend_name = backend or tmpl.backend
    default_command = list(command_override) if command_override is not None else list(tmpl.command)

    source_plan_path: Path | None = None
    if plan_file:
        source_plan_path = Path(plan_file).expanduser()
        if not source_plan_path.is_file():
            raise FileNotFoundError(f"Plan file not found: {source_plan_path}")

    leader_id = uuid.uuid4().hex[:12]
    TeamManager.create_team(
        name=resolved_team_name,
        leader_name=tmpl.leader.name,
        leader_id=leader_id,
        description=tmpl.description,
        user=team_user,
    )

    agent_ids: dict[str, str] = {tmpl.leader.name: leader_id}
    for agent in tmpl.agents:
        agent_id = uuid.uuid4().hex[:12]
        agent_ids[agent.name] = agent_id
        TeamManager.add_member(
            team_name=resolved_team_name,
            member_name=agent.name,
            agent_id=agent_id,
            agent_type=agent.type,
            user=team_user,
        )

    task_store = TaskStore(resolved_team_name)
    for task_def in tmpl.tasks:
        task_store.create(
            subject=task_def.subject,
            description=task_def.description,
            owner=task_def.owner,
        )

    staged_plan_path: Path | None = None
    if source_plan_path:
        staged_plan_path = stage_launch_plan(resolved_team_name, source_plan_path)

    backend_impl = get_backend(backend_name)

    skip_permissions_value, _ = get_effective("skip_permissions")
    skip_permissions = str(skip_permissions_value).lower() not in ("false", "0", "no", "")

    workspace_manager = None
    if workspace:
        from clawteam.workspace import get_workspace_manager

        workspace_manager = get_workspace_manager(repo)
        if workspace_manager is None:
            raise ValueError("Not in a git repository. Use --repo or cd into a repo.")

    resolved_profile = load_profile(profile) if profile else None
    skill_guidance, missing_skills = load_skill_bundle(skill)

    all_agents = [tmpl.leader] + list(tmpl.agents)
    spawned: list[dict[str, str]] = []
    for agent in all_agents:
        agent_id = agent_ids[agent.name]
        agent_command = list(agent.command) if agent.command else list(default_command)
        agent_env: dict[str, str] = {}
        if resolved_profile:
            command_seed = list(agent_command) if (agent.command or command_override) else []
            agent_command, agent_env, _ = apply_profile(
                resolved_profile,
                command=command_seed,
            )

        rendered_task = render_task(
            agent.task,
            goal=goal,
            team_name=resolved_team_name,
            agent_name=agent.name,
        )

        workspace_dir = None
        workspace_branch = ""
        if workspace_manager:
            workspace_info = workspace_manager.create_workspace(
                team_name=resolved_team_name,
                agent_name=agent.name,
                agent_id=agent_id,
            )
            workspace_dir = workspace_info.worktree_path
            workspace_branch = workspace_info.branch_name

        prompt = build_agent_prompt(
            agent_name=agent.name,
            agent_id=agent_id,
            agent_type=agent.type,
            team_name=resolved_team_name,
            leader_name=tmpl.leader.name,
            task=rendered_task,
            user=team_user,
            workspace_dir=workspace_dir or "",
            workspace_branch=workspace_branch,
            isolated_workspace=bool(workspace_dir),
            plan_artifact_path=str(staged_plan_path or ""),
        )
        system_prompt, prompt_guidance = split_guidance_for_command(agent_command, skill_guidance)
        if prompt_guidance:
            prompt = append_guidance_to_prompt(prompt, prompt_guidance)

        result = backend_impl.spawn(
            command=agent_command,
            agent_name=agent.name,
            agent_id=agent_id,
            agent_type=agent.type,
            team_name=resolved_team_name,
            prompt=prompt,
            env=agent_env or None,
            cwd=workspace_dir,
            skip_permissions=skip_permissions,
            system_prompt=system_prompt,
        )
        spawned.append(
            {
                "name": agent.name,
                "id": agent_id,
                "type": agent.type,
                "result": result,
            }
        )

    payload: dict[str, Any] = {
        "status": "launched",
        "team": resolved_team_name,
        "template": tmpl.name,
        "backend": backend_name,
        "agents": [{"name": item["name"], "id": item["id"], "type": item["type"]} for item in spawned],
    }
    if staged_plan_path:
        payload["planFile"] = str(staged_plan_path)
    if skill:
        payload["skills"] = list(skill)
    if missing_skills:
        payload["missingSkills"] = missing_skills
    return payload
