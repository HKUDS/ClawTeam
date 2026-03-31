"""Wsh spawn backend - launches agents in TideTerm/WaveTerminal blocks."""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import time
from pathlib import Path

from clawteam.spawn.adapters import (
    NativeCliAdapter,
    is_claude_command,
    is_codex_command,
    is_gemini_command,
)
from clawteam.spawn.base import SpawnBackend
from clawteam.spawn.cli_env import build_spawn_path, resolve_clawteam_executable
from clawteam.spawn.command_validation import validate_spawn_command
from clawteam.spawn.wsh_rpc import WshRpcClient


def _validate_path(path: str) -> str | None:
    """Validate and normalize a path. Returns error message or None if valid."""
    try:
        resolved = Path(path).resolve()
        if not resolved.exists():
            return f"Error: path does not exist: {path}"
        if not resolved.is_dir():
            return f"Error: path is not a directory: {path}"
    except Exception:
        return f"Error: invalid path: {path}"
    return None


def _wait_for_wsh_block(
    block_id: str,
    timeout_seconds: float = 30.0,
    poll_interval_seconds: float = 0.5,
) -> bool:
    """Poll wsh until target block exists and is observable."""
    wsh_bin = _find_wsh()
    if not wsh_bin:
        return False
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        result = subprocess.run(
            [wsh_bin, "blocks", "list", "--json"],
            capture_output=True,
            text=True,
            timeout=5.0,
        )
        if result.returncode == 0:
            try:
                blocks = json.loads(result.stdout)
                for block in blocks:
                    if block.get("blockid") == block_id:
                        return True
            except json.JSONDecodeError:
                pass
        time.sleep(poll_interval_seconds)

    return False


