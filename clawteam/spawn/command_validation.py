"""Validation and classification helpers for spawned agent commands."""

from __future__ import annotations

import os
import shutil
from pathlib import Path


def validate_spawn_command(
    command: list[str],
    *,
    path: str | None = None,
    cwd: str | None = None,
) -> str | None:
    """Return an error string when the agent command is not executable."""

    if not command:
        return "Error: no agent command specified"

    executable = command[0]
    separators = tuple(sep for sep in (os.sep, os.altsep) if sep)

    if any(sep in executable for sep in separators):
        candidate = Path(executable).expanduser()
        if not candidate.is_absolute() and cwd:
            candidate = Path(cwd) / candidate
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return None
        return f"Error: executable '{executable}' not found or not executable"

    if shutil.which(executable, path=path):
        return None

    return (
        f"Error: command '{executable}' not found in PATH. "
        "Install the agent CLI first or pass an executable path."
    )


def normalize_spawn_command(command: list[str]) -> list[str]:
    """Normalize shorthand agent commands to their interactive entrypoints."""

    if not command:
        return []

    executable = Path(command[0]).name
    if executable == "nanobot" and len(command) == 1:
        return [command[0], "agent"]
    if executable == "openclaw" and len(command) == 1:
        return [command[0], "agent", "--local"]

    return list(command)


# ---------------------------------------------------------------------------
# Command type detection helpers (shared by tmux and subprocess backends)
# ---------------------------------------------------------------------------

def _cmd_basename(command: list[str]) -> str:
    """Extract the basename of the first element of a command list."""
    if not command:
        return ""
    return command[0].rsplit("/", 1)[-1]


def is_claude_command(command: list[str]) -> bool:
    """Check if the command is a claude CLI invocation."""
    return _cmd_basename(command) in ("claude", "claude-code")


def is_codex_command(command: list[str]) -> bool:
    """Check if the command is a codex CLI invocation."""
    return _cmd_basename(command) in ("codex", "codex-cli")


def is_nanobot_command(command: list[str]) -> bool:
    """Check if the command is a nanobot CLI invocation."""
    return _cmd_basename(command) == "nanobot"


def is_gemini_command(command: list[str]) -> bool:
    """Check if the command is a Gemini CLI invocation."""
    return _cmd_basename(command) == "gemini"


def is_kimi_command(command: list[str]) -> bool:
    """Check if the command is a Kimi CLI invocation."""
    return _cmd_basename(command) == "kimi"


def is_qwen_command(command: list[str]) -> bool:
    """Check if the command is a Qwen Code CLI invocation."""
    return _cmd_basename(command) in ("qwen", "qwen-code")


def is_opencode_command(command: list[str]) -> bool:
    """Check if the command is an OpenCode CLI invocation."""
    return _cmd_basename(command) == "opencode"


def is_pi_command(command: list[str]) -> bool:
    """Check if the command is a pi-coding-agent CLI invocation."""
    return _cmd_basename(command) == "pi"


def is_interactive_cli(command: list[str]) -> bool:
    """Check if the command is an interactive AI CLI."""
    return (
        is_claude_command(command)
        or is_codex_command(command)
        or is_nanobot_command(command)
        or is_gemini_command(command)
        or is_kimi_command(command)
        or is_qwen_command(command)
        or is_opencode_command(command)
        or is_pi_command(command)
    )


def command_has_workspace_arg(command: list[str]) -> bool:
    """Return True when a command already specifies a nanobot workspace."""
    return "-w" in command or "--workspace" in command
