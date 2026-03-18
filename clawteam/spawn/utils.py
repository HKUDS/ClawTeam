"""Shared utilities for spawn backends."""

from __future__ import annotations


def is_claude_command(command: list[str]) -> bool:
    """Check if the command is a claude CLI invocation."""
    if not command:
        return False
    cmd = command[0].rsplit("/", 1)[-1]  # basename
    return cmd in ("claude", "claude-code")


def is_codex_command(command: list[str]) -> bool:
    """Check if the command is a codex CLI invocation."""
    if not command:
        return False
    cmd = command[0].rsplit("/", 1)[-1]  # basename
    return cmd in ("codex", "codex-cli")


def is_interactive_cli(command: list[str]) -> bool:
    """Check if the command is an interactive AI CLI (claude or codex)."""
    return is_claude_command(command) or is_codex_command(command)
