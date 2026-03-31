"""Spawn registry - persists agent process info for liveness checking."""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import time
from pathlib import Path

from clawteam.fileutil import atomic_write_text, file_locked
from clawteam.paths import ensure_within_root, validate_identifier
from clawteam.team.models import get_data_dir


def _registry_path(team_name: str) -> Path:
    return ensure_within_root(
        get_data_dir() / "teams",
        validate_identifier(team_name, "team name"),
        "spawn_registry.json",
    )


def register_agent(
    team_name: str,
    agent_name: str,
    backend: str,
    tmux_target: str = "",
    block_id: str = "",
    pid: int = 0,
    command: list[str] | None = None,
) -> None:
    """Record spawn info for an agent (atomic + locked write)."""
    path = _registry_path(team_name)
    with file_locked(path):
        registry = _load(path)
        registry[agent_name] = {
            "backend": backend,
            "tmux_target": tmux_target,
            "block_id": block_id,
            "pid": pid,
            "command": command or [],
            "spawned_at": time.time(),
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
    elif backend == "subprocess":
        return _pid_alive(info.get("pid", 0))
    elif backend == "wsh":
        return _wsh_block_alive(info.get("block_id", ""))
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


def list_zombie_agents(team_name: str, max_hours: float = 2.0) -> list[dict]:
    """Return agents that are still alive but have been running longer than max_hours.

    Each entry contains: agent_name, pid, backend, spawned_at (unix ts), running_hours.
    Agents with no spawned_at recorded are skipped (legacy registry entries).
    """
    registry = get_registry(team_name)
    threshold = max_hours * 3600
    now = time.time()
    zombies = []
    for name, info in registry.items():
        spawned_at = info.get("spawned_at")
        if not spawned_at:
            continue
        alive = is_agent_alive(team_name, name)
        if alive is True:
            running_seconds = now - spawned_at
            if running_seconds > threshold:
                zombies.append({
                    "agent_name": name,
                    "pid": info.get("pid", 0),
                    "backend": info.get("backend", ""),
                    "spawned_at": spawned_at,
                    "running_hours": round(running_seconds / 3600, 1),
                })
    return zombies


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
    elif backend == "subprocess":
        pid = info.get("pid", 0)
        if pid:
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            except PermissionError:
                return False
    elif backend == "wsh":
        block_id = info.get("block_id", "")
        if block_id:
            subprocess.run(
                ["wsh", "deleteblock", "-b", block_id],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

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
    import sys
    if sys.platform == "win32":
        import ctypes
        # PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        # STILL_ACTIVE = 259
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        exit_code = ctypes.c_ulong()
        ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
        ctypes.windll.kernel32.CloseHandle(handle)
        return exit_code.value == 259
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        # Process exists but we can't signal it
        return True


def _wsh_block_alive(block_id: str) -> bool:
    """Check if a wsh block is still alive."""
    if not block_id:
        return False

    wsh_bin = shutil.which("wsh")
    if not wsh_bin:
        for p in [
            Path.home() / ".local/share/tideterm/bin/wsh",
            Path.home() / ".local/state/waveterm/bin/wsh",
        ]:
            if p.is_file() and os.access(p, os.X_OK):
                wsh_bin = str(p)
                break
    if not wsh_bin:
        return False

    result = subprocess.run(
        [wsh_bin, "blocks", "list", "--json"],
        capture_output=True,
        text=True,
        timeout=5.0,
    )
    if result.returncode != 0:
        return False

    try:
        blocks = json.loads(result.stdout)
        for block in blocks:
            if block.get("blockid") == block_id:
                return True
    except json.JSONDecodeError:
        pass

    return False


def _load(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save(path: Path, data: dict) -> None:
    atomic_write_text(path, json.dumps(data, indent=2))
