"""Spawn registry - persists agent process info for liveness checking."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import time
from pathlib import Path

from clawteam.fsutil import replace_file
from clawteam.team.models import get_data_dir


def _registry_path(team_name: str) -> Path:
    return get_data_dir() / "teams" / team_name / "spawn_registry.json"


def register_agent(
    team_name: str,
    agent_name: str,
    backend: str,
    tmux_target: str = "",
    pid: int = 0,
    command: list[str] | None = None,
) -> None:
    """Record spawn info for an agent (atomic write)."""
    path = _registry_path(team_name)
    registry = _load(path)
    registry[agent_name] = {
        "backend": backend,
        "tmux_target": tmux_target,
        "pid": pid,
        "command": command or [],
    }
    _save(path, registry)


def get_registry(team_name: str) -> dict[str, dict]:
    """Return the full spawn registry for a team."""
    return _load(_registry_path(team_name))


def is_agent_alive(team_name: str, agent_name: str) -> bool | None:
    """Check if a spawned agent process is still alive.

    Returns True if alive, False if dead, None if no spawn info found.
    """
    registry = get_registry(team_name)
    info = registry.get(agent_name)
    if not info:
        return None

    backend = info.get("backend", "")
    if backend == "tmux":
        alive = _tmux_pane_alive(info.get("tmux_target", ""))
        if alive is False:
            # Tmux target may be invalid (e.g. after tile operation);
            # fall back to PID check
            pid = info.get("pid", 0)
            if pid:
                return _pid_alive(pid)
        return alive
    elif backend in {"subprocess", "windows"}:
        return _pid_alive(info.get("pid", 0))
    return None


def list_dead_agents(team_name: str) -> list[str]:
    """Return names of agents whose processes are no longer alive."""
    registry = get_registry(team_name)
    dead = []
    for name, info in registry.items():
        alive = is_agent_alive(team_name, name)
        if alive is False:
            dead.append(name)
    return dead


def stop_agent(team_name: str, agent_name: str, timeout_seconds: float = 3.0) -> bool | None:
    """Best-effort stop of a previously registered agent.

    Returns:
        True if the agent was confirmed stopped.
        False if it was found but did not stop within the timeout.
        None if no registry entry exists.
    """
    registry = get_registry(team_name)
    info = registry.get(agent_name)
    if not info:
        return None

    backend = info.get("backend", "")
    if backend == "tmux":
        target = info.get("tmux_target", "")
        if target:
            subprocess.run(
                ["tmux", "kill-window", "-t", target],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
    elif backend in {"subprocess", "windows"}:
        pid = info.get("pid", 0)
        if pid:
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            except PermissionError:
                return False

    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        alive = is_agent_alive(team_name, agent_name)
        if alive is False or alive is None:
            return True
        time.sleep(0.1)

    return is_agent_alive(team_name, agent_name) in (False, None)


def _tmux_pane_alive(target: str) -> bool:
    """Check if a tmux target (session:window) still has a running process."""
    if not target:
        return False
    # Check if the window exists at all
    result = subprocess.run(
        ["tmux", "list-panes", "-t", target, "-F", "#{pane_dead} #{pane_current_command}"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        # Window doesn't exist anymore
        return False
    # Check pane_dead flag — "1" means the command has exited
    for line in result.stdout.strip().splitlines():
        parts = line.split(None, 1)
        if parts and parts[0] == "1":
            return False
        # Also check if the pane is just running a shell (agent exited, shell remains)
        if len(parts) >= 2 and parts[1] in ("bash", "zsh", "sh", "fish"):
            return False
    return True


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
        # Process exists but we can't signal it
        return True


def _load(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save(path: Path, data: dict) -> None:
    import tempfile
    path.parent.mkdir(parents=True, exist_ok=True)
    # Atomic write
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        import os
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
        replace_file(Path(tmp), path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
