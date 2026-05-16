"""Runtime adapters for agent-specific command preparation."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from clawteam.spawn.cli_env import build_docker_clawteam_runtime
from clawteam.spawn.command_validation import (
    command_has_workspace_arg as has_workspace_arg,
)
from clawteam.spawn.command_validation import (
    docker_wrapped_cli_name,
    ensure_docker_env,
    ensure_docker_mount,
    ensure_docker_workspace,
    normalize_spawn_command,
)


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
        container_env: dict[str, str] | None = None,
    ) -> PreparedCommand:
        normalized_command = normalize_spawn_command(command)
        final_command = list(normalized_command)
        post_launch_prompt = None

        if skip_permissions:
            # Claude Code rejects --dangerously-skip-permissions when running
            # as root/sudo.  Detect this and silently omit the flag so spawned
            # agents can still start.
            _is_root = getattr(os, "getuid", lambda: -1)() == 0
            if is_claude_command(normalized_command) and not _is_root:
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
            if cwd and not has_workspace_arg(normalized_command):
                final_command.extend(["-w", cwd])
            if prompt:
                final_command.extend(["--print", "-p", prompt])
        elif is_nanobot_command(normalized_command):
            if docker_wrapped_cli_name(normalized_command) == "nanobot":
                if cwd:
                    final_command = ensure_docker_workspace(final_command, cwd)
                if container_env:
                    data_dir = container_env.get("CLAWTEAM_DATA_DIR")
                    if data_dir:
                        final_command = ensure_docker_mount(final_command, data_dir)
                    docker_runtime = build_docker_clawteam_runtime()
                    if docker_runtime:
                        for host_path, container_path in docker_runtime.mounts:
                            final_command = ensure_docker_mount(final_command, host_path, container_path)
                    docker_env = {
                        key: value
                        for key, value in container_env.items()
                        if value
                        and (
                            (key.startswith("CLAWTEAM_") and key != "CLAWTEAM_BIN")
                            or key.startswith("OH_")
                            or key.endswith("_API_KEY")
                            or key.endswith("_BASE_URL")
                            or key.endswith("_API_BASE")
                            or key == "GOOGLE_CLOUD_PROJECT"
                        )
                    }
                    if docker_runtime:
                        docker_env.update(docker_runtime.env)
                    if docker_env:
                        final_command = ensure_docker_env(final_command, docker_env)
            if cwd and not has_workspace_arg(normalized_command):
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
        elif is_gemini_command(normalized_command):
            if prompt:
                if interactive:
                    final_command.extend(["-i", prompt])
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
    return command_basename(command) == "nanobot" or docker_wrapped_cli_name(command) == "nanobot"


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
