"""Cmux spawn backend - launches agents in cmux workspaces for visual monitoring."""
# cmux backend v0.3.0 — send/send-key prompt injection, auto-close, exact workspace matching

from __future__ import annotations

import os
import re
import shlex
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
        # Parse workspace name from line: "  workspace:N  name  [selected]"
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
        import tempfile
        export_vars = {k: v for k, v in env_vars.items() if _SHELL_ENV_KEY_RE.fullmatch(k)}
        env_fd, env_path = tempfile.mkstemp(prefix="clawteam-env-", suffix=".sh")
        with os.fdopen(env_fd, "w") as f:
            for k, v in export_vars.items():
                f.write(f"export {k}={shlex.quote(v)}\n")
        os.chmod(env_path, 0o600)  # restrict read to owner

        cmd_str = " ".join(shlex.quote(c) for c in final_command)
        # On-exit hook: runs when agent process exits
        exit_cmd = shlex.quote(clawteam_bin) if os.path.isabs(clawteam_bin) else "clawteam"
        exit_hook = (
            f"{exit_cmd} lifecycle on-exit --team {shlex.quote(team_name)} "
            f"--agent {shlex.quote(agent_name)}"
        )
        # Auto-close cmux workspace after agent exits + lifecycle cleanup.
        ws_name = f"{team_name}-{agent_name}"
        cmux_cleanup = (
            f"echo '\\n[Agent exited. Workspace closes in 30s. Press Ctrl-C to keep.]'; "
            f"sleep 30 && {shlex.quote(_CMUX_BIN)} close-workspace --workspace {shlex.quote(ws_name)} 2>/dev/null"
        )
        # Source env from file (secrets stay off terminal), then delete the file
        env_source = f". {shlex.quote(env_path)} && rm -f {shlex.quote(env_path)}"
        unset_clause = "unset CLAUDECODE CLAUDE_CODE_ENTRYPOINT CLAUDE_CODE_SESSION 2>/dev/null; "
        if cwd:
            full_cmd = f"{unset_clause}{env_source}; cd {shlex.quote(cwd)} || exit 1; {cmd_str}; {exit_hook}; {cmux_cleanup}"
        else:
            full_cmd = f"{unset_clause}{env_source}; {cmd_str}; {exit_hook}; {cmux_cleanup}"

        # Remember current workspace to restore focus after spawn
        previous_workspace = _cmux_get_current_workspace()

        work_dir = cwd or os.getcwd()
        spawned_as_surface = False

        if parent_workspace:
            # --- Surface mode: spawn as a tab inside the parent workspace ---
            try:
                launch = subprocess.run(
                    [_CMUX_BIN, "new-surface", "--workspace", parent_workspace],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
            except subprocess.TimeoutExpired:
                return "Error: cmux new-surface timed out after 30s"

            if launch.returncode != 0:
                stderr = launch.stderr.strip() if launch.stderr else ""
                return f"Error: failed to create cmux surface: {stderr}"

            # Parse surface ref from stdout (e.g. "OK surface:N")
            surface_ref = None
            stdout = launch.stdout.strip()
            m = re.search(r"(surface:\S+)", stdout)
            if m:
                surface_ref = m.group(1)

            if not surface_ref:
                return f"Error: could not parse surface ref from cmux output: {stdout}"

            # Rename tab for identification
            subprocess.run(
                [_CMUX_BIN, "rename-tab", "--surface", surface_ref, workspace_name],
                capture_output=True, text=True, timeout=5,
            )

            # Write command to temp script — cmux send chokes on long commands.
            # Script self-deletes after sourcing so env vars land in the shell.
            script = tempfile.NamedTemporaryFile(
                mode="w", prefix="clawteam-surface-", suffix=".sh", delete=False,
            )
            script.write("#!/usr/bin/env bash\n")
            script.write(f"rm -f {shlex.quote(script.name)}\n")
            script.write(full_cmd + "\n")
            script.close()
            os.chmod(script.name, 0o700)

            subprocess.run(
                [_CMUX_BIN, "send", "--surface", surface_ref, "--", f"source {shlex.quote(script.name)}\n"],
                capture_output=True, text=True, timeout=10,
            )

            cmux_handle = surface_ref
            spawned_as_surface = True

            # Wait for CLI readiness, then inject prompt (same as workspace mode)
            if prompt or post_launch_prompt:
                from clawteam.config import load_config
                cfg = load_config()
                _wait_for_surface_ready(
                    surface_ref,
                    timeout_seconds=cfg.spawn_ready_timeout,
                    fallback_delay=cfg.spawn_prompt_delay,
                )
                inject_text = post_launch_prompt or prompt or ""
                if inject_text:
                    _inject_prompt_via_surface(surface_ref, inject_text)
        else:
            # --- Workspace mode: each agent gets its own sidebar workspace ---
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

        if not spawned_as_surface:
            # Set team badge in sidebar (cosmetic — failure must not block spawn)
            try:
                team_type = "side-quest" if team_name.startswith("sq-") else "build"
                icon = "magnifier" if team_type == "side-quest" else "hammer"
                color = "#007aff" if team_type == "side-quest" else "#ff9500"
                subprocess.run(
                    [_CMUX_BIN, "set-status", "team", team_name,
                     "--icon", icon, "--color", color, "--workspace", cmux_handle],
                    capture_output=True, text=True, timeout=5,
                )
                subprocess.run(
                    [_CMUX_BIN, "set-status", "role", agent_name,
                     "--icon", "sparkle", "--workspace", cmux_handle],
                    capture_output=True, text=True, timeout=5,
                )
            except (subprocess.TimeoutExpired, OSError):
                pass  # badge failure is cosmetic, don't block spawn

        # Restore focus to previous workspace to avoid focus steal
        if previous_workspace and not spawned_as_surface:
            subprocess.run(
                [_CMUX_BIN, "select-workspace", "--workspace", previous_workspace],
                capture_output=True,
                text=True,
                timeout=5,
            )

        # Surface mode: command already sent via cmux send, skip readiness/prompt injection.
        # Workspace mode: wait for workspace to appear, then inject prompt if needed.
        if not spawned_as_surface:
            from clawteam.config import load_config

            cfg = load_config()
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

            _confirm_workspace_trust_if_prompted(
                cmux_handle,
                normalized_command,
                timeout_seconds=cfg.spawn_ready_timeout,
            )

            if post_launch_prompt and is_codex_command(normalized_command):
                _dismiss_codex_update_prompt_if_present(
                    cmux_handle,
                    normalized_command,
                    timeout_seconds=pane_ready_timeout,
                    poll_interval_seconds=0.2,
                )

            if post_launch_prompt:
                ready = _wait_for_cli_ready(
                    cmux_handle,
                    timeout_seconds=cfg.spawn_ready_timeout,
                    fallback_delay=cfg.spawn_prompt_delay,
                )
                if not _inject_prompt_via_keys(cmux_handle, post_launch_prompt):
                    return (
                        f"Warning: Agent '{agent_name}' workspace created but prompt injection failed. "
                        f"CLI {'was' if ready else 'was NOT'} ready. "
                        f"Send prompt manually: cmux send --workspace {cmux_handle} '<prompt>' && "
                        f"cmux send-key --workspace {cmux_handle} Enter"
                    )
            elif (
                prompt
                and not is_codex_command(normalized_command)
                and not is_nanobot_command(normalized_command)
                and not is_gemini_command(normalized_command)
                and not is_kimi_command(normalized_command)
                and not is_qwen_command(normalized_command)
                and not is_opencode_command(normalized_command)
            ):
                ready = _wait_for_cli_ready(
                    cmux_handle,
                    timeout_seconds=cfg.spawn_ready_timeout,
                    fallback_delay=cfg.spawn_prompt_delay,
                )
                if not _inject_prompt_via_keys(cmux_handle, prompt):
                    return (
                        f"Warning: Agent '{agent_name}' workspace created but prompt injection failed. "
                        f"CLI {'was' if ready else 'was NOT'} ready. "
                        f"Send prompt manually: cmux send --workspace {cmux_handle} '<prompt>' && "
                        f"cmux send-key --workspace {cmux_handle} Enter"
                    )

        self._agents[agent_name] = cmux_handle

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

        if spawned_as_surface:
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
                [_CMUX_BIN, "send-key", "--workspace", workspace_name, "Enter"],
                capture_output=True, text=True, timeout=5,
            )
            time.sleep(0.5)
            return True
        if action == "down-enter":
            subprocess.run(
                [_CMUX_BIN, "send-key", "--workspace", workspace_name, "Down"],
                capture_output=True, text=True, timeout=5,
            )
            time.sleep(0.2)
            subprocess.run(
                [_CMUX_BIN, "send-key", "--workspace", workspace_name, "Enter"],
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
                [_CMUX_BIN, "send-key", "--workspace", workspace_name, "Enter"],
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
            # Claude Code in cmux shows "-- INSERT --" in the status bar when ready
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


def _inject_prompt_via_keys(workspace_name: str, prompt: str) -> bool:
    """Inject a prompt into a cmux workspace via send + send-key.

    Uses `cmux send` for text (types into terminal) and `cmux send-key Enter`
    to submit. Returns True if all commands succeeded.
    """
    # Write prompt text via temp file to handle multiline/special chars safely
    import tempfile
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write(prompt)
        prompt_file = f.name

    try:
        # Read prompt from file and send via cmux send
        with open(prompt_file) as f:
            prompt_text = f.read()

        result = subprocess.run(
            [_CMUX_BIN, "send", "--workspace", workspace_name, prompt_text],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return False

        time.sleep(0.5)

        # Press Enter to submit
        result = subprocess.run(
            [_CMUX_BIN, "send-key", "--workspace", workspace_name, "Enter"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            return False

        return True
    finally:
        import os
        os.unlink(prompt_file)


def _wait_for_surface_ready(
    surface_ref: str,
    timeout_seconds: float = 30.0,
    fallback_delay: float = 2.0,
    poll_interval: float = 1.0,
) -> bool:
    """Poll cmux surface until CLI shows an input prompt."""
    deadline = time.monotonic() + timeout_seconds
    last_content = ""
    stable_count = 0

    while time.monotonic() < deadline:
        try:
            result = subprocess.run(
                [_CMUX_BIN, "read-screen", "--surface", surface_ref],
                capture_output=True, text=True, timeout=5,
            )
            text = result.stdout if result.returncode == 0 else ""
        except (subprocess.TimeoutExpired, OSError):
            text = ""

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


def _inject_prompt_via_surface(surface_ref: str, prompt: str) -> bool:
    """Inject a prompt into a cmux surface via send + send-key Enter."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write(prompt)
        prompt_file = f.name

    try:
        with open(prompt_file) as f:
            prompt_text = f.read()

        # Send prompt text
        result = subprocess.run(
            [_CMUX_BIN, "send", "--surface", surface_ref, prompt_text],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return False

        time.sleep(0.5)

        # Submit with Enter via send-key
        result = subprocess.run(
            [_CMUX_BIN, "send-key", "--surface", surface_ref, "Enter"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            # Fallback: try \n in send text
            subprocess.run(
                [_CMUX_BIN, "send", "--surface", surface_ref, "\\n"],
                capture_output=True, text=True, timeout=5,
            )
        return True
    finally:
        os.unlink(prompt_file)
