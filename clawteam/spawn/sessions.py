"""Session persistence for agent resume."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from clawteam.paths import ensure_within_root, validate_identifier
from clawteam.team.models import get_data_dir


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SessionState(BaseModel):
    """Persisted session state for an agent."""

    model_config = {"populate_by_name": True}

    agent_name: str = Field(alias="agentName")
    team_name: str = Field(alias="teamName")
    session_id: str = Field(default="", alias="sessionId")
    last_task_id: str = Field(default="", alias="lastTaskId")
    saved_at: str = Field(default_factory=_now_iso, alias="savedAt")
    state: dict[str, Any] = Field(default_factory=dict)


def _sessions_root(team_name: str) -> Path:
    d = ensure_within_root(get_data_dir() / "sessions", validate_identifier(team_name, "team name"))
    d.mkdir(parents=True, exist_ok=True)
    return d


class SessionStore:
    """File-based session store.

    Each agent's session is stored at:
    ``{data_dir}/sessions/{team}/{agent}.json``
    """

    def __init__(self, team_name: str):
        validate_identifier(team_name, "team name")
        self.team_name = team_name

    def save(
        self,
        agent_name: str,
        session_id: str = "",
        last_task_id: str = "",
        state: dict[str, Any] | None = None,
    ) -> SessionState:
        validate_identifier(agent_name, "agent name")
        session = SessionState(
            agent_name=agent_name,
            team_name=self.team_name,
            session_id=session_id,
            last_task_id=last_task_id,
            state=state or {},
        )
        path = _sessions_root(self.team_name) / f"{agent_name}.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(
            session.model_dump_json(indent=2, by_alias=True), encoding="utf-8"
        )
        import os
        os.replace(str(tmp), str(path))
        return session

    def load(self, agent_name: str) -> SessionState | None:
        validate_identifier(agent_name, "agent name")
        path = _sessions_root(self.team_name) / f"{agent_name}.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return SessionState.model_validate(data)
        except Exception:
            return None

    def clear(self, agent_name: str) -> bool:
        validate_identifier(agent_name, "agent name")
        path = _sessions_root(self.team_name) / f"{agent_name}.json"
        if path.exists():
            path.unlink()
            return True
        return False

    def list_sessions(self) -> list[SessionState]:
        root = _sessions_root(self.team_name)
        sessions = []
        for f in sorted(root.glob("*.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                sessions.append(SessionState.model_validate(data))
            except Exception:
                continue
        return sessions
