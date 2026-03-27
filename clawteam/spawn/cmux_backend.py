"""Cmux spawn backend - launches agents in cmux workspaces for visual monitoring."""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import time

from clawteam.spawn.adapters import (
    NativeCliAdapter,
    is_claude_command,
    is_codex_command,
    is_gemini_command,
    is_kimi_command,
    is_nanobot_command,
    is_opencode_command,
    is_qwen_command,
)
from clawteam.spawn.base import SpawnBackend
from clawteam.spawn.cli_env import build_spawn_path, resolve_clawteam_executable
from clawteam.spawn.command_validation import validate_spawn_command

_CMUX_BIN = "/opt/homebrew/bin/cmux"
_SHELL_ENV_KEY_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")


def _cmux_available() -> bool:
    """Check if cmux binary exists and the socket is reachable."""
    if not os.path.isfile(_CMUX_BIN):
        return False
    try:
        result = subprocess.run(
            [_CMUX_BIN, "list-workspaces"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def _cmux_workspace_exists(name: str) -> bool:
    """Check if a cmux workspace with the given name exists."""
    try:
        result = subprocess.run(
            [_CMUX_BIN, "list-workspaces"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (subprocess.TimeoutExpired, OSError):
        return False
    if result.returncode != 0:
        return False
    for line in result.stdout.strip().splitlines():
        if name in line:
            return True
    return False


def _cmux_get_current_workspace() -> str | None:
    """Return the currently focused workspace ref, or None."""
    try:
        result = subprocess.run(
            [_CMUX_BIN, "current-workspace"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip()
    return None


class CmuxBackend(SpawnBackend):
    """Spawn agents in cmux workspaces for visual monitoring.

    Each agent gets its own cmux workspace named ``{team}-{agent}``.
    Agents run in interactive mode so their work is visible.
    """

    def __init__(self):
        self._agents: dict[str, str] = {}  # agent_name -> workspace name
        self._adapter = NativeCliAdapter()

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
        if not os.path.isfile(_CMUX_BIN):
            return f"Error: cmux not found at {_CMUX_BIN}"

        if not _cmux_available():
            return "Error: cmux is not running (socket not found). Start cmux first."

        workspace_name = f"{team_name}-{agent_name}"
        clawteam_bin = resolve_clawteam_executable()
        env_vars = os.environ.copy()
        # Normalize TERM for interactive CLIs
        if env_vars.get("TERM", "").lower() == "dumb":
            env_vars["TERM"] = "xterm-256color"
        env_vars.update({
            "CLAWTEAM_AGENT_ID": agent_id,
            "CLAWTEAM_AGENT_NAME": agent_name,
            "CLAWTEAM_AGENT_TYPE": agent_type,
            "CLAWTEAM_TEAM_NAME": team_name,
            "CLAWTEAM_AGENT_LEADER": "0",
        })
        if cwd:
            env_vars["CLAWTEAM_WORKSPACE_DIR"] = cwd
        # Inject context awareness flags
        env_vars["CLAWTEAM_CONTEXT_ENABLED"] = "1"
        if env:
            env_vars.update(env)
        env_vars["PATH"] = build_spawn_path(env_vars.get("PATH", os.environ.get("PATH")))
        if os.path.isabs(clawteam_bin):
            env_vars.setdefault("CLAWTEAM_BIN", clawteam_bin)

        prepared = self._adapter.prepare_command(
            command,
            prompt=prompt,
            cwd=cwd,
            skip_permissions=skip_permissions,
            agent_name=agent_name,
            interactive=True,
        )
        normalized_command = prepared.normalized_command
        validation_command = normalized_command
        final_command = list(prepared.final_command)
        post_launch_prompt = prepared.post_launch_prompt
        if system_prompt and is_claude_command(normalized_command):
            insert_at = final_command.index("-p") if "-p" in final_command else len(final_command)
            final_command[insert_at:insert_at] = ["--append-system-prompt", system_prompt]

        command_error = validate_spawn_command(validation_command, path=env_vars["PATH"], cwd=cwd)
        if command_error:
            return command_error

        # Build shell-safe env exports (filter out invalid env var names)
        export_vars = {k: v for k, v in env_vars.items() if _SHELL_ENV_KEY_RE.fullmatch(k)}
        export_str = "; ".join(f"export {k}={shlex.quote(v)}" for k, v in export_vars.items())

        cmd_str = " ".join(shlex.quote(c) for c in final_command)
        # On-exit hook: runs when agent process exits
        exit_cmd = shlex.quote(clawteam_bin) if os.path.isabs(clawteam_bin) else "clawteam"
        exit_hook = (
            f"{exit_cmd} lifecycle on-exit --team {shlex.quote(team_name)} "
            f"--agent {shlex.quote(agent_name)}"
        )
        # Unset Claude nesting-detection env vars so spawned agents don't refuse to start
        unset_clause = "unset CLAUDECODE CLAUDE_CODE_ENTRYPOINT CLAUDE_CODE_SESSION 2>/dev/null; "
        if cwd:
            full_cmd = f"{unset_clause}{export_str}; cd {shlex.quote(cwd)} && {cmd_str}; {exit_hook}"
        else:
            full_cmd = f"{unset_clause}{export_str}; {cmd_str}; {exit_hook}"

        # Remember current workspace to restore focus after spawn
        previous_workspace = _cmux_get_current_workspace()

        # Spawn workspace via cmux
        work_dir = cwd or os.getcwd()
        try:
            launch = subprocess.run(
                [_CMUX_BIN, "new-workspace", "--cwd", work_dir, "--command", full_cmd],
                capture_output=True,
                text=True,
                timeout=30,
            )
        except subprocess.TimeoutExpired:
            return "Error: cmux new-workspace timed out after 30s"

        if launch.returncode != 0:
            stderr = launch.stderr.strip() if launch.stderr else ""
            return f"Error: failed to launch cmux workspace: {stderr}"

        # Parse workspace ref from stdout: "OK workspace:N"
        workspace_ref = None
        stdout = launch.stdout.strip()
        match = re.search(r"(workspace:\S+)", stdout)
        if match:
            workspace_ref = match.group(1)

        # Rename workspace to team-agent format
        if workspace_ref:
            subprocess.run(
                [_CMUX_BIN, "rename-workspace", "--workspace", workspace_ref, workspace_name],
                capture_output=True,
                text=True,
                timeout=5,
            )

        # Restore focus to previous workspace to avoid focus steal
        if previous_workspace:
            subprocess.run(
                [_CMUX_BIN, "select-workspace", "--workspace", previous_workspace],
                capture_output=True,
                text=True,
                timeout=5,
            )

        from clawteam.config import load_config

        cfg = load_config()
        pane_ready_timeout = min(cfg.spawn_ready_timeout, max(4.0, cfg.spawn_prompt_delay + 2.0))
        if not _wait_for_cmux_workspace(
            workspace_name,
            timeout_seconds=pane_ready_timeout,
            poll_interval_seconds=0.2,
        ):
            return (
                f"Error: cmux workspace for '{normalized_command[0]}' did not become visible "
                f"within {pane_ready_timeout:.1f}s. Verify the CLI works standalone before "
                "using it with clawteam spawn."
            )

        _confirm_workspace_trust_if_prompted(
            workspace_name,
            normalized_command,
            timeout_seconds=cfg.spawn_ready_timeout,
        )

        if post_launch_prompt and is_codex_command(normalized_command):
            _dismiss_codex_update_prompt_if_present(
                workspace_name,
                normalized_command,
                timeout_seconds=pane_ready_timeout,
                poll_interval_seconds=0.2,
            )

        if post_launch_prompt:
            _wait_for_cli_ready(
                workspace_name,
                timeout_seconds=cfg.spawn_ready_timeout,
                fallback_delay=cfg.spawn_prompt_delay,
            )
            _inject_prompt_via_keys(workspace_name, post_launch_prompt)
        elif (
            prompt
            and not is_codex_command(normalized_command)
            and not is_nanobot_command(normalized_command)
            and not is_gemini_command(normalized_command)
            and not is_kimi_command(normalized_command)
            and not is_qwen_command(normalized_command)
            and not is_opencode_command(normalized_command)
        ):
            _wait_for_cli_ready(
                workspace_name,
                timeout_seconds=cfg.spawn_ready_timeout,
                fallback_delay=cfg.spawn_prompt_delay,
            )
            _inject_prompt_via_keys(workspace_name, prompt)

        self._agents[agent_name] = workspace_name

        # Persist spawn info for liveness checking
        from clawteam.spawn.registry import register_agent
        register_agent(
            team_name=team_name,
            agent_name=agent_name,
            backend="cmux",
            tmux_target=workspace_name,  # reuse field for workspace name
            pid=0,  # cmux doesn't expose pane PIDs
            command=list(final_command),
        )

        return f"Agent '{agent_name}' spawned in cmux workspace '{workspace_name}'"

    def list_running(self) -> list[dict[str, str]]:
        return [
            {"name": name, "workspace": workspace, "backend": "cmux"}
            for name, workspace in self._agents.items()
        ]


def _wait_for_cmux_workspace(
    workspace_name: str,
    timeout_seconds: float = 5.0,
    poll_interval_seconds: float = 0.2,
) -> bool:
    """Poll cmux until the workspace exists."""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if _cmux_workspace_exists(workspace_name):
            return True
        time.sleep(poll_interval_seconds)
    return False


def _read_workspace_screen(workspace_name: str) -> str:
    """Read the current screen content of a cmux workspace."""
    try:
        result = subprocess.run(
            [_CMUX_BIN, "read-screen", "--workspace", workspace_name],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (subprocess.TimeoutExpired, OSError):
        return ""
    if result.returncode == 0:
        return result.stdout
    return ""


def _confirm_workspace_trust_if_prompted(
    workspace_name: str,
    command: list[str],
    timeout_seconds: float = 5.0,
    poll_interval_seconds: float = 0.2,
) -> bool:
    """Acknowledge startup confirmation prompts for interactive CLIs.

    Claude Code and Codex can stop at a directory trust prompt when launched in
    a fresh git worktree. Detect and dismiss before prompt injection.
    """
    if not (is_claude_command(command) or is_codex_command(command) or is_gemini_command(command)):
        return False

    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        screen_text = _read_workspace_screen(workspace_name).lower()
        action = _startup_prompt_action(command, screen_text)
        if action == "enter":
            subprocess.run(
                [_CMUX_BIN, "input-text", "--workspace", workspace_name, "--text", "\n"],
                capture_output=True, text=True, timeout=5,
            )
            time.sleep(0.5)
            return True
        if action == "down-enter":
            subprocess.run(
                [_CMUX_BIN, "input-text", "--workspace", workspace_name, "--text", "\x1b[B"],
                capture_output=True, text=True, timeout=5,
            )
            time.sleep(0.2)
            subprocess.run(
                [_CMUX_BIN, "input-text", "--workspace", workspace_name, "--text", "\n"],
                capture_output=True, text=True, timeout=5,
            )
            time.sleep(0.5)
            return True

        time.sleep(poll_interval_seconds)
    return False


def _startup_prompt_action(command: list[str], screen_text: str) -> str | None:
    """Return the key action needed to dismiss a startup confirmation prompt."""
    if _looks_like_claude_skip_permissions_prompt(command, screen_text):
        return "down-enter"
    if _looks_like_workspace_trust_prompt(command, screen_text):
        return "enter"
    return None


def _looks_like_workspace_trust_prompt(command: list[str], screen_text: str) -> bool:
    """Return True when the screen is showing a trust confirmation dialog."""
    if not screen_text:
        return False
    if is_claude_command(command):
        return ("trust this folder" in screen_text or "trust the contents" in screen_text) and (
            "enter to confirm" in screen_text or "press enter" in screen_text or "enter to continue" in screen_text
        )
    if is_codex_command(command):
        return (
            "trust the contents of this directory" in screen_text
            and "press enter to continue" in screen_text
        )
    if is_gemini_command(command):
        return "trust folder" in screen_text or "trust parent folder" in screen_text
    return False


def _looks_like_claude_skip_permissions_prompt(command: list[str], screen_text: str) -> bool:
    """Return True when Claude is waiting for the dangerous-permissions confirmation."""
    if not screen_text or not is_claude_command(command):
        return False
    has_accept_choice = "yes, i accept" in screen_text
    has_permissions_warning = (
        "dangerously-skip-permissions" in screen_text
        or "skip permissions" in screen_text
        or "permission" in screen_text
        or "approval" in screen_text
    )
    return has_accept_choice and has_permissions_warning


def _looks_like_codex_update_prompt(screen_text: str) -> bool:
    """Return True when Codex is showing the update gate before the main TUI."""
    if not screen_text:
        return False
    return (
        "update available" in screen_text
        and "press enter to continue" in screen_text
        and ("update now" in screen_text or "skip until next version" in screen_text)
    )


def _dismiss_codex_update_prompt_if_present(
    workspace_name: str,
    command: list[str],
    timeout_seconds: float = 5.0,
    poll_interval_seconds: float = 0.2,
) -> bool:
    """Dismiss the Codex update gate if it is blocking the interactive UI."""
    if not is_codex_command(command):
        return False

    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        screen_text = _read_workspace_screen(workspace_name).lower()
        if _looks_like_codex_update_prompt(screen_text):
            subprocess.run(
                [_CMUX_BIN, "input-text", "--workspace", workspace_name, "--text", "\n"],
                capture_output=True, text=True, timeout=5,
            )
            time.sleep(0.5)
            return True

        if screen_text and "openai codex" in screen_text:
            return False

        time.sleep(poll_interval_seconds)
    return False


def _wait_for_cli_ready(
    workspace_name: str,
    timeout_seconds: float = 30.0,
    fallback_delay: float = 2.0,
    poll_interval: float = 1.0,
) -> bool:
    """Poll cmux workspace until an interactive CLI shows an input prompt.

    Uses prompt indicators and content stabilization, same heuristics as tmux backend.
    Returns True when ready, False on timeout.
    """
    deadline = time.monotonic() + timeout_seconds
    last_content = ""
    stable_count = 0

    while time.monotonic() < deadline:
        text = _read_workspace_screen(workspace_name)
        if not text:
            time.sleep(poll_interval)
            continue

        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        tail = lines[-10:] if len(lines) >= 10 else lines

        for line in tail:
            if line.startswith(("\u276f", ">", "\u203a")):
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
    time.sleep(fallback_delay)
    return False


def _inject_prompt_via_keys(workspace_name: str, prompt: str) -> None:
    """Inject a prompt into a cmux workspace via input-text.

    cmux doesn't have tmux's buffer mechanism, so we write the prompt
    text directly followed by Enter keystrokes.
    """
    subprocess.run(
        [_CMUX_BIN, "input-text", "--workspace", workspace_name, "--text", prompt],
        capture_output=True, text=True, timeout=10,
    )
    time.sleep(0.5)
    subprocess.run(
        [_CMUX_BIN, "input-text", "--workspace", workspace_name, "--text", "\n"],
        capture_output=True, text=True, timeout=5,
    )
    time.sleep(0.3)
    subprocess.run(
        [_CMUX_BIN, "input-text", "--workspace", workspace_name, "--text", "\n"],
        capture_output=True, text=True, timeout=5,
    )
