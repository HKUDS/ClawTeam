"""ACPX spawn backend - launches agents via Agent Client Protocol (acpx CLI)."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess

from clawteam.spawn.base import SpawnBackend


# ACPX-supported agent types and their acpx subcommand names
ACPX_AGENTS = frozenset({
    "pi", "codex", "claude", "gemini", "cursor", "copilot", "openclaw",
})


class AcpxBackend(SpawnBackend):
    """Spawn agents using acpx (Agent Client Protocol headless CLI).

    Instead of managing tmux sessions or raw subprocesses, this backend
    delegates to ``acpx <agent-type> <prompt>`` which communicates with
    agents through their native ACP interface.

    Supports:
    - Named sessions (``-s <name>``) for reconnect / resume
    - JSON output format (``--format json``) for structured parsing
    - Permission modes (``--approve-all``, ``--approve-reads``)
    - Async prompt submission (``--no-wait``)
    """

    def __init__(self, acpx_path: str = "acpx"):
        self._acpx = acpx_path
        self._agents: dict[str, dict] = {}  # agent_name -> spawn info

    # ------------------------------------------------------------------
    # SpawnBackend interface
    # ------------------------------------------------------------------

    def spawn(
        self,
        command: list[str],
        agent_name: str,
        agent_id: str,
        agent_type: str,
        team_name: str,
        prompt: str | None = None,
        env: dict[str, str] | None = None,
        cwd: str | None = None,
        skip_permissions: bool = False,
    ) -> str:
        if not shutil.which(self._acpx):
            return (
                f"Error: '{self._acpx}' not found. "
                "Install with: npm install -g acpx@latest"
            )

        # Determine the acpx agent type from the command
        acpx_agent = _resolve_acpx_agent(command)

        # Build the acpx command
        acpx_cmd = [self._acpx, acpx_agent]

        # Named session for reconnect support
        session_name = f"clawteam-{team_name}-{agent_name}"
        acpx_cmd.extend(["-s", session_name])

        # JSON output for structured message parsing
        acpx_cmd.extend(["--format", "json"])

        # Permission modes
        if skip_permissions:
            acpx_cmd.append("--approve-all")

        # Async: run with --no-wait so the spawn returns immediately
        acpx_cmd.append("--no-wait")

        # Append the prompt
        if prompt:
            acpx_cmd.append(prompt)

        # Prepare environment
        spawn_env = os.environ.copy()
        spawn_env.update({
            "CLAWTEAM_AGENT_ID": agent_id,
            "CLAWTEAM_AGENT_NAME": agent_name,
            "CLAWTEAM_AGENT_TYPE": agent_type,
            "CLAWTEAM_TEAM_NAME": team_name,
            "CLAWTEAM_AGENT_LEADER": "0",
        })
        user = os.environ.get("CLAWTEAM_USER", "")
        if user:
            spawn_env["CLAWTEAM_USER"] = user
        transport = os.environ.get("CLAWTEAM_TRANSPORT", "")
        if transport:
            spawn_env["CLAWTEAM_TRANSPORT"] = transport
        if cwd:
            spawn_env["CLAWTEAM_WORKSPACE_DIR"] = cwd
        # Inject context awareness flags
        spawn_env["CLAWTEAM_CONTEXT_ENABLED"] = "1"
        if env:
            spawn_env.update(env)

        # Wrap with on-exit hook
        cmd_str = " ".join(shlex.quote(c) for c in acpx_cmd)
        exit_hook = (
            f"clawteam lifecycle on-exit --team {shlex.quote(team_name)} "
            f"--agent {shlex.quote(agent_name)}"
        )
        shell_cmd = f"{cmd_str}; {exit_hook}"

        process = subprocess.Popen(
            shell_cmd,
            shell=True,
            env=spawn_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=cwd,
        )

        self._agents[agent_name] = {
            "pid": process.pid,
            "session": session_name,
            "acpx_agent": acpx_agent,
            "command": acpx_cmd,
        }

        # Persist spawn info for liveness checking
        from clawteam.spawn.registry import register_agent

        register_agent(
            team_name=team_name,
            agent_name=agent_name,
            backend="acpx",
            pid=process.pid,
            command=acpx_cmd,
        )

        return (
            f"Agent '{agent_name}' spawned via acpx "
            f"(agent={acpx_agent}, session={session_name}, pid={process.pid})"
        )

    def list_running(self) -> list[dict[str, str]]:
        result = []
        for name, info in list(self._agents.items()):
            pid = info.get("pid", 0)
            if pid and _pid_alive(pid):
                result.append({
                    "name": name,
                    "pid": str(pid),
                    "session": info.get("session", ""),
                    "acpx_agent": info.get("acpx_agent", ""),
                    "backend": "acpx",
                })
            else:
                self._agents.pop(name, None)
        return result

    # ------------------------------------------------------------------
    # ACPX session helpers
    # ------------------------------------------------------------------

    def send_prompt(self, session_name: str, prompt: str) -> str | None:
        """Send a follow-up prompt to an existing ACPX session.

        Returns the JSON response or None on failure.
        """
        cmd = [self._acpx, "send", "-s", session_name, "--format", "json", prompt]
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=300,
            )
            if result.returncode == 0:
                return result.stdout
        except (subprocess.TimeoutExpired, OSError):
            pass
        return None

    def get_session_status(self, session_name: str) -> dict | None:
        """Query ACPX session status. Returns parsed JSON or None."""
        cmd = [self._acpx, "status", "-s", session_name, "--format", "json"]
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                return json.loads(result.stdout)
        except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
            pass
        return None

    @staticmethod
    def is_available() -> bool:
        """Check if acpx CLI is installed and reachable."""
        return shutil.which("acpx") is not None


def _resolve_acpx_agent(command: list[str]) -> str:
    """Map a ClawTeam command list to an acpx agent type.

    If the command itself is an acpx-known agent (e.g. ["claude"]),
    return it directly. Otherwise default to "claude".
    """
    if not command:
        return "claude"
    cmd_base = command[0].rsplit("/", 1)[-1].lower()  # basename, lowercase
    if cmd_base in ACPX_AGENTS:
        return cmd_base
    # Check if command[0] is "acpx" and command[1] is the agent type
    if cmd_base == "acpx" and len(command) > 1 and command[1] in ACPX_AGENTS:
        return command[1]
    return "claude"


def _pid_alive(pid: int) -> bool:
    """Check if a process with the given PID is still running."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
