"""Team manager for creating and managing teams."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from clawteam.team.models import TeamConfig, TeamMember, get_data_dir
from clawteam.team.plan import referenced_legacy_plan_paths, team_plans_path
from clawteam.fsutil import replace_file


def _teams_root() -> Path:
    p = get_data_dir() / "teams"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _team_dir(team_name: str) -> Path:
    return _teams_root() / team_name


def _config_path(team_name: str) -> Path:
    return _team_dir(team_name) / "config.json"


def _load_config(team_name: str) -> TeamConfig | None:
    path = _config_path(team_name)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return TeamConfig.model_validate(data)
    except (json.JSONDecodeError, Exception):
        return None


def _save_config(config: TeamConfig) -> None:
    path = _config_path(config.name)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(
        config.model_dump_json(indent=2, by_alias=True), encoding="utf-8"
    )
    replace_file(tmp, path)


class TeamManager:
    """Manages team lifecycle operations."""

    @staticmethod
    def get_member(
        team_name: str,
        member_name: str,
        user: str = "",
    ) -> TeamMember | None:
        """Return a member by logical name, optionally scoped by user."""
        config = _load_config(team_name)
        if not config:
            return None
        if user:
            for member in config.members:
                if member.name == member_name and member.user == user:
                    return member
        matches = [member for member in config.members if member.name == member_name]
        if len(matches) == 1:
            return matches[0]
        return None

    @staticmethod
    def create_team(
        name: str,
        leader_name: str,
        leader_id: str,
        description: str = "",
        user: str = "",
        leader_agent_type: str = "leader",
    ) -> TeamConfig:
        if _config_path(name).exists():
            raise ValueError(f"Team '{name}' already exists")

        leader = TeamMember(
            name=leader_name,
            user=user,
            agent_id=leader_id,
            agent_type=leader_agent_type,
        )
        config = TeamConfig(
            name=name,
            description=description,
            lead_agent_id=leader_id,
            members=[leader],
        )
        _save_config(config)
        # Create inboxes dir and leader inbox
        inbox_name = f"{user}_{leader_name}" if user else leader_name
        inbox = _team_dir(name) / "inboxes" / inbox_name
        inbox.mkdir(parents=True, exist_ok=True)
        # Create tasks dir
        tasks_dir = get_data_dir() / "tasks" / name
        tasks_dir.mkdir(parents=True, exist_ok=True)
        return config

    @staticmethod
    def discover_teams() -> list[dict]:
        root = _teams_root()
        teams = []
        if not root.exists():
            return teams
        for d in sorted(root.iterdir()):
            if d.is_dir() and (d / "config.json").exists():
                config = _load_config(d.name)
                if config:
                    teams.append({
                        "name": config.name,
                        "description": config.description,
                        "leadAgentId": config.lead_agent_id,
                        "memberCount": len(config.members),
                    })
        return teams

    @staticmethod
    def get_team(name: str) -> TeamConfig | None:
        return _load_config(name)

    @staticmethod
    def add_member(
        team_name: str,
        member_name: str,
        agent_id: str,
        agent_type: str = "general-purpose",
        user: str = "",
    ) -> TeamMember:
        config = _load_config(team_name)
        if not config:
            raise ValueError(f"Team '{team_name}' not found")
        for m in config.members:
            if m.name == member_name and m.user == user:
                raise ValueError(f"Agent '{member_name}' (user={user or '(none)'}) already in team")
        member = TeamMember(
            name=member_name,
            user=user,
            agent_id=agent_id,
            agent_type=agent_type,
        )
        config.members.append(member)
        _save_config(config)
        inbox_name = f"{user}_{member_name}" if user else member_name
        inbox = _team_dir(team_name) / "inboxes" / inbox_name
        inbox.mkdir(parents=True, exist_ok=True)
        return member

    @staticmethod
    def remove_member(team_name: str, member_name: str) -> bool:
        config = _load_config(team_name)
        if not config:
            return False
        before = len(config.members)
        config.members = [m for m in config.members if m.name != member_name]
        if len(config.members) < before:
            _save_config(config)
            return True
        return False

    @staticmethod
    def get_leader_name(team_name: str) -> str | None:
        config = _load_config(team_name)
        if not config:
            return None
        for m in config.members:
            if m.agent_id == config.lead_agent_id:
                return m.name
        return config.members[0].name if config.members else None

    @staticmethod
    def cleanup(team_name: str) -> bool:
        # Best-effort cleanup of git workspaces before removing dirs
        try:
            from clawteam.workspace import get_workspace_manager
            ws_mgr = get_workspace_manager()
            if ws_mgr:
                ws_mgr.cleanup_team(team_name)
        except Exception:
            pass

        legacy_plan_paths = referenced_legacy_plan_paths(team_name)
        team_dir = _team_dir(team_name)
        tasks_dir = get_data_dir() / "tasks" / team_name
        costs_dir = get_data_dir() / "costs" / team_name
        sessions_dir = get_data_dir() / "sessions" / team_name
        plans_dir = team_plans_path(team_name)
        cleaned = False
        for d in (team_dir, tasks_dir, costs_dir, sessions_dir, plans_dir):
            if d.exists():
                shutil.rmtree(d)
                cleaned = True
        for path in legacy_plan_paths:
            try:
                if path.exists():
                    path.unlink()
                    cleaned = True
            except OSError:
                pass
        return cleaned

    @staticmethod
    def list_members(team_name: str) -> list[TeamMember]:
        config = _load_config(team_name)
        return config.members if config else []

    @staticmethod
    def inbox_name_for(member: TeamMember) -> str:
        """Return the inbox directory name for a member."""
        return f"{member.user}_{member.name}" if member.user else member.name

    @staticmethod
    def resolve_inbox(team_name: str, recipient: str, user: str = "") -> str:
        """Resolve a logical agent name to its on-disk inbox directory."""
        member = TeamManager.get_member(team_name, recipient, user=user)
        if member:
            return TeamManager.inbox_name_for(member)
        return recipient

    @staticmethod
    def get_leader_inbox(team_name: str) -> str | None:
        """Return the inbox name for the team leader."""
        config = _load_config(team_name)
        if not config:
            return None
        for m in config.members:
            if m.agent_id == config.lead_agent_id:
                return f"{m.user}_{m.name}" if m.user else m.name
        if config.members:
            m = config.members[0]
            return f"{m.user}_{m.name}" if m.user else m.name
        return None
