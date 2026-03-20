"""Subprocess spawn backend - launches agents as separate processes."""

from __future__ import annotations

import os
import shlex
import subprocess

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


class SubprocessBackend(SpawnBackend):
    """Spawn agents as independent subprocesses running any command."""

    def __init__(self):
        self._processes: dict[str, subprocess.Popen] = {}

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
        spawn_env = os.environ.copy()
        clawteam_bin = resolve_clawteam_executable()
        spawn_env.update({
            "CLAWTEAM_AGENT_ID": agent_id,
            "CLAWTEAM_AGENT_NAME": agent_name,
            "CLAWTEAM_AGENT_TYPE": agent_type,
            "CLAWTEAM_TEAM_NAME": team_name,
            "CLAWTEAM_AGENT_LEADER": "0",
        })
        # Propagate user if set
        user = os.environ.get("CLAWTEAM_USER", "")
        if user:
            spawn_env["CLAWTEAM_USER"] = user
        # Propagate transport if set
        transport = os.environ.get("CLAWTEAM_TRANSPORT", "")
        if transport:
            spawn_env["CLAWTEAM_TRANSPORT"] = transport
        if cwd:
            spawn_env["CLAWTEAM_WORKSPACE_DIR"] = cwd
        if env:
            spawn_env.update(env)
        spawn_env["PATH"] = build_spawn_path(spawn_env.get("PATH"))
        if os.path.isabs(clawteam_bin):
            spawn_env.setdefault("CLAWTEAM_BIN", clawteam_bin)

        normalized_command = normalize_spawn_command(command)

        command_error = validate_spawn_command(normalized_command, path=spawn_env["PATH"], cwd=cwd)
        if command_error:
            return command_error

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
        elif prompt:
            if is_codex_command(normalized_command):
                final_command.append(prompt)
            else:
                final_command.extend(["-p", prompt])

        # Wrap with on-exit hook so task status updates immediately on exit
        cmd_str = " ".join(shlex.quote(c) for c in final_command)
        exit_cmd = shlex.quote(clawteam_bin) if os.path.isabs(clawteam_bin) else "clawteam"
        exit_hook = (
            f"{exit_cmd} lifecycle on-exit --team {shlex.quote(team_name)} "
            f"--agent {shlex.quote(agent_name)}"
        )
        shell_cmd = f"{cmd_str}; {exit_hook}"

        process = subprocess.Popen(
            shell_cmd,
            shell=True,
            env=spawn_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=cwd,
        )
        self._processes[agent_name] = process

        # Persist spawn info for liveness checking
        from clawteam.spawn.registry import register_agent
        register_agent(
            team_name=team_name,
            agent_name=agent_name,
            backend="subprocess",
            pid=process.pid,
            command=list(normalized_command),
        )

        return f"Agent '{agent_name}' spawned as subprocess (pid={process.pid})"

    def list_running(self) -> list[dict[str, str]]:
        result = []
        for name, proc in list(self._processes.items()):
            if proc.poll() is None:
                result.append({"name": name, "pid": str(proc.pid), "backend": "subprocess"})
            else:
                self._processes.pop(name, None)
        return result
