"""Profile resolution helpers for agent commands and runtime environments."""

from __future__ import annotations

import os
from pathlib import Path

from clawteam.config import AgentProfile, load_config


def load_profile(name: str) -> AgentProfile:
    """Load a named profile from config or raise ValueError."""
    cfg = load_config()
    profile = cfg.profiles.get(name)
    if profile is None:
        raise ValueError(f"Unknown profile '{name}'")
    return profile


def save_profile(name: str, profile: AgentProfile) -> None:
    """Persist a named profile."""
    from clawteam.config import save_config

    cfg = load_config()
    cfg.profiles[name] = profile
    save_config(cfg)


def remove_profile(name: str) -> bool:
    """Remove a profile. Returns True if it existed."""
    from clawteam.config import save_config

    cfg = load_config()
    if name not in cfg.profiles:
        return False
    del cfg.profiles[name]
    save_config(cfg)
    return True


def list_profiles() -> dict[str, AgentProfile]:
    """Return all configured profiles."""
    return load_config().profiles


def load_team_profile(team_name: str) -> tuple[str, list[dict]]:
    """Load a team profile configuration.
    
    Returns (leader_profile_name, member_configs).
    member_configs is a list of dicts with 'profile' and optional 'personality'.
    """
    from clawteam.config import load_config
    
    cfg = load_config()
    team_profile = cfg.team_profiles.get(team_name)
    if team_profile is None:
        raise ValueError(f"Unknown team profile '{team_name}'")
    
    leader_profile = team_profile.leader.profile
    members = [
        {"profile": m.profile, "personality": m.personality}
        for m in team_profile.members
    ]
    
    return leader_profile, members


def apply_profile(
    profile: AgentProfile | None,
    *,
    command: list[str] | None = None,
    env: dict[str, str] | None = None,
) -> tuple[list[str], dict[str, str], str]:
    """Apply a profile to a command/env pair.

    Returns (resolved_command, resolved_env, resolved_agent_basename).
    """

    resolved_env = dict(env or {})
    if profile is None:
        resolved_command = list(command or [])
        return resolved_command, resolved_env, command_basename(resolved_command)

    resolved_command = list(command or [])
    if not resolved_command:
        if profile.command:
            resolved_command = list(profile.command)
        elif profile.agent:
            resolved_command = [profile.agent]

    if not resolved_command:
        raise ValueError("Profile does not define an agent command")

    agent = command_basename(resolved_command)

    for key, value in profile.env.items():
        resolved_env[key] = value

    for dest, source in profile.env_map.items():
        value = os.environ.get(source)
        if value:
            resolved_env[dest] = value

    if profile.base_url:
        base_url_env = profile.base_url_env or _base_url_env_var(agent)
        if base_url_env:
            resolved_env.setdefault(base_url_env, profile.base_url)

    if profile.api_key_env:
        token = os.environ.get(profile.api_key_env)
        if token:
            api_key_target = profile.api_key_target_env or _api_key_target_env(agent)
            if api_key_target:
                resolved_env.setdefault(api_key_target, token)

    if profile.model and not _command_has_model_arg(resolved_command):
        model_flag = _model_flag(agent)
        if model_flag:
            resolved_command.extend([model_flag, profile.model])

    if profile.args:
        resolved_command.extend(profile.args)

    return resolved_command, resolved_env, agent


def command_basename(command: list[str]) -> str:
    """Return the executable basename for a command."""
    if not command:
        return ""
    return Path(command[0]).name.lower()


def _command_has_model_arg(command: list[str]) -> bool:
    return "--model" in command or "-m" in command


def _model_flag(agent: str) -> str | None:
    if agent in {"claude", "claude-code", "codex", "codex-cli", "gemini", "kimi"}:
        return "--model"
    return None


def _base_url_env_var(agent: str) -> str | None:
    if agent in {"claude", "claude-code"}:
        return "ANTHROPIC_BASE_URL"
    if agent in {"codex", "codex-cli"}:
        return "OPENAI_BASE_URL"
    if agent == "gemini":
        return "GOOGLE_GEMINI_BASE_URL"
    if agent == "kimi":
        return "KIMI_BASE_URL"
    return None


def _api_key_target_env(agent: str) -> str | None:
    if agent in {"claude", "claude-code"}:
        return "ANTHROPIC_AUTH_TOKEN"
    if agent in {"codex", "codex-cli"}:
        return "OPENAI_API_KEY"
    if agent == "gemini":
        return "GEMINI_API_KEY"
    if agent == "kimi":
        return "KIMI_API_KEY"
    return None
