"""Team state snapshots for checkpoint/restore."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from clawteam.team.models import get_data_dir


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _snapshots_root(team_name: str) -> Path:
    d = get_data_dir() / "snapshots" / team_name
    d.mkdir(parents=True, exist_ok=True)
    return d


class SnapshotMeta(BaseModel):
    """Metadata header stored inside each snapshot bundle."""

    model_config = {"populate_by_name": True}

    id: str
    team_name: str = Field(alias="teamName")
    tag: str = ""
    created_at: str = Field(default_factory=_now_iso, alias="createdAt")
    member_count: int = Field(default=0, alias="memberCount")
    task_count: int = Field(default=0, alias="taskCount")
    event_count: int = Field(default=0, alias="eventCount")
    session_count: int = Field(default=0, alias="sessionCount")
    cost_event_count: int = Field(default=0, alias="costEventCount")


def _read_json_dir(directory: Path, pattern: str) -> list[dict]:
    if not directory.exists():
        return []
    items = []
    for f in sorted(directory.glob(pattern)):
        try:
            items.append(json.loads(f.read_text("utf-8")))
        except Exception:
            continue
    return items


class SnapshotManager:
    """Create and restore full team state snapshots.

    Bundles config, tasks, events, sessions, costs, and pending inbox
    messages into a single JSON file under ``{data_dir}/snapshots/{team}/``.
    """

    def __init__(self, team_name: str):
        self.team_name = team_name

    def _team_dir(self) -> Path:
        return get_data_dir() / "teams" / self.team_name

    def create(self, tag: str = "") -> SnapshotMeta:
        """Capture current team state."""
        data_dir = get_data_dir()
        team_dir = self._team_dir()

        config_path = team_dir / "config.json"
        if not config_path.exists():
            raise ValueError(f"Team '{self.team_name}' not found")
        config = json.loads(config_path.read_text("utf-8"))

        tasks = _read_json_dir(data_dir / "tasks" / self.team_name, "task-*.json")
        events = _read_json_dir(team_dir / "events", "evt-*.json")
        sessions = _read_json_dir(data_dir / "sessions" / self.team_name, "*.json")
        costs = _read_json_dir(data_dir / "costs" / self.team_name, "cost-*.json")

        # pending inbox messages (not yet consumed)
        inboxes: dict[str, list[dict]] = {}
        inbox_root = team_dir / "inboxes"
        if inbox_root.exists():
            for agent_dir in sorted(inbox_root.iterdir()):
                if agent_dir.is_dir():
                    msgs = _read_json_dir(agent_dir, "msg-*.json")
                    if msgs:
                        inboxes[agent_dir.name] = msgs

        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        snap_id = f"{ts}-{tag}" if tag else ts

        meta = SnapshotMeta(
            id=snap_id,
            team_name=self.team_name,
            tag=tag,
            member_count=len(config.get("members", [])),
            task_count=len(tasks),
            event_count=len(events),
            session_count=len(sessions),
            cost_event_count=len(costs),
        )

        bundle = {
            "meta": json.loads(meta.model_dump_json(by_alias=True)),
            "config": config,
            "tasks": tasks,
            "events": events,
            "sessions": sessions,
            "costs": costs,
            "inboxes": inboxes,
        }

        path = _snapshots_root(self.team_name) / f"snap-{snap_id}.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(bundle, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        tmp.rename(path)
        return meta

    def list_snapshots(self) -> list[SnapshotMeta]:
        """List available snapshots, newest first."""
        root = _snapshots_root(self.team_name)
        out: list[SnapshotMeta] = []
        for f in sorted(root.glob("snap-*.json"), reverse=True):
            try:
                data = json.loads(f.read_text("utf-8"))
                out.append(SnapshotMeta.model_validate(data["meta"]))
            except Exception:
                continue
        return out

    def load_bundle(self, snapshot_id: str) -> dict[str, Any]:
        """Load a snapshot bundle from disk."""
        path = _snapshots_root(self.team_name) / f"snap-{snapshot_id}.json"
        if not path.exists():
            raise ValueError(f"Snapshot '{snapshot_id}' not found")
        return json.loads(path.read_text("utf-8"))

    def restore(self, snapshot_id: str, dry_run: bool = False) -> dict[str, Any]:
        """Restore team state from a snapshot.

        Returns a summary dict. With dry_run=True nothing is written.
        """
        bundle = self.load_bundle(snapshot_id)

        summary: dict[str, Any] = {
            "snapshot_id": snapshot_id,
            "dry_run": dry_run,
            "config": bool(bundle.get("config")),
            "tasks": len(bundle.get("tasks", [])),
            "events": len(bundle.get("events", [])),
            "sessions": len(bundle.get("sessions", [])),
            "costs": len(bundle.get("costs", [])),
            "inboxes": sum(len(v) for v in bundle.get("inboxes", {}).values()),
        }
        if dry_run:
            return summary

        data_dir = get_data_dir()
        team_dir = self._team_dir()

        # config
        if bundle.get("config"):
            team_dir.mkdir(parents=True, exist_ok=True)
            _atomic_write(team_dir / "config.json", bundle["config"])

        # tasks
        tasks_dir = data_dir / "tasks" / self.team_name
        tasks_dir.mkdir(parents=True, exist_ok=True)
        for task in bundle.get("tasks", []):
            tid = task.get("id", "unknown")
            _atomic_write(tasks_dir / f"task-{tid}.json", task)

        # events -- restored with sequential names to avoid collisions
        events_dir = team_dir / "events"
        events_dir.mkdir(parents=True, exist_ok=True)
        for i, evt in enumerate(bundle.get("events", [])):
            _atomic_write(events_dir / f"evt-restored-{i:06d}.json", evt)

        # sessions
        sessions_dir = data_dir / "sessions" / self.team_name
        sessions_dir.mkdir(parents=True, exist_ok=True)
        for sess in bundle.get("sessions", []):
            name = sess.get("agentName", sess.get("agent_name", "unknown"))
            _atomic_write(sessions_dir / f"{name}.json", sess)

        # costs
        costs_dir = data_dir / "costs" / self.team_name
        costs_dir.mkdir(parents=True, exist_ok=True)
        for cost in bundle.get("costs", []):
            cid = cost.get("id", "unknown")
            ts = cost.get("reportedAt", "x").replace(":", "-").replace("+", "p")
            _atomic_write(costs_dir / f"cost-{ts}-{cid}.json", cost)

        # inbox messages
        inbox_root = team_dir / "inboxes"
        for agent_name, messages in bundle.get("inboxes", {}).items():
            agent_inbox = inbox_root / agent_name
            agent_inbox.mkdir(parents=True, exist_ok=True)
            for j, msg in enumerate(messages):
                _atomic_write(
                    agent_inbox / f"msg-restored-{j:06d}.json", msg
                )

        return summary

    def delete(self, snapshot_id: str) -> bool:
        path = _snapshots_root(self.team_name) / f"snap-{snapshot_id}.json"
        if path.exists():
            path.unlink()
            return True
        return False


def _atomic_write(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.rename(path)
