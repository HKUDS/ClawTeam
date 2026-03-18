"""ACPX transport: uses ACPX sessions as message channels between agents.

Leverages ACPX's structured JSON output for reliable message delivery.
Falls back to FileTransport if ACPX is unavailable.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
import uuid
from pathlib import Path

from clawteam.team.models import get_data_dir
from clawteam.transport.base import Transport
from clawteam.transport.file import FileTransport


def _acpx_sessions_dir(team_name: str) -> Path:
    """Directory to track ACPX session metadata for a team."""
    d = get_data_dir() / "teams" / team_name / "acpx_sessions"
    d.mkdir(parents=True, exist_ok=True)
    return d


class AcpxTransport(Transport):
    """Transport that uses ACPX sessions as message channels.

    Each agent has a named ACPX session. Delivering a message sends a
    structured prompt to the recipient's session. Fetching reads from
    a local spool directory populated by ACPX JSON output.

    Falls back to FileTransport if the acpx CLI is not available.
    """

    def __init__(self, team_name: str, acpx_path: str = "acpx"):
        self.team_name = team_name
        self._acpx = acpx_path
        self._file_fallback = FileTransport(team_name)
        self._available = shutil.which(self._acpx) is not None

    def deliver(self, recipient: str, data: bytes) -> None:
        if not self._available:
            self._file_fallback.deliver(recipient, data)
            return

        session_name = f"clawteam-{self.team_name}-{recipient}"

        # Try to deliver via ACPX session
        try:
            # Parse the message to extract content for the ACPX prompt
            msg = json.loads(data)
            content = msg.get("content", data.decode("utf-8", errors="replace"))
            from_agent = msg.get("from_agent", "unknown")
            payload = f"[ClawTeam message from {from_agent}]: {content}"

            result = subprocess.run(
                [
                    self._acpx, "send",
                    "-s", session_name,
                    "--format", "json",
                    "--no-wait",
                    payload,
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0:
                # Also store in file spool as a reliable record
                self._spool_message(recipient, data)
                return
        except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
            pass

        # ACPX delivery failed — fall back to file transport
        self._file_fallback.deliver(recipient, data)

    def fetch(self, agent_name: str, limit: int = 10, consume: bool = True) -> list[bytes]:
        messages: list[bytes] = []

        # Read from the ACPX spool directory first
        spool = self._spool_dir(agent_name)
        if spool.exists():
            files = sorted(spool.glob("msg-*.json"))
            for f in files[:limit]:
                try:
                    raw = f.read_bytes()
                    messages.append(raw)
                    if consume:
                        f.unlink()
                except Exception:
                    if consume:
                        try:
                            f.unlink()
                        except OSError:
                            pass

        # Fill remaining from file fallback
        remaining = limit - len(messages)
        if remaining > 0:
            messages.extend(self._file_fallback.fetch(agent_name, remaining, consume))

        return messages[:limit]

    def count(self, agent_name: str) -> int:
        spool = self._spool_dir(agent_name)
        spool_count = len(list(spool.glob("msg-*.json"))) if spool.exists() else 0
        return spool_count + self._file_fallback.count(agent_name)

    def list_recipients(self) -> list[str]:
        recipients: set[str] = set()
        # Check ACPX sessions directory
        sessions_dir = _acpx_sessions_dir(self.team_name)
        for f in sessions_dir.glob("*.json"):
            recipients.add(f.stem)
        # Union with file transport recipients
        recipients.update(self._file_fallback.list_recipients())
        return list(recipients)

    def close(self) -> None:
        """Release resources."""
        pass

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _spool_dir(self, agent_name: str) -> Path:
        """Per-agent spool directory for ACPX-delivered messages."""
        d = get_data_dir() / "teams" / self.team_name / "acpx_spool" / agent_name
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _spool_message(self, recipient: str, data: bytes) -> None:
        """Write a message to the recipient's spool directory (atomic)."""
        spool = self._spool_dir(recipient)
        ts = int(time.time() * 1000)
        uid = uuid.uuid4().hex[:8]
        filename = f"msg-{ts}-{uid}.json"
        tmp = spool / f".tmp-{uid}.json"
        target = spool / filename
        tmp.write_bytes(data)
        tmp.rename(target)

    def register_session(self, agent_name: str, session_name: str) -> None:
        """Record an ACPX session for an agent (for recipient discovery)."""
        sessions_dir = _acpx_sessions_dir(self.team_name)
        info = {"session": session_name, "agent": agent_name}
        path = sessions_dir / f"{agent_name}.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(info), encoding="utf-8")
        tmp.rename(path)
