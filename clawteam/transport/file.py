"""File-based transport: messages stored as JSON files in inbox directories."""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

from clawteam.compat import is_path_locked
from clawteam.team.models import get_data_dir
from clawteam.transport.base import Transport
from clawteam.transport.claimed import ClaimedMessage


def _teams_root() -> Path:
    return get_data_dir() / "teams"


def _inbox_dir(team_name: str, agent_name: str) -> Path:
    d = _teams_root() / team_name / "inboxes" / agent_name
    d.mkdir(parents=True, exist_ok=True)
    return d


def _dead_letter_dir(team_name: str, agent_name: str) -> Path:
    d = _teams_root() / team_name / "dead_letters" / agent_name
    d.mkdir(parents=True, exist_ok=True)
    return d


def _claimable_paths(inbox: Path) -> list[Path]:
    paths = list(inbox.glob("msg-*.json"))
    paths.extend(inbox.glob("msg-*.consumed"))
    return sorted(paths)



class FileTransport(Transport):
    """Transport backed by the local filesystem.

    Each message is a file: ``{data_dir}/teams/{team}/inboxes/{agent}/msg-{ts}-{uid}.json``
    Atomic writes (tmp + rename) prevent partial reads.
    """

    def __init__(self, team_name: str):
        self.team_name = team_name

    def _make_claimed_message(
        self,
        agent_name: str,
        original_path: Path,
        consumed_path: Path,
        file_handle,
        data: bytes,
    ) -> ClaimedMessage:
        def _ack() -> None:
            try:
                file_handle.close()
            finally:
                consumed_path.unlink(missing_ok=True)

        def _quarantine(error: str) -> None:
            try:
                file_handle.close()
            finally:
                self._quarantine_bytes(
                    agent_name,
                    data,
                    error,
                    source_name=original_path.name,
                    consumed_path=consumed_path,
                )

        return ClaimedMessage(data=data, ack=_ack, quarantine=_quarantine)

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

    def claim_messages(self, agent_name: str, limit: int = 10) -> list[ClaimedMessage]:
        inbox = _inbox_dir(self.team_name, agent_name)
        claimed: list[ClaimedMessage] = []
        for path in _claimable_paths(inbox)[:limit]:
            consumed = path
            if path.suffix == ".json":
                consumed = path.with_suffix(".consumed")
                try:
                    path.rename(consumed)
                except OSError:
                    continue
            try:
                file_handle = consumed.open("rb")
            except Exception:
                consumed.unlink(missing_ok=True)
                continue

            if is_path_locked(consumed):
                file_handle.close()
                continue
            try:
                data = file_handle.read()
            except Exception:
                file_handle.close()
                consumed.unlink(missing_ok=True)
                continue
            claimed.append(
                self._make_claimed_message(
                    agent_name=agent_name,
                    original_path=path,
                    consumed_path=consumed,
                    file_handle=file_handle,
                    data=data,
                )
            )
        return claimed

    def _quarantine_bytes(
        self,
        agent_name: str,
        data: bytes,
        error: str,
        source_name: str,
        consumed_path: Path | None = None,
    ) -> None:
        dead_dir = _dead_letter_dir(self.team_name, agent_name)
        raw_path = dead_dir / source_name
        if raw_path.exists():
            raw_path = dead_dir / f"{raw_path.stem}-{uuid.uuid4().hex[:8]}{raw_path.suffix}"

        if consumed_path is not None and consumed_path.exists():
            consumed_path.replace(raw_path)
        else:
            raw_path.write_bytes(data)

        meta_path = raw_path.with_name(f"{raw_path.name}.meta.json")
        meta_path.write_text(
            json.dumps(
                {
                    "team": self.team_name,
                    "agent": agent_name,
                    "sourceName": source_name,
                    "error": error,
                    "quarantinedAtMs": int(time.time() * 1000),
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    def fetch(self, agent_name: str, limit: int = 10, consume: bool = True) -> list[bytes]:
        inbox = _inbox_dir(self.team_name, agent_name)
        if consume:
            messages = []
            for claimed in self.claim_messages(agent_name, limit):
                messages.append(claimed.data)
                claimed.ack()
            return messages

        files = _claimable_paths(inbox)
        messages: list[bytes] = []
        for f in files[:limit]:
            if f.suffix == ".consumed" and is_path_locked(f):
                continue
            try:
                messages.append(f.read_bytes())
            except Exception:
                continue
        return messages

    def count(self, agent_name: str) -> int:
        inbox = _inbox_dir(self.team_name, agent_name)
        return sum(
            1
            for path in _claimable_paths(inbox)
            if path.suffix != ".consumed" or not is_path_locked(path)
        )

    def list_recipients(self) -> list[str]:
        inboxes_dir = _teams_root() / self.team_name / "inboxes"
        if not inboxes_dir.exists():
            return []
        return [d.name for d in inboxes_dir.iterdir() if d.is_dir()]
