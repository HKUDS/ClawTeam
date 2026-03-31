"""Cmux spawn backend - launches agents in cmux workspaces for visual monitoring."""
# cmux backend v0.4.0 — unified launcher + helpers, PYTHONDONTWRITEBYTECODE

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import tempfile
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
    """Check if a cmux workspace with the given exact name exists."""
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
        parts = line.strip().split()
        for i, part in enumerate(parts):
            if part.startswith("workspace:") and i + 1 < len(parts):
                ws_name = parts[i + 1]
                if ws_name == name:
                    return True
                break
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


# ---------------------------------------------------------------------------
# Unified helpers — parameterized by is_surface to serve both workspace and
# surface (tab) code paths.  Replaces the former _read_workspace_screen,
# _wait_for_cli_ready / _wait_for_surface_ready, and
# _inject_prompt_via_keys / _inject_prompt_via_surface duplicates.
# ---------------------------------------------------------------------------


def _read_screen(handle: str, is_surface: bool = False) -> str:
    """Read the current screen content of a cmux workspace or surface."""
    flag = "--surface" if is_surface else "--workspace"
    try:
        result = subprocess.run(
            [_CMUX_BIN, "read-screen", flag, handle],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (subprocess.TimeoutExpired, OSError):
        return ""
    if result.returncode == 0:
        return result.stdout
    return ""


def _wait_for_ready(
    handle: str,
    is_surface: bool = False,
    timeout_seconds: float = 30.0,
    fallback_delay: float = 2.0,
    poll_interval: float = 1.0,
) -> bool:
    """Poll cmux workspace/surface until an interactive CLI shows an input prompt.

    Uses prompt indicators and content stabilisation.
    Returns True when ready, False on timeout.
    """
    deadline = time.monotonic() + timeout_seconds
    last_content = ""
    stable_count = 0

    while time.monotonic() < deadline:
        text = _read_screen(handle, is_surface)
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
            if "-- INSERT --" in line:
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


def _inject_prompt(handle: str, prompt: str, is_surface: bool = False) -> bool:
    """Inject a prompt into a cmux workspace/surface via send + send-key.

    Writes prompt to a temp file first to handle multiline/special chars.
    On Enter failure, falls back to sending a literal ``\\n`` (was surface-only,
    now unified for both modes).
    """
    flag = "--surface" if is_surface else "--workspace"
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write(prompt)
        prompt_file = f.name

    try:
        with open(prompt_file) as f:
            prompt_text = f.read()

        result = subprocess.run(
            [_CMUX_BIN, "send", flag, handle, prompt_text],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return False

        time.sleep(0.5)

        result = subprocess.run(
            [_CMUX_BIN, "send-key", flag, handle, "Enter"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            # Fallback: try literal \n via send
            subprocess.run(
                [_CMUX_BIN, "send", flag, handle, "\\n"],
                capture_output=True, text=True, timeout=5,
            )
        return True
    finally:
        os.unlink(prompt_file)


# ---------------------------------------------------------------------------
# Launcher builder — both surface and workspace modes write the same
# self-deleting script so there is one place to set PYTHONDONTWRITEBYTECODE
# and one cleanup pattern.
# ---------------------------------------------------------------------------


def _prepare_launcher(full_cmd: str) -> str:
    """Write a self-deleting launcher script and return its path.

    The script:
    1. Exports PYTHONDONTWRITEBYTECODE=1 (prevents .pyc staleness)
    2. Schedules its own deletion after 5 s (belt-and-suspenders cleanup)
    3. Runs the full agent command chain
    """
    fd, path = tempfile.mkstemp(prefix="agent-launch-", suffix=".sh")
    with os.fdopen(fd, "w") as f:
        f.write("#!/usr/bin/env bash\n")
        f.write("export PYTHONDONTWRITEBYTECODE=1\n")
        f.write('_self="$0"; ( sleep 5; rm -f "$_self" ) &\n')
        f.write(full_cmd + "\n")
    os.chmod(path, 0o700)
    return path


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
        parent_workspace: str | None = None,
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

        # Write env to temp file to avoid exposing secrets in terminal scrollback.
        # The file is sourced then deleted — secrets never appear in the command line.
        export_vars = {k: v for k, v in env_vars.items() if _SHELL_ENV_KEY_RE.fullmatch(k)}
        env_fd, env_path = tempfile.mkstemp(prefix="clawteam-env-", suffix=".sh")
        with os.fdopen(env_fd, "w") as f:
            for k, v in export_vars.items():
                f.write(f"export {k}={shlex.quote(v)}\n")
        os.chmod(env_path, 0o600)  # restrict read to owner
        # Default close command (workspace mode). Surface mode overrides after
        # surface_ref is known — the env file is sourced at shell runtime, so
        # appending before launch is fine.
        with open(env_path, "a") as f:
            f.write(f"export _CMUX_CLOSE_CMD={shlex.quote(f'{_CMUX_BIN} close-workspace --workspace {workspace_name}')}\n")

        cmd_str = " ".join(shlex.quote(c) for c in final_command)
        # On-exit hook: runs when agent process exits.
        # Capture exit code and include it in the DONE message so parents can
        # distinguish clean exits from crashes.  Only send the fallback DONE if
        # the agent didn't already post one (avoids duplicate messages).
        exit_cmd = shlex.quote(clawteam_bin) if os.path.isabs(clawteam_bin) else "clawteam"
        exit_hook = (
            f"_ec=$?; "
            f"_already=$({exit_cmd} inbox peek {shlex.quote(team_name)} "
            f"--agent leader 2>/dev/null | grep -cF 'DONE: {agent_name}' || true); "
            f'if [ "$_already" = "0" ]; then '
            f"{exit_cmd} inbox send {shlex.quote(team_name)} leader "
            f"\"DONE: {agent_name} exited (exit_code=$_ec)\" -f {shlex.quote(agent_name)} 2>/dev/null; "
            f"fi; "
            f"{exit_cmd} lifecycle on-exit --team {shlex.quote(team_name)} "
            f"--agent {shlex.quote(agent_name)}"
        )
        # Auto-close cmux workspace after agent exits + cleanup badges.
        ws_name = f"{team_name}-{agent_name}"
        # Clear sidebar badges on exit. Use $CMUX_WORKSPACE_ID which cmux
        # auto-sets in every shell it spawns — works for both workspace and surface mode.
        badge_cleanup = (
            f"{shlex.quote(_CMUX_BIN)} clear-status agent-{agent_name} --workspace \"$CMUX_WORKSPACE_ID\" 2>/dev/null"
        )
        cmux_cleanup = (
            f"{badge_cleanup}; "
            f"echo '\\n[Agent exited. Workspace closes in 30s. Press Ctrl-C to keep.]'; "
            f"sleep 30 && eval \"$_CMUX_CLOSE_CMD\" 2>/dev/null"
        )
        # Source env from file (secrets stay off terminal), then delete the file
        env_source = f". {shlex.quote(env_path)} && rm -f {shlex.quote(env_path)}"
        unset_clause = "unset CLAUDECODE CLAUDE_CODE_ENTRYPOINT CLAUDE_CODE_SESSION 2>/dev/null; "
        if cwd:
            full_cmd = f"{unset_clause}{env_source}; cd {shlex.quote(cwd)} || exit 1; {cmd_str}; {exit_hook}; {cmux_cleanup}"
        else:
            full_cmd = f"{unset_clause}{env_source}; {cmd_str}; {exit_hook}; {cmux_cleanup}"

        # Unified launcher script for both modes (G1, G4)
        launcher_path = _prepare_launcher(full_cmd)

        # Remember current workspace to restore focus after spawn
        previous_workspace = _cmux_get_current_workspace()

        work_dir = cwd or os.getcwd()
        is_surface = bool(parent_workspace)

        if is_surface:
            # --- Surface mode: spawn as a tab inside the parent workspace ---
            try:
                launch = subprocess.run(
                    [_CMUX_BIN, "new-surface", "--workspace", parent_workspace],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
            except subprocess.TimeoutExpired:
                os.unlink(launcher_path)
                os.unlink(env_path)
                return "Error: cmux new-surface timed out after 30s"

            if launch.returncode != 0:
                os.unlink(launcher_path)
                os.unlink(env_path)
                stderr = launch.stderr.strip() if launch.stderr else ""
                return f"Error: failed to create cmux surface: {stderr}"

            # Parse surface ref from stdout (e.g. "OK surface:N")
            surface_ref = None
            stdout = launch.stdout.strip()
            m = re.search(r"(surface:\S+)", stdout)
            if m:
                surface_ref = m.group(1)

            if not surface_ref:
                os.unlink(launcher_path)
                os.unlink(env_path)
                return f"Error: could not parse surface ref from cmux output: {stdout}"

            # Rename tab for identification
            subprocess.run(
                [_CMUX_BIN, "rename-tab", "--surface", surface_ref, workspace_name],
                capture_output=True, text=True, timeout=5,
            )

            # Override close command: surface mode closes the tab, not the workspace
            # Also set correct CMUX env vars so spawned shell knows its own identity
            with open(env_path, "a") as f:
                f.write(f"export _CMUX_CLOSE_CMD={shlex.quote(f'{_CMUX_BIN} close-surface --surface {surface_ref}')}\n")
                f.write(f"export CMUX_WORKSPACE_ID={shlex.quote(parent_workspace)}\n")
                f.write(f"export CMUX_SURFACE_ID={shlex.quote(surface_ref)}\n")

            # Source the launcher so env vars land in the shell process
            subprocess.run(
                [_CMUX_BIN, "send", "--surface", surface_ref, "--", f"source {shlex.quote(launcher_path)}\n"],
                capture_output=True, text=True, timeout=10,
            )

            cmux_handle = surface_ref
        else:
            # --- Workspace mode: each agent gets its own sidebar workspace ---
            try:
                launch = subprocess.run(
                    [_CMUX_BIN, "new-workspace", "--cwd", work_dir,
                     "--command", f"bash {shlex.quote(launcher_path)}"],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
            except subprocess.TimeoutExpired:
                os.unlink(launcher_path)
                os.unlink(env_path)
                return "Error: cmux new-workspace timed out after 30s"

            if launch.returncode != 0:
                os.unlink(launcher_path)
                os.unlink(env_path)
                stderr = launch.stderr.strip() if launch.stderr else ""
                return f"Error: failed to launch cmux workspace: {stderr}"

            # Parse workspace ref from stdout: "OK workspace:N"
            workspace_ref = None
            stdout = launch.stdout.strip()
            match = re.search(r"(workspace:\S+)", stdout)
            if match:
                workspace_ref = match.group(1)

            # Rename workspace to team-agent format (display name only)
            if workspace_ref:
                subprocess.run(
                    [_CMUX_BIN, "rename-workspace", "--workspace", workspace_ref, workspace_name],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
            # IMPORTANT: Use workspace_ref for ALL subsequent cmux operations.
            cmux_handle = workspace_ref or workspace_name

            # Override CMUX_WORKSPACE_ID in env file so spawned shell knows its
            # own workspace, not the parent's. The env file is sourced at startup.
            if workspace_ref:
                with open(env_path, "a") as f:
                    f.write(f"export CMUX_WORKSPACE_ID={shlex.quote(workspace_ref)}\n")

        # Load config for readiness timeouts (both modes need this)
        from clawteam.config import load_config
        cfg = load_config()

        # Set team badge in sidebar (cosmetic — failure must not block spawn)
        # For tabs (surface mode), badge goes on the parent workspace
        # Clear stale badges first to prevent accumulation from previous spawns
        badge_target = parent_workspace if is_surface else cmux_handle
        if badge_target:
            try:
                subprocess.run(
                    [_CMUX_BIN, "clear-status", f"agent-{agent_name}", "--workspace", badge_target],
                    capture_output=True, text=True, timeout=3,
                )
            except (subprocess.TimeoutExpired, OSError):
                pass
            try:
                is_sidequest = team_name.startswith("sq") or team_name.startswith("sidequest")
                icon = "magnifyingglass" if is_sidequest else "hammer"
                color = "#007aff" if is_sidequest else "#ff9500"
                # One badge: icon shows type, text shows what it's doing
                short_name = agent_name[:60]
                subprocess.run(
                    [_CMUX_BIN, "set-status", f"agent-{agent_name}", short_name,
                     "--icon", icon, "--color", color, "--workspace", badge_target],
                    capture_output=True, text=True, timeout=5,
                )
            except (subprocess.TimeoutExpired, OSError):
                pass  # badge failure is cosmetic, don't block spawn

        # --- Workspace-only post-spawn: focus restore, visibility ---
        if not is_surface:

            # Restore focus to previous workspace to avoid focus steal
            if previous_workspace:
                subprocess.run(
                    [_CMUX_BIN, "select-workspace", "--workspace", previous_workspace],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )

            pane_ready_timeout = min(cfg.spawn_ready_timeout, max(15.0, cfg.spawn_prompt_delay + 2.0))
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

        # Codex update dismissal — applies to both workspace and surface modes
        if post_launch_prompt and is_codex_command(normalized_command):
            _dismiss_codex_update_prompt_if_present(
                cmux_handle,
                normalized_command,
                is_surface=is_surface,
                timeout_seconds=cfg.spawn_ready_timeout,
                poll_interval_seconds=0.2,
            )

        _confirm_trust_if_prompted(
            cmux_handle,
            normalized_command,
            is_surface=is_surface,
            timeout_seconds=cfg.spawn_ready_timeout,
        )

        # --- Unified readiness + prompt injection (G2, G3) ---
        inject_text = post_launch_prompt
        if not inject_text and prompt:
            # Only inject raw prompt for CLIs that don't embed it in the command
            if not (
                is_codex_command(normalized_command)
                or is_nanobot_command(normalized_command)
                or is_gemini_command(normalized_command)
                or is_kimi_command(normalized_command)
                or is_qwen_command(normalized_command)
                or is_opencode_command(normalized_command)
            ):
                inject_text = prompt

        if inject_text:
            ready = _wait_for_ready(
                cmux_handle,
                is_surface=is_surface,
                timeout_seconds=cfg.spawn_ready_timeout,
                fallback_delay=cfg.spawn_prompt_delay,
            )
            if not _inject_prompt(cmux_handle, inject_text, is_surface):
                flag_name = "--surface" if is_surface else "--workspace"
                return (
                    f"Warning: Agent '{agent_name}' {'surface' if is_surface else 'workspace'} "
                    f"created but prompt injection failed. "
                    f"CLI {'was' if ready else 'was NOT'} ready. "
                    f"Send prompt manually: cmux send {flag_name} {cmux_handle} '<prompt>' && "
                    f"cmux send-key {flag_name} {cmux_handle} Enter"
                )

        self._agents[agent_name] = cmux_handle

        # Persist spawn info for liveness checking
        from clawteam.spawn.registry import register_agent
        register_agent(
            team_name=team_name,
            agent_name=agent_name,
            backend="cmux",
            tmux_target=workspace_name,  # reuse field for workspace name
            pid=-1,  # cmux doesn't expose pane PIDs; -1 sentinel skips PID liveness check
            command=list(final_command),
        )

        if is_surface:
            return f"Agent '{agent_name}' spawned as tab in workspace '{parent_workspace}'"
        return f"Agent '{agent_name}' spawned in cmux workspace '{workspace_name}'"

    def list_running(self) -> list[dict[str, str]]:
        return [
            {"name": name, "target": workspace, "backend": "cmux"}
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


def _confirm_trust_if_prompted(
    handle: str,
    command: list[str],
    is_surface: bool = False,
    timeout_seconds: float = 5.0,
    poll_interval_seconds: float = 0.2,
) -> bool:
    """Acknowledge startup confirmation prompts for interactive CLIs.

    Claude Code, Codex, and Gemini can stop at a directory trust prompt when
    launched in a fresh git worktree.  Detect and dismiss before prompt
    injection.  Works for both workspaces and surfaces.
    """
    if not (is_claude_command(command) or is_codex_command(command) or is_gemini_command(command)):
        return False

    flag = "--surface" if is_surface else "--workspace"
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        screen_text = _read_screen(handle, is_surface=is_surface).lower()
        action = _startup_prompt_action(command, screen_text)
        if action == "enter":
            subprocess.run(
                [_CMUX_BIN, "send-key", flag, handle, "Enter"],
                capture_output=True, text=True, timeout=5,
            )
            time.sleep(0.5)
            return True
        if action == "down-enter":
            subprocess.run(
                [_CMUX_BIN, "send-key", flag, handle, "Down"],
                capture_output=True, text=True, timeout=5,
            )
            time.sleep(0.2)
            subprocess.run(
                [_CMUX_BIN, "send-key", flag, handle, "Enter"],
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
    is_surface: bool = False,
    timeout_seconds: float = 5.0,
    poll_interval_seconds: float = 0.2,
) -> bool:
    """Dismiss the Codex update gate if it is blocking the interactive UI."""
    if not is_codex_command(command):
        return False

    flag = "--surface" if is_surface else "--workspace"
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        screen_text = _read_screen(workspace_name, is_surface=is_surface).lower()
        if _looks_like_codex_update_prompt(screen_text):
            subprocess.run(
                [_CMUX_BIN, "send-key", flag, workspace_name, "Enter"],
                capture_output=True, text=True, timeout=5,
            )
            time.sleep(0.5)
            return True

        if screen_text and "openai codex" in screen_text:
            return False

        time.sleep(poll_interval_seconds)
    return False


def verify_and_cleanup(team_name: str, agent_name: str = "builder") -> str:
    """Verify build work landed, then destroy worktree + workspace.

    Gate pipeline: clean worktree -> pushed -> PR merged -> destroy.
    Returns a status string: success message or BLOCKED with reason.
    """
    try:
        return _verify_and_cleanup_inner(team_name, agent_name)
    except subprocess.TimeoutExpired as e:
        return f"BLOCKED: git command timed out ({e.cmd}). Check for lock files."
    except OSError as e:
        return f"BLOCKED: OS error during cleanup: {e}"


def _verify_and_cleanup_inner(team_name: str, agent_name: str) -> str:
    worktree = os.path.expanduser(f"~/.clawteam/workspaces/{team_name}/{agent_name}")
    branch = f"clawteam/{team_name}/{agent_name}"
    workspace = f"{team_name}-{agent_name}"

    # Gate 0: gh CLI required — refuse to destroy without PR verification
    gh_path = shutil.which("gh")
    if not gh_path:
        return (
            f"BLOCKED: gh CLI not found — cannot verify PR status before cleanup. "
            f"Install gh or clean up manually."
        )

    worktree_exists = os.path.isdir(worktree)

    if worktree_exists:
        # Gate 1: worktree clean?
        dirty = subprocess.run(
            ["git", "-C", worktree, "status", "--porcelain"],
            capture_output=True, text=True, timeout=10,
        ).stdout.strip()
        if dirty:
            return f"BLOCKED: Uncommitted work in {worktree}:\n{dirty}"

        # Gate 2: branch pushed? (skip if upstream ref gone)
        upstream_check = subprocess.run(
            ["git", "-C", worktree, "rev-parse", "--verify", "@{u}"],
            capture_output=True, text=True, timeout=10,
        )
        if upstream_check.returncode == 0:
            unpushed = subprocess.run(
                ["git", "-C", worktree, "log", "--oneline", "@{u}..HEAD"],
                capture_output=True, text=True, timeout=10,
            ).stdout.strip()
            if unpushed:
                return f"BLOCKED: Unpushed commits on {branch}:\n{unpushed}"

    # Gate 3: PR merged? (runs even if worktree gone)
    merged = subprocess.run(
        ["gh", "pr", "list", "--head", branch, "--state", "merged", "--json", "number"],
        capture_output=True, text=True, timeout=15,
    )
    if merged.returncode == 0 and merged.stdout.strip() not in ("", "[]"):
        pass  # merged — continue to cleanup
    else:
        open_pr = subprocess.run(
            ["gh", "pr", "list", "--head", branch, "--state", "open", "--json", "number,url"],
            capture_output=True, text=True, timeout=15,
        )
        if open_pr.returncode == 0 and open_pr.stdout.strip() not in ("", "[]"):
            return f"BLOCKED: PR not yet merged: {open_pr.stdout.strip()}"
        return f"BLOCKED: No PR found for branch {branch}"

    # All gates passed — destroy
    messages = []

    if worktree_exists:
        subprocess.run(["git", "worktree", "remove", worktree, "--force"],
                       capture_output=True, timeout=30)
        messages.append("worktree removed")

    delete_result = subprocess.run(
        ["git", "push", "origin", "--delete", branch],
        capture_output=True, timeout=15,
    )
    if delete_result.returncode == 0:
        messages.append("remote branch deleted")
    else:
        messages.append("remote branch already gone")

    subprocess.run([_CMUX_BIN, "close-workspace", "--workspace", workspace],
                   capture_output=True, text=True, timeout=5)
    messages.append("workspace closed")

    subprocess.run(["clawteam", "workspace", "cleanup", team_name],
                   capture_output=True, text=True, timeout=10)
    messages.append("team cleaned up")

    return f"Verified and cleaned: {', '.join(messages)}."