_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]|\x1b\].*?\x07|\x1b\[.*?m")


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def _capture_block_output(block_id: str, tail_lines: int = 100) -> str:
    """Capture terminal output from a block via wavefile protocol."""
    wsh_bin = _find_wsh()
    if not wsh_bin:
        return ""
    result = subprocess.run(
        [wsh_bin, "file", "cat", f"wavefile://{block_id}/term"],
        capture_output=True,
        text=True,
        timeout=10.0,
    )
    if result.returncode != 0:
        return ""

    cleaned = _strip_ansi(result.stdout)
    if tail_lines > 0:
        lines = cleaned.splitlines()
        return "\n".join(lines[-tail_lines:])
    return cleaned


def _wait_for_cli_ready(
    block_id: str,
    command: list[str],
    timeout_seconds: float = 30.0,
    poll_interval: float = 1.0,
) -> bool:
    """Poll block until CLI shows an input prompt."""
    deadline = time.monotonic() + timeout_seconds
    last_content = ""
    stable_count = 0

    while time.monotonic() < deadline:
        text = _capture_block_output(block_id)
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        tail = lines[-10:] if len(lines) >= 10 else lines

        for line in tail:
            if line.startswith(("❯", ">", "›")):
                return True
            if "Try " in line and "write a test" in line:
                return True

        if text == last_content and lines:
            stable_count += 1
            if stable_count >= 2:
                return True
        else:
            stable_count = 0
            last_content = text

        time.sleep(poll_interval)

    return False


def _is_block_alive(block_id: str) -> bool:
    """Check if a wsh block is still alive."""
    if not block_id:
        return False
    wsh_bin = _find_wsh()
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
                meta = block.get("meta", {})
                controller = meta.get("controller", "")
                return controller in ("shell", "cmd")
    except json.JSONDecodeError:
        pass

    return False


def _looks_like_workspace_trust_prompt(command: list[str], pane_text: str) -> bool:
    """Return True when block is showing a trust confirmation dialog."""
    if not pane_text:
        return False

    if is_claude_command(command):
        return ("trust this folder" in pane_text or "trust contents" in pane_text) and (
            "enter to confirm" in pane_text
            or "press enter" in pane_text
            or "enter to continue" in pane_text
        )

    if is_codex_command(command):
        return (
            "trust contents of this directory" in pane_text
            and "press enter to continue" in pane_text
        )

    if is_gemini_command(command):
        return "trust folder" in pane_text or "trust parent folder" in pane_text

    return False


_WSH_SEARCH_PATHS = [
    Path.home() / ".local/share/tideterm/bin/wsh",
    Path.home() / ".local/state/waveterm/bin/wsh",
]


def _find_wsh() -> str | None:
    """Find wsh executable via PATH or known locations."""
    found = shutil.which("wsh")
    if found:
        return found
    for p in _WSH_SEARCH_PATHS:
        if p.is_file() and os.access(p, os.X_OK):
            return str(p)
    return None


class WshBackend(SpawnBackend):
    """Spawn agents in TideTerm/WaveTerminal blocks.

    Each agent gets its own block with isolated terminal session.
    Terminal output is captured via wavefile protocol.
    Input is injected via JSON-RPC over Unix socket.
    """

    def __init__(self):
        self._blocks: dict[str, str] = {}
        self._adapter = NativeCliAdapter()
        self._rpc_client: WshRpcClient | None = None

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
        system_prompt: str | None = None,
    ) -> str:
        """Spawn a new agent in a TideTerm block."""
        wsh_bin = _find_wsh()
        if not wsh_bin:
            return "Error: wsh not installed"

        if cwd:
            path_error = _validate_path(cwd)
            if path_error:
                return path_error

        clawteam_bin = resolve_clawteam_executable()
        env_vars = os.environ.copy()
        env_vars.update(
            {
                "CLAWTEAM_AGENT_ID": agent_id,
                "CLAWTEAM_AGENT_NAME": agent_name,
                "CLAWTEAM_AGENT_TYPE": agent_type,
                "CLAWTEAM_TEAM_NAME": team_name,
                "CLAWTEAM_AGENT_LEADER": "0",
            }
        )
        if cwd:
            env_vars["CLAWTEAM_WORKSPACE_DIR"] = cwd
        if env:
            env_vars.update(env)
        env_vars["PATH"] = build_spawn_path(env_vars.get("PATH", os.environ.get("PATH")))

        prepared = self._adapter.prepare_command(
            command,
            prompt=None,
            cwd=cwd,
            skip_permissions=skip_permissions,
            agent_name=agent_name,
            interactive=True,
        )
        normalized_command = prepared.normalized_command
        validation_command = normalized_command
        final_command = list(prepared.final_command)

        if prompt and is_claude_command(normalized_command):
            final_command.append(prompt)

        if system_prompt and is_claude_command(normalized_command):
            if "-p" in final_command:
                insert_at = final_command.index("-p") + 2
            else:
                insert_at = 1
            final_command[insert_at:insert_at] = ["--append-system-prompt", system_prompt]

        command_error = validate_spawn_command(
            validation_command, path=env_vars.get("PATH", ""), cwd=cwd
        )
        if command_error:
            return command_error

        cmd_str = " ".join(shlex.quote(c) for c in final_command)
        exit_cmd = shlex.quote(clawteam_bin) if os.path.isabs(clawteam_bin) else "clawteam"
        exit_hook = (
            f"{exit_cmd} lifecycle on-exit --team {shlex.quote(team_name)} "
            f"--agent {shlex.quote(agent_name)}"
        )

        shell_env_key_re = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
        export_vars = {k: v for k, v in env_vars.items() if shell_env_key_re.fullmatch(k)}
        export_prefix = " ".join(f"export {k}={shlex.quote(v)}" for k, v in export_vars.items())

        if cwd:
            full_cmd = f"{export_prefix}; cd {shlex.quote(cwd)} && {cmd_str}; {exit_hook}"
        else:
            full_cmd = f"{export_prefix}; {cmd_str}; {exit_hook}"

        result = subprocess.run(
            [wsh_bin, "run", "-X", "-c", full_cmd, "--cwd", cwd if cwd else "."],
            capture_output=True,
            text=True,
            timeout=30.0,
        )

        if result.returncode != 0:
            return "Error: failed to create block"

        match = re.search(r"block:([a-f0-9-]+)", result.stdout)
        if not match:
            return "Error: could not parse block ID from wsh output"

        block_id = match.group(1)

        self._blocks[agent_name] = block_id

        from clawteam.config import load_config

        cfg = load_config()

        if not _wait_for_wsh_block(
            block_id,
            timeout_seconds=cfg.spawn_ready_timeout,
            poll_interval_seconds=0.5,
        ):
            return (
                f"Error: wsh block for '{normalized_command[0]}' did not become visible "
                f"within {cfg.spawn_ready_timeout:.1f}s. Verify CLI works standalone before "
                "using it with clawteam spawn."
            )

        subprocess.run(
            [
                wsh_bin,
                "setmeta",
                "-b",
                block_id,
                f"clawteam:team={team_name}",
                f"clawteam:agent={agent_name}",
                f"frame:title={agent_name}",
            ],
            capture_output=True,
        )

        pane_pid = 0
        from clawteam.spawn.registry import register_agent

        register_agent(
            team_name=team_name,
            agent_name=agent_name,
            backend="wsh",
            block_id=block_id,
            pid=pane_pid,
            command=list(final_command),
        )

        return f"Agent '{agent_name}' spawned in wsh block ({block_id})"

    def list_running(self) -> list[dict[str, str]]:
        """List currently running agents."""
        return [
            {"name": name, "target": target, "backend": "wsh"}
            for name, target in self._blocks.items()
        ]

    def _confirm_workspace_trust_if_prompted(
        self,
        block_id: str,
        command: list[str],
        timeout_seconds: float = 5.0,
        poll_interval_seconds: float = 0.2,
    ) -> bool:
        """Acknowledge startup confirmation prompts for interactive CLIs."""
        if not (
            is_claude_command(command) or is_codex_command(command) or is_gemini_command(command)
        ):
            return False

        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            output = _capture_block_output(block_id)
            output_lower = output.lower()

            if _looks_like_workspace_trust_prompt(command, output_lower):
                if self._rpc_client is None:
                    self._rpc_client = WshRpcClient()
                self._rpc_client.send_input(block_id, "")
                return True

            time.sleep(poll_interval_seconds)

        return False
