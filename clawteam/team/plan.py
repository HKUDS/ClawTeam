"""Plan approval workflow for team agents."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from clawteam.paths import ensure_within_root, validate_identifier
from clawteam.team.mailbox import MailboxManager
from clawteam.team.models import MessageType, get_data_dir


def _plans_root() -> Path:
    d = _plans_root_path()
    d.mkdir(parents=True, exist_ok=True)
    return d


def _plans_root_path() -> Path:
    return get_data_dir() / "plans"


def _team_plans_root(team_name: str) -> Path:
    d = team_plans_path(team_name)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _plan_filename(agent_name: str, plan_id: str) -> str:
    return (
        f"{validate_identifier(agent_name, 'agent name')}"
        f"-{validate_identifier(plan_id, 'plan id')}.md"
    )


def _team_plan_path(team_name: str, agent_name: str, plan_id: str) -> Path:
    return _team_plans_root(team_name) / _plan_filename(agent_name, plan_id)


def _legacy_plan_path(agent_name: str, plan_id: str) -> Path:
    return _plans_root_path() / _plan_filename(agent_name, plan_id)


def _iter_plan_paths(team_name: str, agent_name: str, plan_id: str) -> list[Path]:
    paths = []
    if team_name:
        paths.append(_team_plan_path(team_name, agent_name, plan_id))
    else:
        filename = _plan_filename(agent_name, plan_id)
        plans_root = _plans_root_path()
        if plans_root.exists():
            for team_dir in sorted(plans_root.iterdir()):
                if team_dir.is_dir():
                    paths.append(team_dir / filename)
    paths.append(_legacy_plan_path(agent_name, plan_id))
    return paths


def team_plans_path(team_name: str) -> Path:
    """Return the team-scoped plan directory path without creating it."""
    return ensure_within_root(_plans_root_path(), validate_identifier(team_name, "team name"))


def referenced_legacy_plan_paths(team_name: str) -> set[Path]:
    """Return legacy flat plan files referenced by this team's event log."""
    team_events_dir = ensure_within_root(
        get_data_dir() / "teams",
        validate_identifier(team_name, "team name"),
        "events",
    )
    plans_root = _plans_root_path()
    paths: set[Path] = set()
    if not team_events_dir.exists():
        return paths

    for event_file in team_events_dir.glob("evt-*.json"):
        try:
            data = json.loads(event_file.read_text(encoding="utf-8"))
        except Exception:
            continue

        if data.get("type") != MessageType.plan_approval_request.value:
            continue

        from_agent = data.get("from")
        request_id = data.get("requestId")
        if from_agent and request_id:
            paths.add(_legacy_plan_path(from_agent, request_id))

        plan_file = data.get("planFile")
        if not plan_file:
            continue

        plan_path = Path(plan_file).expanduser()
        if plan_path.parent == plans_root:
            paths.add(plan_path)

    return paths


class PlanManager:
    """Manages plan submission and approval between team members and leader."""

    def __init__(self, team_name: str, mailbox: MailboxManager):
        self.team_name = team_name
        self.mailbox = mailbox

    def submit_plan(
        self,
        agent_name: str,
        leader_name: str,
        plan_content: str,
        summary: str = "",
    ) -> str:
        validate_identifier(agent_name, "agent name")
        validate_identifier(leader_name, "leader name")
        plan_id = uuid.uuid4().hex[:12]
        plan_path = _team_plan_path(self.team_name, agent_name, plan_id)
        plan_path.write_text(plan_content, encoding="utf-8")

        self.mailbox.send(
            from_agent=agent_name,
            to=leader_name,
            msg_type=MessageType.plan_approval_request,
            request_id=plan_id,
            plan_file=str(plan_path),
            summary=summary or plan_content[:200],
            plan=plan_content,
        )
        return plan_id

    def approve_plan(
        self,
        leader_name: str,
        plan_id: str,
        agent_name: str,
        feedback: str = "",
    ) -> None:
        self.mailbox.send(
            from_agent=leader_name,
            to=agent_name,
            msg_type=MessageType.plan_approved,
            request_id=plan_id,
            feedback=feedback or None,
        )

    def reject_plan(
        self,
        leader_name: str,
        plan_id: str,
        agent_name: str,
        feedback: str = "",
    ) -> None:
        self.mailbox.send(
            from_agent=leader_name,
            to=agent_name,
            msg_type=MessageType.plan_rejected,
            request_id=plan_id,
            feedback=feedback or None,
        )

    @staticmethod
    def get_plan(plan_id: str, agent_name: str, team_name: str = "") -> str | None:
        validate_identifier(plan_id, "plan id")
        validate_identifier(agent_name, "agent name")
        validate_identifier(team_name, "team name", allow_empty=True)
        for plan_path in _iter_plan_paths(team_name, agent_name, plan_id):
            if plan_path.exists():
                return plan_path.read_text(encoding="utf-8")
        return None
