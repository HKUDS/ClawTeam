"""Runtime adapters for agent-specific command preparation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from clawteam.spawn.command_validation import normalize_spawn_command


@dataclass(frozen=True)
class PreparedCommand:
    """Prepared native CLI command plus any post-launch prompt injection."""

    normalized_command: list[str]
    final_command: list[str]
    post_launch_prompt: str | None = None


class NativeCliAdapter:
    """Adapter for direct CLI runtimes such as claude, codex, gemini, kimi, nanobot, qwen, opencode."""

    def prepare_command(
        self,
        command: list[str],
        *,
        prompt: str | None = None,
        cwd: str | None = None,
        skip_permissions: bool = False,
        interactive: bool = False,
        agent_name: str | None = None,
    ) -> PreparedCommand:
        normalized_command = normalize_spawn_command(command)
        final_command = list(normalized_command)
        post_launch_prompt = None

        if skip_permissions:
            if is_claude_command(normalized_command):
                final_command.append("--dangerously-skip-permissions")
            elif is_codex_command(normalized_command):
                final_command.append("--dangerously-bypass-approvals-and-sandbox")
            elif (
                is_gemini_command(normalized_command)
                or is_kimi_command(normalized_command)
                or is_qwen_command(normalized_command)
                or is_opencode_command(normalized_command)
            ):
                final_command.append("--yolo")

        if is_kimi_command(normalized_command):
            if cwd and not command_has_workspace_arg(normalized_command):
                final_command.extend(["-w", cwd])
            if prompt:
                final_command.extend(["--print", "-p", prompt])
        elif is_nanobot_command(normalized_command):
            if cwd and not command_has_workspace_arg(normalized_command):
                final_command.extend(["-w", cwd])
            if prompt:
                final_command.extend(["-m", prompt])
        elif is_openclaw_command(normalized_command):
            if "agent" in normalized_command:
                if "--local" not in normalized_command:
                    final_command.append("--local")
                if agent_name and "--session-id" not in normalized_command:
                    final_command.extend(["--session-id", agent_name])
                if prompt:
                    final_command.extend(["--message", prompt])
            else:
                if agent_name and "--session" not in normalized_command:
                    final_command.extend(["--session", agent_name])
                if prompt:
                    final_command.extend(["--message", prompt])
        elif is_pi_command(normalized_command):
            # pi doesn't require special flags for skip_permissions (minimal by design)
            # pi works in cwd automatically, no workspace flag needed
            if prompt:
                if interactive:
                    final_command.append(prompt)
                else:
                    final_command.extend(["-p", prompt])
        elif prompt:
            if interactive and is_claude_command(normalized_command):
                post_launch_prompt = prompt
            elif is_codex_command(normalized_command):
                if interactive and not _is_codex_noninteractive_command(normalized_command):
                    post_launch_prompt = prompt
                else:
                    final_command.append(prompt)
            else:
                final_command.extend(["-p", prompt])

        return PreparedCommand(
            normalized_command=normalized_command,
            final_command=final_command,
            post_launch_prompt=post_launch_prompt,
        )


def command_basename(command: list[str]) -> str:
    """Return the normalized executable basename for a command."""
    if not command:
        return ""
    return Path(command[0]).name.lower()


def is_claude_command(command: list[str]) -> bool:
    """Check if the command is a Claude CLI invocation."""
    return command_basename(command) in ("claude", "claude-code")


def is_codex_command(command: list[str]) -> bool:
    """Check if the command is a Codex CLI invocation."""
    return command_basename(command) in ("codex", "codex-cli")


def _is_codex_noninteractive_command(command: list[str]) -> bool:
    """Return True when Codex is invoked in a non-interactive subcommand mode."""
    if len(command) < 2:
        return False
    return command[1] in {
        "exec",
        "e",
        "review",
        "resume",
        "fork",
        "cloud",
        "mcp",
        "mcp-server",
        "app-server",
        "completion",
        "sandbox",
        "debug",
        "apply",
        "login",
        "logout",
        "features",
    }


def is_nanobot_command(command: list[str]) -> bool:
    """Check if the command is a nanobot CLI invocation."""
    return command_basename(command) == "nanobot"


def is_gemini_command(command: list[str]) -> bool:
    """Check if the command is a Gemini CLI invocation."""
    return command_basename(command) == "gemini"


def is_kimi_command(command: list[str]) -> bool:
    """Check if the command is a Kimi CLI invocation."""
    return command_basename(command) == "kimi"


def is_qwen_command(command: list[str]) -> bool:
    """Check if the command is a Qwen Code CLI invocation."""
    return command_basename(command) in ("qwen", "qwen-code")


def is_opencode_command(command: list[str]) -> bool:
    """Check if the command is an OpenCode CLI invocation."""
    return command_basename(command) == "opencode"


def is_openclaw_command(command: list[str]) -> bool:
    """Check if the command is an OpenClaw CLI invocation."""
    return command_basename(command) == "openclaw"


def is_pi_command(command: list[str]) -> bool:
    """Check if the command is a pi-coding-agent CLI invocation."""
    return command_basename(command) == "pi"


def is_interactive_cli(command: list[str]) -> bool:
    """Check if the command is a known interactive AI coding CLI."""
    return (
        is_claude_command(command)
        or is_codex_command(command)
        or is_nanobot_command(command)
        or is_gemini_command(command)
        or is_kimi_command(command)
        or is_qwen_command(command)
        or is_opencode_command(command)
        or is_openclaw_command(command)
        or is_pi_command(command)
    )


def command_has_workspace_arg(command: list[str]) -> bool:
    """Return True when a command already specifies a workspace."""
    return "-w" in command or "--workspace" in command
