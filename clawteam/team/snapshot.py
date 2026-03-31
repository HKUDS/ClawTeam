"""Team state snapshots for checkpoint/restore."""

from __future__ import annotations

import sys

if sys.platform == "win32":
    import msvcrt
else:
    import fcntl

import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from clawteam.fileutil import atomic_write_text
from clawteam.paths import ensure_within_root, validate_identifier
from clawteam.team.models import get_data_dir


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _snapshots_root(team_name: str) -> Path:
    d = ensure_within_root(get_data_dir() / "snapshots", validate_identifier(team_name, "team name"))
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


def _read_inbox_messages(directory: Path) -> list[dict]:
    if not directory.exists():
        return []
    items = []
    for f in sorted(directory.glob("msg-*.json")):
        try:
            items.append(json.loads(f.read_text("utf-8")))
        except Exception:
            continue
    for f in sorted(directory.glob("msg-*.consumed")):
        try:
            handle = f.open("rb")
        except Exception:
            continue
        try:
            try:
                # Snapshot capture only needs a best-effort view of recovered
                # `.consumed` files. This Unix-only `flock()` probe avoids
                # active claims, but the result is advisory because the lock is
                # released before the caller resumes.
                if sys.platform == "win32":
                    pos = handle.tell()
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                    handle.seek(pos)
                else:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                continue
            try:
                items.append(json.loads(handle.read().decode("utf-8")))
            except Exception:
                continue
        finally:
            handle.close()
    return items


def _safe_snapshot_tag(tag: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", tag).strip("-._")
    return safe or "snapshot"


class SnapshotManager:
    """Create and restore full team state snapshots.

    Bundles config, tasks, events, sessions, costs, and pending inbox
    messages into a single JSON file under ``{data_dir}/snapshots/{team}/``.
    """

    def __init__(self, team_name: str):
        validate_identifier(team_name, "team name")
        self.team_name = team_name

    def _team_dir(self) -> Path:
        return ensure_within_root(get_data_dir() / "teams", validate_identifier(self.team_name, "team name"))

    def create(self, tag: str = "") -> SnapshotMeta:
        """Capture current team state."""
        data_dir = get_data_dir()
        team_dir = self._team_dir()

        config_path = team_dir / "config.json"
        if not config_path.exists():
            raise ValueError(f"Team '{self.team_name}' not found")
        config = json.loads(config_path.read_text("utf-8"))

        tasks = _read_json_dir(
            ensure_within_root(data_dir / "tasks", self.team_name),
            "task-*.json",
        )
        events = _read_json_dir(team_dir / "events", "evt-*.json")
        sessions = _read_json_dir(
            ensure_within_root(data_dir / "sessions", self.team_name),
            "*.json",
        )
        costs = _read_json_dir(
            ensure_within_root(data_dir / "costs", self.team_name),
            "cost-*.json",
        )

        # pending inbox messages (not yet consumed)
        inboxes: dict[str, list[dict]] = {}
        inbox_root = team_dir / "inboxes"
        if inbox_root.exists():
            for agent_dir in sorted(inbox_root.iterdir()):
                if agent_dir.is_dir():
                    msgs = _read_inbox_messages(agent_dir)
                    if msgs:
                        inboxes[agent_dir.name] = msgs

        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        snap_id = f"{ts}-{_safe_snapshot_tag(tag)}" if tag else ts

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
        atomic_write_text(path, json.dumps(bundle, indent=2, ensure_ascii=False))
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

        # Restore should replace current team state for this snapshot domain,
        # not overlay on top of newer tasks/events/messages.
        for path in (
            ensure_within_root(data_dir / "tasks", self.team_name),
            team_dir / "events",
            ensure_within_root(data_dir / "sessions", self.team_name),
            ensure_within_root(data_dir / "costs", self.team_name),
            team_dir / "inboxes",
        ):
            if path.exists():
                shutil.rmtree(path)

        # config
        if bundle.get("config"):
            team_dir.mkdir(parents=True, exist_ok=True)
            _atomic_write(team_dir / "config.json", bundle["config"])

        # tasks
        tasks_dir = ensure_within_root(data_dir / "tasks", self.team_name)
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
        sessions_dir = ensure_within_root(data_dir / "sessions", self.team_name)
        sessions_dir.mkdir(parents=True, exist_ok=True)
        for sess in bundle.get("sessions", []):
            name = sess.get("agentName", sess.get("agent_name", "unknown"))
            _atomic_write(sessions_dir / f"{name}.json", sess)

        # costs
        costs_dir = ensure_within_root(data_dir / "costs", self.team_name)
        costs_dir.mkdir(parents=True, exist_ok=True)
        for cost in bundle.get("costs", []):
            cid = cost.get("id", "unknown")
            ts = cost.get("reportedAt", "x").replace(":", "-").replace("+", "p")
            _atomic_write(costs_dir / f"cost-{ts}-{cid}.json", cost)

        # inbox messages
        inbox_root = team_dir / "inboxes"
        for agent_name, messages in bundle.get("inboxes", {}).items():
            agent_inbox = ensure_within_root(
                inbox_root,
                validate_identifier(agent_name, "inbox name"),
            )
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
    atomic_write_text(path, json.dumps(data, indent=2, ensure_ascii=False))
