"""Persistent configuration for ClawTeam."""

from __future__ import annotations

import json
import os
from pathlib import Path

from pydantic import BaseModel


class ClawTeamConfig(BaseModel):
    data_dir: str = ""
    user: str = ""
    default_team: str = ""
    transport: str = ""
    workspace: str = "auto"  # "auto" | "always" | "never" | ""
    default_backend: str = "tmux"  # "tmux" | "subprocess" | "acpx"
    skip_permissions: bool = True  # pass --dangerously-skip-permissions to claude
    gource_path: str = ""  # custom path to gource binary (auto-detected if empty)
    gource_resolution: str = "1280x720"  # default viewport resolution
    gource_seconds_per_day: float = 0.5  # animation speed
    # ACPX settings
    acpx_path: str = ""  # path to acpx binary (default: "acpx" from PATH)
    acpx_default_format: str = "json"  # "json" | "text" | "stream-json"
    acpx_approve_mode: str = ""  # "" | "approve-all" | "approve-reads"


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
    """Atomically write config to disk (tmp + rename)."""
    p = config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(cfg.model_dump_json(indent=2), encoding="utf-8")
    tmp.rename(p)


def get_effective(key: str) -> tuple[str, str]:
    """Get effective value for a config key. Returns (value, source).

    Priority: env var > config file > default.
    """
    env_map = {
        "data_dir": "CLAWTEAM_DATA_DIR",
        "user": "CLAWTEAM_USER",
        "default_team": "CLAWTEAM_TEAM_NAME",
        "transport": "CLAWTEAM_TRANSPORT",
        "workspace": "CLAWTEAM_WORKSPACE",
        "default_backend": "CLAWTEAM_DEFAULT_BACKEND",
        "skip_permissions": "CLAWTEAM_SKIP_PERMISSIONS",
        "gource_path": "CLAWTEAM_GOURCE_PATH",
        "gource_resolution": "CLAWTEAM_GOURCE_RESOLUTION",
        "gource_seconds_per_day": "CLAWTEAM_GOURCE_SECONDS_PER_DAY",
        "acpx_path": "CLAWTEAM_ACPX_PATH",
        "acpx_default_format": "CLAWTEAM_ACPX_DEFAULT_FORMAT",
        "acpx_approve_mode": "CLAWTEAM_ACPX_APPROVE_MODE",
    }
    defaults = ClawTeamConfig()
    cfg = load_config()

    env_key = env_map.get(key)
    if env_key:
        env_val = os.environ.get(env_key)
        if env_val:
            return env_val, "env"

    file_val = getattr(cfg, key, "")
    if file_val:
        return file_val, "file"

    return getattr(defaults, key, ""), "default"
