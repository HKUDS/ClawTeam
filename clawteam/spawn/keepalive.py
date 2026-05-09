"""Helpers for resumable agent keepalive loops."""

from __future__ import annotations

import shlex
from pathlib import Path

from clawteam.spawn.command_validation import docker_wrapped_cli_name, normalize_spawn_command


def build_resume_command(command: list[str]) -> list[str]:
    """Return a resumable follow-up command for interactive CLIs."""
    normalized = normalize_spawn_command(command)
    if not normalized:
        return []

    if docker_wrapped_cli_name(normalized) == "nanobot":
        return []

    executable = Path(normalized[0]).name.lower()
    if executable in {"claude", "claude-code"}:
        return [normalized[0], "--continue"]
    if executable in {"codex", "codex-cli"}:
        return [normalized[0], "resume", "--last"]
    if executable == "gemini":
        return [normalized[0], "--resume", "latest"]
    if executable == "kimi":
        return [normalized[0], "--continue"]
    if executable in {"qwen", "qwen-code"}:
        return [normalized[0], "--continue"]
    if executable == "opencode":
        return [normalized[0], "--continue"]
    if executable == "pi":
        return [normalized[0], "--continue"]
    if executable == "openclaw":
        # OpenClaw resumes via --session-id (injected by NativeCliAdapter),
        # so the resume command is just the base `openclaw agent` invocation.
        return [normalized[0], "agent"]
    return []


def build_keepalive_resume_prompt(team_name: str, agent_name: str) -> str:
    """Return a generic resume instruction for long-running worker keepalive."""
    return (
        "ClawTeam resumed you after a clean exit because keepalive is enabled.\n"
        "Before you exit again, re-check your assigned tasks and inbox.\n"
        f"- Run `clawteam task list {team_name} --owner {agent_name}`.\n"
        f"- Run `clawteam inbox receive {team_name} --agent {agent_name}`.\n"
        "- If you previously started a daemon, watcher, or background loop for an ongoing job, "
        "verify it is healthy and keep acting as its watchdog/reporter instead of treating the "
        "first turn as the end of the job.\n"
        f"- If you are truly idle, notify the leader with `clawteam lifecycle idle {team_name}` "
        "and keep polling for new work until shutdown is explicitly approved."
    )


def build_keepalive_shell_command(
    initial_command: list[str],
    *,
    resume_command: list[str],
    clawteam_bin: str,
    team_name: str,
    agent_name: str,
    keepalive: bool,
) -> str:
    """Build a POSIX shell command that keeps resumable agents alive."""
    cmd_str = " ".join(shlex.quote(c) for c in initial_command)
    exit_cmd = shlex.quote(clawteam_bin) if clawteam_bin.startswith("/") else clawteam_bin
    exit_hook = (
        f'CLAWTEAM_EXIT_CODE="$__ct_status" {exit_cmd} lifecycle on-exit '
        f'--team {shlex.quote(team_name)} --agent {shlex.quote(agent_name)}'
    )

    if not keepalive or not resume_command:
        return f"{cmd_str}; __ct_status=$?; {exit_hook}; exit $__ct_status"

    resume_str = " ".join(shlex.quote(c) for c in resume_command)
    should_keepalive = (
        f"{exit_cmd} lifecycle should-keepalive "
        f"--team {shlex.quote(team_name)} --agent {shlex.quote(agent_name)}"
    )

    return (
        f'__ct_cmd={shlex.quote(cmd_str)}; '
        f'__ct_resume={shlex.quote(resume_str)}; '
        "while true; do "
        'eval "$__ct_cmd"; '
        "__ct_status=$?; "
        f"{exit_hook}; "
        'if [ "$__ct_status" -eq 0 ] && '
        f"{should_keepalive}; "
        'then __ct_cmd="$__ct_resume"; sleep 1; continue; fi; '
        "exit $__ct_status; "
        "done"
    )
