"""Tmux spawn backend - launches agents in tmux windows for visual monitoring."""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import tempfile
import time
from xml.sax.saxutils import escape

from clawteam.spawn.adapters import (
    NativeCliAdapter,
    is_claude_command,
    is_codex_command,
    is_gemini_command,
    is_kimi_command,
    is_nanobot_command,
    is_opencode_command,
    is_pi_command,
    is_qwen_command,
)
from clawteam.spawn.base import SpawnBackend
from clawteam.spawn.cli_env import build_spawn_path, resolve_clawteam_executable
from clawteam.spawn.command_validation import validate_spawn_command

_SHELL_ENV_KEY_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")


class TmuxBackend(SpawnBackend):
    """Spawn agents in tmux windows for visual monitoring.

    Each agent gets its own tmux window in a session named ``clawteam-{team}``.
    Agents run in interactive mode so their work is visible in the tmux pane.
    """

    def __init__(self):
        self._agents: dict[str, str] = {}  # agent_name -> tmux target
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
        if not shutil.which("tmux"):
            return "Error: tmux not installed"

        session_name = f"clawteam-{team_name}"
        clawteam_bin = resolve_clawteam_executable()
        env_vars = os.environ.copy()
        # Interactive CLIs like Codex refuse to start when TERM=dumb is inherited
        # from a non-interactive shell. tmux provides a real terminal, so we
        # normalize TERM to a sensible value before exporting it into the pane.
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
        if system_prompt and (is_claude_command(normalized_command) or is_pi_command(normalized_command)):
            insert_at = final_command.index("-p") if "-p" in final_command else len(final_command)
            final_command[insert_at:insert_at] = ["--append-system-prompt", system_prompt]

        command_error = validate_spawn_command(validation_command, path=env_vars["PATH"], cwd=cwd)
        if command_error:
            return command_error

        # tmux launches the command through a shell, so only shell-safe
        # environment names can be exported. The current host environment on
        # WSL includes names like `PROGRAMFILES(X86)`, which would abort the
        # shell before the pane becomes observable.
        export_vars = {k: v for k, v in env_vars.items() if _SHELL_ENV_KEY_RE.fullmatch(k)}
        export_str = "; ".join(f"export {k}={shlex.quote(v)}" for k, v in export_vars.items())

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

        from clawteam.config import load_config

        cfg = load_config()
        pane_ready_timeout = min(cfg.spawn_ready_timeout, max(4.0, cfg.spawn_prompt_delay + 2.0))
        if not _wait_for_tmux_pane(
            target,
            timeout_seconds=pane_ready_timeout,
            poll_interval_seconds=0.2,
        ):
            return (
                f"Error: tmux pane for '{normalized_command[0]}' did not become visible "
                f"within {pane_ready_timeout:.1f}s. Verify the CLI works standalone before "
                "using it with clawteam spawn."
            )

        _confirm_workspace_trust_if_prompted(
            target,
            normalized_command,
            timeout_seconds=cfg.spawn_ready_timeout,
        )

        if post_launch_prompt and is_codex_command(normalized_command):
            _dismiss_codex_update_prompt_if_present(
                target,
                normalized_command,
                timeout_seconds=pane_ready_timeout,
                poll_interval_seconds=0.2,
            )

        if post_launch_prompt:
            _wait_for_cli_ready(
                target,
                timeout_seconds=cfg.spawn_ready_timeout,
                fallback_delay=cfg.spawn_prompt_delay,
            )
            _inject_prompt_via_buffer(target, agent_name, post_launch_prompt)
        elif (
            prompt
            and not is_codex_command(normalized_command)
            and not is_nanobot_command(normalized_command)
            and not is_gemini_command(normalized_command)
            and not is_kimi_command(normalized_command)
            and not is_qwen_command(normalized_command)
            and not is_opencode_command(normalized_command)
        ):
            # Other interactive TUIs still need the screen to be live before we
            # inject text via tmux send-keys.
            _wait_for_tui_ready(
                target,
                timeout=cfg.spawn_ready_timeout,
                fallback_delay=cfg.spawn_prompt_delay,
            )
            subprocess.run(
                ["tmux", "send-keys", "-t", target, prompt, "Enter"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

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
            command=list(final_command),
        )

        return f"Agent '{agent_name}' spawned in tmux ({target})"

    def list_running(self) -> list[dict[str, str]]:
        return [
            {"name": name, "target": target, "backend": "tmux"}
            for name, target in self._agents.items()
        ]

    def inject_runtime_message(self, team: str, agent_name: str, envelope) -> tuple[bool, str]:
        """Best-effort runtime injection into an existing tmux agent pane."""
        if not shutil.which("tmux"):
            return False, "tmux not installed"

        target = f"{self.session_name(team)}:{agent_name}"
        probe = subprocess.run(
            ["tmux", "list-panes", "-t", target, "-F", "#{pane_id}"],
            capture_output=True,
            text=True,
        )
        if probe.returncode != 0 or not probe.stdout.strip():
            return False, f"tmux target '{target}' not found"

        try:
            _inject_prompt_via_buffer(
                target,
                agent_name,
                _render_runtime_notification(envelope),
            )
        except Exception as exc:
            return False, f"runtime injection failed for '{target}': {exc}"

        return True, f"Injected runtime notification into {target}"

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
    """Acknowledge startup confirmation prompts for interactive CLIs.

    Claude Code and Codex can stop at a directory trust prompt when launched in
    a fresh git worktree. Claude can also pause on a confirmation dialog when
    `--dangerously-skip-permissions` is enabled. Detect these screens before
    any prompt injection so the interactive TUI remains intact.
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
        action = _startup_prompt_action(command, pane_text)
        if action == "enter":
            subprocess.run(
                ["tmux", "send-keys", "-t", target, "Enter"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            time.sleep(0.5)
            return True
        if action == "down-enter":
            subprocess.run(
                ["tmux", "send-keys", "-t", target, "-l", "\x1b[B"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            time.sleep(0.2)
            subprocess.run(
                ["tmux", "send-keys", "-t", target, "Enter"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            time.sleep(0.5)
            return True

        time.sleep(poll_interval_seconds)

    return False


def _startup_prompt_action(command: list[str], pane_text: str) -> str | None:
    """Return the key action needed to dismiss a startup confirmation prompt."""
    if _looks_like_claude_skip_permissions_prompt(command, pane_text):
        return "down-enter"
    if _looks_like_workspace_trust_prompt(command, pane_text):
        return "enter"
    return None


def _wait_for_tmux_pane(
    target: str,
    timeout_seconds: float = 5.0,
    poll_interval_seconds: float = 0.2,
) -> bool:
    """Poll tmux until the target pane exists and is observable."""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        pane = subprocess.run(
            ["tmux", "list-panes", "-t", target, "-F", "#{pane_id}"],
            capture_output=True,
            text=True,
        )
        if pane.returncode == 0 and pane.stdout.strip():
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


def _looks_like_claude_skip_permissions_prompt(command: list[str], pane_text: str) -> bool:
    """Return True when Claude is waiting for the dangerous-permissions confirmation."""
    if not pane_text or not is_claude_command(command):
        return False

    has_accept_choice = "yes, i accept" in pane_text
    has_permissions_warning = (
        "dangerously-skip-permissions" in pane_text
        or "skip permissions" in pane_text
        or "permission" in pane_text
        or "approval" in pane_text
    )
    return has_accept_choice and has_permissions_warning


def _looks_like_codex_update_prompt(pane_text: str) -> bool:
    """Return True when Codex is showing the update gate before the main TUI."""
    if not pane_text:
        return False

    return (
        "update available" in pane_text
        and "press enter to continue" in pane_text
        and ("update now" in pane_text or "skip until next version" in pane_text)
    )


def _dismiss_codex_update_prompt_if_present(
    target: str,
    command: list[str],
    timeout_seconds: float = 5.0,
    poll_interval_seconds: float = 0.2,
) -> bool:
    """Dismiss the Codex update gate if it is blocking the interactive UI."""
    if not is_codex_command(command):
        return False

    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        pane = subprocess.run(
            ["tmux", "capture-pane", "-p", "-t", target],
            capture_output=True,
            text=True,
        )
        pane_text = pane.stdout.lower() if pane.returncode == 0 else ""
        if _looks_like_codex_update_prompt(pane_text):
            subprocess.run(
                ["tmux", "send-keys", "-t", target, "Enter"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            time.sleep(0.5)
            return True

        if pane_text and "openai codex" in pane_text:
            return False

        time.sleep(poll_interval_seconds)

    return False


def _wait_for_cli_ready(
    target: str,
    timeout_seconds: float = 30.0,
    fallback_delay: float = 2.0,
    poll_interval: float = 1.0,
) -> bool:
    """Poll tmux pane until an interactive CLI shows an input prompt.

    Uses two complementary heuristics:

    1. **Prompt indicators** — common prompt characters (``❯``, ``>``,
       ``›``) or well-known hint lines in the last few visible lines.
    2. **Content stabilization** — if the pane output has stopped changing
       for two consecutive polls and contains visible text, the CLI has
       likely finished initialisation and is waiting for input.

    Returns True when ready, False on timeout (caller should still
    attempt injection as a best-effort).
    """
    deadline = time.monotonic() + timeout_seconds
    last_content = ""
    stable_count = 0

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
    time.sleep(fallback_delay)
    return False


def _wait_for_tui_ready(
    target: str,
    timeout: float = 30.0,
    fallback_delay: float = 2.0,
    poll_interval: float = 0.5,
) -> None:
    """Poll the tmux pane until the TUI appears ready, then return.

    This is used for interactive CLIs that still rely on tmux send-keys prompt
    injection. When readiness is not detected before ``timeout``, we keep the
    previous fallback behaviour and sleep for ``fallback_delay`` seconds.
    """

    ready_hints = ("╭", "╔", "┌", "│", "║", "✓", ">", "❯", "›")
    time.sleep(0.5)

    deadline = time.time() + timeout
    while time.time() < deadline:
        result = subprocess.run(
            ["tmux", "capture-pane", "-t", target, "-p"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 and any(hint in result.stdout for hint in ready_hints):
            return
        time.sleep(poll_interval)

    time.sleep(fallback_delay)


def _inject_prompt_via_buffer(
    target: str,
    agent_name: str,
    prompt: str,
) -> None:
    """Inject a prompt into a tmux pane via ``load-buffer`` / ``paste-buffer``.

    Using a temp file avoids the shell-escaping pitfalls of ``send-keys`` for
    multi-line or special-character prompts. Two Enter keystrokes are sent
    after the paste to confirm and submit.
    """
    buf_name = f"prompt-{agent_name}"
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, prefix="clawteam-prompt-"
    ) as f:
        f.write(prompt)
        tmp_path = f.name

    try:
        subprocess.run(
            ["tmux", "load-buffer", "-b", buf_name, tmp_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        subprocess.run(
            ["tmux", "paste-buffer", "-b", buf_name, "-t", target],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        time.sleep(0.5)
        subprocess.run(
            ["tmux", "send-keys", "-t", target, "Enter"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        time.sleep(0.3)
        subprocess.run(
            ["tmux", "send-keys", "-t", target, "Enter"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        subprocess.run(
            ["tmux", "delete-buffer", "-b", buf_name],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    finally:
        os.unlink(tmp_path)

def _render_runtime_notification(envelope) -> str:
    summary = str(getattr(envelope, "summary", "") or "").strip()
    if not summary:
        summary = "Runtime update"

    evidence = getattr(envelope, "evidence", []) or []
    if isinstance(evidence, str):
        evidence = [evidence]
    evidence_block = "\n".join(str(item) for item in evidence if item)

    lines = [
        '<clawteam_notification version="1"',
        f'  source="{escape(str(getattr(envelope, "source", "system") or "system"))}"',
        f'  target="{escape(str(getattr(envelope, "target", "") or ""))}"',
        f'  channel="{escape(str(getattr(envelope, "channel", "direct") or "direct"))}"',
        f'  priority="{escape(str(getattr(envelope, "priority", "medium") or "medium"))}">',
        "<summary>",
        escape(summary),
        "</summary>",
    ]

    if evidence_block:
        lines.extend(["<evidence>", escape(evidence_block), "</evidence>"])
    recommended_next_action = str(getattr(envelope, "recommended_next_action", "") or "").strip()
    if recommended_next_action:
        lines.extend(
            [
                "<recommended_next_action>",
                escape(recommended_next_action),
                "</recommended_next_action>",
            ]
        )

    lines.append("</clawteam_notification>")
    return "\n".join(lines)
