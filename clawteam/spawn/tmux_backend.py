"""Tmux spawn backend - launches agents in tmux windows for visual monitoring."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import tempfile
import time

from clawteam.spawn.base import SpawnBackend
from clawteam.spawn.cli_env import build_spawn_path, resolve_clawteam_executable
from clawteam.spawn.command_validation import (
    command_has_workspace_arg,
    is_claude_command,
    is_codex_command,
    is_gemini_command,
    is_kimi_command,
    is_nanobot_command,
    is_opencode_command,
    is_qwen_command,
    normalize_spawn_command,
    validate_spawn_command,
)


class TmuxBackend(SpawnBackend):
    """Spawn agents in tmux windows for visual monitoring.

    Each agent gets its own tmux window in a session named ``clawteam-{team}``.
    Agents run in interactive mode so their work is visible in the tmux pane.
    """

    def __init__(self):
        self._agents: dict[str, str] = {}  # agent_name -> tmux target

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
        if not shutil.which("tmux"):
            return "Error: tmux not installed"

        session_name = f"clawteam-{team_name}"
        clawteam_bin = resolve_clawteam_executable()
        env_vars = {
            "CLAWTEAM_AGENT_ID": agent_id,
            "CLAWTEAM_AGENT_NAME": agent_name,
            "CLAWTEAM_AGENT_TYPE": agent_type,
            "CLAWTEAM_TEAM_NAME": team_name,
            "CLAWTEAM_AGENT_LEADER": "0",
        }
        # Propagate user if set
        user = os.environ.get("CLAWTEAM_USER", "")
        if user:
            env_vars["CLAWTEAM_USER"] = user
        # Propagate transport if set
        transport = os.environ.get("CLAWTEAM_TRANSPORT", "")
        if transport:
            env_vars["CLAWTEAM_TRANSPORT"] = transport
        if cwd:
            env_vars["CLAWTEAM_WORKSPACE_DIR"] = cwd
        if env:
            env_vars.update(env)
        env_vars["PATH"] = build_spawn_path(env_vars.get("PATH", os.environ.get("PATH")))
        if os.path.isabs(clawteam_bin):
            env_vars.setdefault("CLAWTEAM_BIN", clawteam_bin)

        normalized_command = normalize_spawn_command(command)

        command_error = validate_spawn_command(normalized_command, path=env_vars["PATH"], cwd=cwd)
        if command_error:
            return command_error

        export_str = "; ".join(f"export {k}={shlex.quote(v)}" for k, v in env_vars.items())

        # Build the command (without prompt — we'll send it via send-keys)
        final_command = list(normalized_command)
        if skip_permissions:
            if is_claude_command(normalized_command) or is_qwen_command(normalized_command):
                final_command.append("--dangerously-skip-permissions")
            elif is_codex_command(normalized_command):
                final_command.append("--dangerously-bypass-approvals-and-sandbox")
            elif is_gemini_command(normalized_command) or is_kimi_command(normalized_command) or is_opencode_command(normalized_command):
                final_command.append("--yolo")

        if is_nanobot_command(normalized_command):
            if cwd and not command_has_workspace_arg(normalized_command):
                final_command.extend(["-w", cwd])
            if prompt:
                final_command.extend(["-m", prompt])
        elif prompt and is_codex_command(normalized_command):
            final_command.append(prompt)
        elif prompt and is_gemini_command(normalized_command):
            final_command.extend(["-p", prompt])

        cmd_str = " ".join(shlex.quote(c) for c in final_command)
        # Append on-exit hook: runs immediately when agent process exits
        exit_cmd = shlex.quote(clawteam_bin) if os.path.isabs(clawteam_bin) else "clawteam"
        exit_hook = (
            f"{exit_cmd} lifecycle on-exit --team {shlex.quote(team_name)} "
            f"--agent {shlex.quote(agent_name)}"
        )
        # Unset Claude nesting-detection env vars so spawned claude agents
        # don't refuse to start when the leader is itself a claude session.
        unset_clause = "unset CLAUDECODE CLAUDE_CODE_ENTRYPOINT CLAUDE_CODE_SESSION 2>/dev/null; "
        if cwd:
            full_cmd = f"{unset_clause}{export_str}; cd {shlex.quote(cwd)} && {cmd_str}; {exit_hook}"
        else:
            full_cmd = f"{unset_clause}{export_str}; {cmd_str}; {exit_hook}"

        # Check if tmux session exists
        check = subprocess.run(
            ["tmux", "has-session", "-t", session_name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        target = f"{session_name}:{agent_name}"

        if check.returncode != 0:
            launch = subprocess.run(
                ["tmux", "new-session", "-d", "-s", session_name, "-n", agent_name, full_cmd],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        else:
            launch = subprocess.run(
                ["tmux", "new-window", "-t", session_name, "-n", agent_name, full_cmd],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        if launch.returncode != 0:
            stderr = launch.stderr.decode() if isinstance(launch.stderr, bytes) else launch.stderr
            return f"Error: failed to launch tmux session: {(stderr or '').strip()}"

        # Detect commands that die before the session becomes observable.
        time.sleep(0.3)
        pane_check = subprocess.run(
            ["tmux", "list-panes", "-t", target, "-F", "#{pane_id}"],
            capture_output=True,
            text=True,
        )
        if pane_check.returncode != 0 or not pane_check.stdout.strip():
            return (
                f"Error: agent command '{normalized_command[0]}' exited immediately after launch. "
                "Verify the CLI works standalone before using it with clawteam spawn."
            )

        _confirm_workspace_trust_if_prompted(target, normalized_command)

        # Inject prompt into the interactive TUI session.
        # CLIs whose prompt was already passed as a CLI argument (codex,
        # nanobot, gemini) are skipped here.
        _prompt_already_set = (
            is_codex_command(normalized_command)
            or is_nanobot_command(normalized_command)
            or is_gemini_command(normalized_command)
        )
        if prompt and not _prompt_already_set:
            _wait_for_cli_ready(target, normalized_command, timeout_seconds=30)
            _inject_prompt_via_buffer(target, agent_name, prompt, normalized_command)

        self._agents[agent_name] = target

        # Capture pane PID for robust liveness checking (survives tile operations)
        pane_pid = 0
        pid_result = subprocess.run(
            ["tmux", "list-panes", "-t", target, "-F", "#{pane_pid}"],
            capture_output=True, text=True,
        )
        if pid_result.returncode == 0 and pid_result.stdout.strip():
            try:
                pane_pid = int(pid_result.stdout.strip().splitlines()[0])
            except ValueError:
                pass

        # Persist spawn info for liveness checking
        from clawteam.spawn.registry import register_agent
        register_agent(
            team_name=team_name,
            agent_name=agent_name,
            backend="tmux",
            tmux_target=target,
            pid=pane_pid,
            command=list(normalized_command),
        )

        return f"Agent '{agent_name}' spawned in tmux ({target})"

    def list_running(self) -> list[dict[str, str]]:
        return [
            {"name": name, "target": target, "backend": "tmux"}
            for name, target in self._agents.items()
        ]

    @staticmethod
    def session_name(team_name: str) -> str:
        return f"clawteam-{team_name}"

    @staticmethod
    def tile_panes(team_name: str) -> str:
        """Merge all windows into one tiled view. Does NOT attach.

        Returns status message or error.
        """
        session = TmuxBackend.session_name(team_name)

        check = subprocess.run(
            ["tmux", "has-session", "-t", session],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if check.returncode != 0:
            return f"Error: tmux session '{session}' not found. No agents spawned for team '{team_name}'?"

        # Count current panes in window 0
        pane_count = subprocess.run(
            ["tmux", "list-panes", "-t", f"{session}:0"],
            capture_output=True, text=True,
        )
        num_panes = len(pane_count.stdout.strip().splitlines()) if pane_count.returncode == 0 else 0

        # Get windows
        result = subprocess.run(
            ["tmux", "list-windows", "-t", session, "-F", "#{window_index}"],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            return f"Error: failed to list windows: {result.stderr.strip()}"

        windows = result.stdout.strip().splitlines()

        # If already tiled (1 window, multiple panes), skip merge
        if len(windows) <= 1 and num_panes > 1:
            return f"Already tiled ({num_panes} panes) in {session}"

        if len(windows) > 1:
            first = windows[0]
            for w in windows[1:]:
                subprocess.run(
                    ["tmux", "join-pane", "-s", f"{session}:{w}", "-t", f"{session}:{first}", "-h"],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                )
            subprocess.run(
                ["tmux", "select-layout", "-t", f"{session}:{first}", "tiled"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )

        # Recount
        pane_count = subprocess.run(
            ["tmux", "list-panes", "-t", f"{session}:0"],
            capture_output=True, text=True,
        )
        final_panes = len(pane_count.stdout.strip().splitlines()) if pane_count.returncode == 0 else 0
        return f"Tiled {final_panes} panes in {session}"

    @staticmethod
    def attach_all(team_name: str) -> str:
        """Tile all windows into panes and attach to the session."""
        result = TmuxBackend.tile_panes(team_name)
        if result.startswith("Error"):
            return result

        session = TmuxBackend.session_name(team_name)
        subprocess.run(["tmux", "attach-session", "-t", session])
        return result


def _confirm_workspace_trust_if_prompted(
    target: str,
    command: list[str],
    timeout_seconds: float = 5.0,
    poll_interval_seconds: float = 0.2,
) -> bool:
    """Acknowledge first-run workspace trust prompts for interactive CLIs.

    Claude Code and Codex can stop at a directory trust prompt when launched in
    a fresh git worktree. Detect that specific screen before any prompt
    injection and accept it with a single Enter so the interactive TUI remains
    intact.
    """
    if not (is_claude_command(command) or is_codex_command(command) or is_gemini_command(command)):
        return False

    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        pane = subprocess.run(
            ["tmux", "capture-pane", "-p", "-t", target],
            capture_output=True,
            text=True,
        )
        pane_text = pane.stdout.lower() if pane.returncode == 0 else ""
        if _looks_like_workspace_trust_prompt(command, pane_text):
            subprocess.run(
                ["tmux", "send-keys", "-t", target, "Enter"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            time.sleep(0.5)
            return True

        time.sleep(poll_interval_seconds)

    return False


def _looks_like_workspace_trust_prompt(command: list[str], pane_text: str) -> bool:
    """Return True when the tmux pane is showing a trust confirmation dialog."""
    if not pane_text:
        return False

    if is_claude_command(command):
        return ("trust this folder" in pane_text or "trust the contents" in pane_text) and (
            "enter to confirm" in pane_text or "press enter" in pane_text or "enter to continue" in pane_text
        )

    if is_codex_command(command):
        return (
            "trust the contents of this directory" in pane_text
            and "press enter to continue" in pane_text
        )

    if is_gemini_command(command):
        return "trust folder" in pane_text or "trust parent folder" in pane_text

    return False


def _wait_for_cli_ready(
    target: str,
    command: list[str],
    timeout_seconds: float = 30.0,
    poll_interval: float = 1.0,
) -> bool:
    """Poll tmux pane until the CLI shows an input prompt.

    Uses CLI-specific prompt indicators when available, then falls back
    to a generic "pane content stabilized" heuristic so that future CLIs
    work without code changes.

    Returns True if ready detected, False on timeout (caller should
    still attempt injection as a best-effort).
    """
    prev_snapshot: str | None = None
    stable_count = 0
    # After 3 consecutive identical snapshots (~3 s) the TUI is likely idle.
    stable_threshold = 3

    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        pane = subprocess.run(
            ["tmux", "capture-pane", "-p", "-t", target],
            capture_output=True,
            text=True,
        )
        if pane.returncode != 0:
            time.sleep(poll_interval)
            continue

        text = pane.stdout
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        tail = lines[-10:] if len(lines) >= 10 else lines

        if _check_cli_ready_indicators(command, tail):
            return True

        # Generic fallback: content stabilization
        snapshot = "\n".join(tail)
        if snapshot and snapshot == prev_snapshot:
            stable_count += 1
            if stable_count >= stable_threshold:
                return True
        else:
            stable_count = 0
        prev_snapshot = snapshot

        time.sleep(poll_interval)
    return False


def _check_cli_ready_indicators(command: list[str], tail_lines: list[str]) -> bool:
    """Return True if the tail lines contain known ready indicators for
    the given CLI."""
    # Claude, qwen, kimi, and opencode all use TUI prompt characters.
    # The indicators below are shared across most modern AI CLI tools.
    for line in tail_lines:
        if line.startswith(("❯", ">", "›", "$", "%")):
            return True
        # Claude Code hint line
        if "Try " in line and "write a test" in line:
            return True
    return False


def _inject_prompt_via_buffer(
    target: str,
    agent_name: str,
    prompt: str,
    command: list[str],
) -> None:
    """Inject a prompt into a tmux pane using load-buffer / paste-buffer.

    This is safer than send-keys for multi-line prompts and avoids
    escaping issues with special characters.
    """
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, prefix="clawteam-prompt-"
    ) as f:
        f.write(prompt)
        tmp_path = f.name

    buf_name = f"prompt-{agent_name}"
    try:
        subprocess.run(
            ["tmux", "load-buffer", "-b", buf_name, tmp_path],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        subprocess.run(
            ["tmux", "paste-buffer", "-b", buf_name, "-t", target],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        # Most interactive CLIs need Enter to submit after paste.
        # Claude specifically needs a double-Enter (confirm + submit).
        time.sleep(0.5)
        subprocess.run(
            ["tmux", "send-keys", "-t", target, "Enter"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        if is_claude_command(command) or is_qwen_command(command):
            time.sleep(0.3)
            subprocess.run(
                ["tmux", "send-keys", "-t", target, "Enter"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
    finally:
        subprocess.run(
            ["tmux", "delete-buffer", "-b", buf_name],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
