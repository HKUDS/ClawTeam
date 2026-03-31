"""Inbox watcher - synchronous file polling for CLI watch mode."""

from __future__ import annotations

import signal
import subprocess
import sys
import time

from clawteam.team.mailbox import MailboxManager
from clawteam.team.models import TeamMessage


class InboxWatcher:
    """Polls an agent's inbox directory for new messages.

    Designed for CLI ``inbox watch`` mode - prints messages to stdout as they arrive.
    Supports an optional --exec callback that runs a shell command for each message.
    """

    def __init__(
        self,
        team_name: str,
        agent_name: str,
        mailbox: MailboxManager,
        poll_interval: float = 1.0,
        json_output: bool = False,
        exec_cmd: str | None = None,
        runtime_router=None,
    ):
        self.team_name = team_name
        self.agent_name = agent_name
        self.mailbox = mailbox
        self.poll_interval = poll_interval
        self.json_output = json_output
        self.exec_cmd = exec_cmd
        self.runtime_router = runtime_router
        self._running = False

    def watch(self) -> None:
        """Start the blocking polling loop. Ctrl+C to stop."""
        self._running = True

        def _handle_signal(signum, frame):
            self._running = False

        prev_int = signal.getsignal(signal.SIGINT)
        prev_term = signal.getsignal(signal.SIGTERM)
        signal.signal(signal.SIGINT, _handle_signal)
        signal.signal(signal.SIGTERM, _handle_signal)

        try:
            while self._running:
                if self.runtime_router:
                    self._flush_runtime_routes()
                messages = self.mailbox.receive(self.agent_name, limit=10)
                for msg in messages:
                    self._handle_message(msg)
                time.sleep(self.poll_interval)
        finally:
            signal.signal(signal.SIGINT, prev_int)
            signal.signal(signal.SIGTERM, prev_term)

    def _handle_message(self, msg: TeamMessage) -> None:
        self._output(msg)
        if self.runtime_router:
            try:
                self.runtime_router.route_message(msg)
            except Exception as exc:
                self._warn(f"[warn] runtime routing failed: {exc}")
        if self.exec_cmd:
            self._run_callback(msg)

    def _flush_runtime_routes(self) -> None:
        try:
            self.runtime_router.flush_due()
        except Exception as exc:
            self._warn(f"[warn] runtime flush failed: {exc}")

    def _output(self, msg: TeamMessage) -> None:
        if self.json_output:
            print(msg.model_dump_json(by_alias=True, exclude_none=True), flush=True)
        else:
            print(
                f"[{msg.timestamp}] {msg.type.value} from={msg.from_agent} "
                f"to={msg.to}: {msg.content}",
                flush=True,
            )

    def _warn(self, message: str) -> None:
        stream = sys.stderr if self.json_output else None
        print(message, file=stream, flush=True)

    def _run_callback(self, msg: TeamMessage) -> None:
        """Execute the --exec command with message data as env vars."""
        env_extra = {
            "CLAWTEAM_MSG_FROM": msg.from_agent or "",
            "CLAWTEAM_MSG_TO": msg.to or "",
            "CLAWTEAM_MSG_TYPE": msg.type.value,
            "CLAWTEAM_MSG_CONTENT": msg.content or "",
            "CLAWTEAM_MSG_TIMESTAMP": msg.timestamp or "",
            "CLAWTEAM_MSG_JSON": msg.model_dump_json(by_alias=True, exclude_none=True),
        }
        import os
        full_env = {**os.environ, **env_extra}
        try:
            subprocess.run(
                self.exec_cmd,
                shell=True,
                env=full_env,
                timeout=30,
            )
        except subprocess.TimeoutExpired:
            print("[warn] exec callback timed out", flush=True)
        except Exception as e:
            print(f"[warn] exec callback failed: {e}", flush=True)
