"""Data models for multi-agent team coordination (aligned with teammate-tool spec)."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


def get_data_dir() -> Path:
    """Return the data directory, respecting CLAWTEAM_DATA_DIR env var and config."""
    custom = os.environ.get("CLAWTEAM_DATA_DIR")
    if not custom:
        from clawteam.config import load_config
        custom = load_config().data_dir or None
    p = Path(custom) if custom else Path.home() / ".clawteam"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class MemberStatus(str, Enum):
    active = "active"
    idle = "idle"
    shutdown = "shutdown"


class TaskStatus(str, Enum):
    pending = "pending"
    in_progress = "in_progress"
    review = "review"
    completed = "completed"
    blocked = "blocked"


class TaskPriority(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"
    urgent = "urgent"


class MessageType(str, Enum):
    message = "message"
    join_request = "join_request"
    join_approved = "join_approved"
    join_rejected = "join_rejected"
    plan_approval_request = "plan_approval_request"
    plan_approved = "plan_approved"
    plan_rejected = "plan_rejected"
    shutdown_request = "shutdown_request"
    shutdown_approved = "shutdown_approved"
    shutdown_rejected = "shutdown_rejected"
    idle = "idle"
    broadcast = "broadcast"


class TeamMember(BaseModel):
    """A member of a team."""

    model_config = {"populate_by_name": True}

    name: str = Field(alias="name")
    user: str = Field(default="", alias="user")
    agent_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12], alias="agentId")
    agent_type: str = Field(default="general-purpose", alias="agentType")
    joined_at: str = Field(default_factory=_now_iso, alias="joinedAt")


class TeamConfig(BaseModel):
    """Team configuration stored in config.json."""

    model_config = {"populate_by_name": True}

    name: str
    description: str = ""
    lead_agent_id: str = Field(default="", alias="leadAgentId")
    created_at: str = Field(default_factory=_now_iso, alias="createdAt")
    members: list[TeamMember] = Field(default_factory=list)
    budget_cents: float = Field(default=0.0, alias="budgetCents")


class TeamMessage(BaseModel):
    """A message in the team mailbox system (aligned with teammate-tool).

    Uses exclude_none=True when serializing so only relevant fields appear.
    """

    model_config = {"populate_by_name": True}

    type: MessageType = MessageType.message
    from_agent: str = Field(alias="from", serialization_alias="from")
    to: str | None = None
    content: str | None = None
    request_id: str | None = Field(default=None, alias="requestId")
    timestamp: str = Field(default_factory=_now_iso)
    key: str | None = None
    # join_request fields
    proposed_name: str | None = Field(default=None, alias="proposedName")
    capabilities: str | None = None
    # join_approved fields
    assigned_name: str | None = Field(default=None, alias="assignedName")
    agent_id: str | None = Field(default=None, alias="agentId")
    team_name: str | None = Field(default=None, alias="teamName")
    # plan fields
    plan_file: str | None = Field(default=None, alias="planFile")
    summary: str | None = None
    plan: str | None = None
    # rejection/feedback
    feedback: str | None = None
    reason: str | None = None
    # idle notification fields
    last_task: str | None = Field(default=None, alias="lastTask")
    status: str | None = None


class TaskItem(BaseModel):
    """A task in the shared task list (aligned with teammate-tool)."""

    model_config = {"populate_by_name": True}

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:8])
    subject: str
    description: str = ""
    status: TaskStatus = TaskStatus.pending
    priority: TaskPriority = TaskPriority.medium
    owner: str = ""
    locked_by: str = Field(default="", alias="lockedBy")
    locked_at: str = Field(default="", alias="lockedAt")
    blocks: list[str] = Field(default_factory=list)
    blocked_by: list[str] = Field(default_factory=list, alias="blockedBy")
    started_at: str = Field(default="", alias="startedAt")
    created_at: str = Field(default_factory=_now_iso, alias="createdAt")
    updated_at: str = Field(default_factory=_now_iso, alias="updatedAt")
    metadata: dict[str, Any] = Field(default_factory=dict)
