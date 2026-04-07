"""Agent identity for team context with dual-prefix environment variable support."""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field


def _env(primary_key: str, fallback_key: str, default: str = "") -> str:
    """Read from primary env var first, fall back to secondary."""
    return os.environ.get(primary_key) or os.environ.get(fallback_key) or default


def _env_bool(primary_key: str, fallback_key: str) -> bool:
    val = _env(primary_key, fallback_key)
    return val.lower() in ("1", "true", "yes")


@dataclass
class AgentIdentity:
    """Identity of an agent within a team (or standalone)."""

    agent_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    agent_name: str = "agent"
    user: str = ""
    agent_type: str = "general-purpose"
    team_name: str | None = None
    is_leader: bool = False
    plan_mode_required: bool = False

    @property
    def in_team(self) -> bool:
        return self.team_name is not None

    @classmethod
    def from_env(cls) -> AgentIdentity:
        """Build identity from environment variables with legacy fallbacks.

        Field precedence:
        - agent_id, agent_name, agent_type, team_name, and is_leader:
          CLAWTEAM_* first, then CLAUDE_CODE_*.
        - plan_mode_required:
          CLAWTEAM_PLAN_MODE_REQUIRED first, then OH_PLAN_MODE_REQUIRED,
          then CLAUDE_CODE_PLAN_MODE_REQUIRED.
        - user:
          CLAWTEAM_USER first, otherwise load_config().user.
        """
        user = os.environ.get("CLAWTEAM_USER", "")
        if not user:
            from clawteam.config import load_config

            user = load_config().user
        return cls(
            agent_id=_env("CLAWTEAM_AGENT_ID", "CLAUDE_CODE_AGENT_ID", uuid.uuid4().hex[:12]),
            agent_name=_env("CLAWTEAM_AGENT_NAME", "CLAUDE_CODE_AGENT_NAME", "agent"),
            user=user,
            agent_type=_env("CLAWTEAM_AGENT_TYPE", "CLAUDE_CODE_AGENT_TYPE", "general-purpose"),
            team_name=_env("CLAWTEAM_TEAM_NAME", "CLAUDE_CODE_TEAM_NAME") or None,
            is_leader=_env_bool("CLAWTEAM_AGENT_LEADER", "CLAUDE_CODE_AGENT_LEADER"),
            plan_mode_required=(
                os.environ.get("CLAWTEAM_PLAN_MODE_REQUIRED")
                or os.environ.get("OH_PLAN_MODE_REQUIRED")
                or os.environ.get("CLAUDE_CODE_PLAN_MODE_REQUIRED")
                or ""
            ).lower() in ("1", "true", "yes"),
        )

    def to_env(self) -> dict[str, str]:
        """Export identity as environment variables (for spawning sub-agents)."""
        env = {
            "CLAWTEAM_AGENT_ID": self.agent_id,
            "CLAWTEAM_AGENT_NAME": self.agent_name,
            "CLAWTEAM_AGENT_TYPE": self.agent_type,
            "CLAWTEAM_AGENT_LEADER": "1" if self.is_leader else "0",
            "CLAWTEAM_PLAN_MODE_REQUIRED": "1" if self.plan_mode_required else "0",
            # Legacy alias for backward compatibility
            "OH_PLAN_MODE_REQUIRED": "1" if self.plan_mode_required else "0",
        }
        if self.user:
            env["CLAWTEAM_USER"] = self.user
        if self.team_name:
            env["CLAWTEAM_TEAM_NAME"] = self.team_name
        return env
