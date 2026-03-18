"""File-based transport: messages stored as JSON files in inbox directories."""

from __future__ import annotations

import time
import uuid
from pathlib import Path

from clawteam.team.models import get_data_dir
from clawteam.transport.base import Transport


def _teams_root() -> Path:
    return get_data_dir() / "teams"


def _inbox_dir(team_name: str, agent_name: str) -> Path:
    d = _teams_root() / team_name / "inboxes" / agent_name
    d.mkdir(parents=True, exist_ok=True)
    return d


class FileTransport(Transport):
    """Transport backed by the local filesystem.

    Each message is a file: ``{data_dir}/teams/{team}/inboxes/{agent}/msg-{ts}-{uid}.json``
    Atomic writes (tmp + rename) prevent partial reads.
    """

    def __init__(self, team_name: str):
        self.team_name = team_name

    def deliver(self, recipient: str, data: bytes) -> None:
        inbox = _inbox_dir(self.team_name, recipient)
        ts = int(time.time() * 1000)
        uid = uuid.uuid4().hex[:8]
        filename = f"msg-{ts}-{uid}.json"
        tmp = inbox / f".tmp-{uid}.json"
        target = inbox / filename
        try:
            tmp.write_bytes(data)
            tmp.replace(target)
        except Exception:
            tmp.unlink(missing_ok=True)
            raise

    def fetch(self, agent_name: str, limit: int = 10, consume: bool = True) -> list[bytes]:
        inbox = _inbox_dir(self.team_name, agent_name)
        files = sorted(inbox.glob("msg-*.json"))
        messages: list[bytes] = []
        for f in files[:limit]:
            try:
                if consume:
                    # Atomically rename to a `.consumed` marker before reading so
                    # that concurrent fetchers cannot both process the same message.
                    consumed = f.with_suffix(".consumed")
                    try:
                        f.rename(consumed)
                    except OSError:
                        # Another process already claimed this message; skip it.
                        continue
                    try:
                        raw = consumed.read_bytes()
                        messages.append(raw)
                    finally:
                        consumed.unlink(missing_ok=True)
                else:
                    raw = f.read_bytes()
                    messages.append(raw)
            except Exception:
                continue
        return messages

    def count(self, agent_name: str) -> int:
        inbox = _inbox_dir(self.team_name, agent_name)
        return len(list(inbox.glob("msg-*.json")))

    def list_recipients(self) -> list[str]:
        inboxes_dir = _teams_root() / self.team_name / "inboxes"
        if not inboxes_dir.exists():
            return []
        return [d.name for d in inboxes_dir.iterdir() if d.is_dir()]
