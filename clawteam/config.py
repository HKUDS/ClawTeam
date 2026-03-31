"""Persistent configuration for ClawTeam."""

from __future__ import annotations

import json
import os
from pathlib import Path

from pydantic import BaseModel, Field

from clawteam.fileutil import atomic_write_text


class AgentProfile(BaseModel):
    """Reusable agent runtime profile for spawn/launch."""

    description: str = ""
    agent: str = ""
    command: list[str] = Field(default_factory=list)
    model: str = ""
    base_url: str = ""
    base_url_env: str = ""
    api_key_env: str = ""
    api_key_target_env: str = ""
    env: dict[str, str] = Field(default_factory=dict)
    env_map: dict[str, str] = Field(default_factory=dict)
    args: list[str] = Field(default_factory=list)


class AgentPreset(BaseModel):
    """Shared preset input for generating client-scoped profiles."""

    description: str = ""
    auth_env: str = ""
    base_url: str = ""
    env: dict[str, str] = Field(default_factory=dict)
    client_overrides: dict[str, AgentProfile] = Field(default_factory=dict)


class ClawTeamConfig(BaseModel):
    data_dir: str = ""
    user: str = ""
    default_team: str = ""
    default_profile: str = ""
    transport: str = ""
    task_store: str = ""  # "file" (default) — extensible for redis/sql later
    workspace: str = "auto"  # "auto" | "always" | "never" | ""
    default_backend: str = "tmux"  # "tmux" | "subprocess"
    skip_permissions: bool = True  # pass --dangerously-skip-permissions to claude
    timezone: str = "UTC"  # display timezone for human-readable timestamps
    gource_path: str = ""  # custom path to gource binary (auto-detected if empty)
    gource_resolution: str = "1280x720"  # default viewport resolution
    gource_seconds_per_day: float = 0.5  # animation speed
    profiles: dict[str, AgentProfile] = Field(default_factory=dict)
    presets: dict[str, AgentPreset] = Field(default_factory=dict)
    spawn_prompt_delay: float = 2.0  # fallback wait (seconds) if TUI ready-detection times out
    spawn_ready_timeout: float = 30.0  # max seconds to poll for TUI readiness before fallback


def config_path() -> Path:
    """Fixed config location: ~/.clawteam/config.json (never affected by data_dir)."""
    return Path.home() / ".clawteam" / "config.json"


def load_config() -> ClawTeamConfig:
    """Load config from disk. Returns defaults if file doesn't exist."""
    p = config_path()
    if not p.exists():
        return ClawTeamConfig()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return ClawTeamConfig.model_validate(data)
    except Exception:
        return ClawTeamConfig()


def save_config(cfg: ClawTeamConfig) -> None:
    """Atomically write config to disk (mkstemp + replace)."""
    atomic_write_text(config_path(), cfg.model_dump_json(indent=2))


def get_effective(key: str) -> tuple[str, str]:
    """Get effective value for a config key. Returns (value, source).

    Priority: env var > config file > default.
    """
    env_map = {
        "data_dir": "CLAWTEAM_DATA_DIR",
        "user": "CLAWTEAM_USER",
        "default_team": "CLAWTEAM_TEAM_NAME",
        "default_profile": "CLAWTEAM_DEFAULT_PROFILE",
        "transport": "CLAWTEAM_TRANSPORT",
        "task_store": "CLAWTEAM_TASK_STORE",
        "workspace": "CLAWTEAM_WORKSPACE",
        "default_backend": "CLAWTEAM_DEFAULT_BACKEND",
        "skip_permissions": "CLAWTEAM_SKIP_PERMISSIONS",
        "timezone": "CLAWTEAM_TIMEZONE",
        "gource_path": "CLAWTEAM_GOURCE_PATH",
        "gource_resolution": "CLAWTEAM_GOURCE_RESOLUTION",
        "gource_seconds_per_day": "CLAWTEAM_GOURCE_SECONDS_PER_DAY",
        "spawn_prompt_delay": "CLAWTEAM_SPAWN_PROMPT_DELAY",
        "spawn_ready_timeout": "CLAWTEAM_SPAWN_READY_TIMEOUT",
    }
    defaults = ClawTeamConfig()
    cfg = load_config()

    env_key = env_map.get(key)
    if env_key:
        env_val = os.environ.get(env_key)
        if env_val:
            return env_val, "env"

    file_val = getattr(cfg, key, "")
    default_val = getattr(defaults, key, "")
    if file_val != default_val:
        return str(file_val), "file"

    return str(default_val), "default"


def scalar_config_keys() -> list[str]:
    """Return user-facing scalar config keys (excluding nested structures)."""
    return [
        key
        for key in ClawTeamConfig.model_fields.keys()
        if key not in {"profiles", "presets"}
    ]
