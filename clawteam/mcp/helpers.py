"""Shared helpers for ClawTeam MCP tools."""

from __future__ import annotations

from enum import Enum
from typing import Any, TypeVar

from clawteam.team.costs import CostStore
from clawteam.team.mailbox import MailboxManager
from clawteam.team.manager import TeamManager
from clawteam.team.plan import PlanManager
from clawteam.team.tasks import TaskLockError, TaskStore

EnumT = TypeVar("EnumT", bound=Enum)


class MCPToolError(ValueError):
    """Structured tool error surfaced to MCP clients."""


def fail(message: str) -> None:
    raise MCPToolError(message)


def translate_error(exc: Exception) -> MCPToolError:
    if isinstance(exc, MCPToolError):
        return exc
    if isinstance(exc, TaskLockError):
        return MCPToolError(str(exc))
    if isinstance(exc, (ValueError, RuntimeError)):
        return MCPToolError(str(exc))
    return MCPToolError(f"Unexpected error: {exc}")


def to_payload(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, Enum):
        return value.value
    if hasattr(value, "model_dump"):
        return to_payload(value.model_dump(by_alias=True, exclude_none=True))
    if isinstance(value, dict):
        return {key: to_payload(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [to_payload(item) for item in value]
    return value


def coerce_enum(enum_cls: type[EnumT], value: str | None) -> EnumT | None:
    return enum_cls(value) if value else None


def require_team(team_name: str):
    team = TeamManager.get_team(team_name)
    if team is None:
        raise ValueError(f"Team '{team_name}' not found")
    return team


def team_mailbox(team_name: str) -> MailboxManager:
    require_team(team_name)
    return MailboxManager(team_name)


def task_store(team_name: str) -> TaskStore:
    require_team(team_name)
    return TaskStore(team_name)


def plan_manager(team_name: str) -> PlanManager:
    return PlanManager(team_name, team_mailbox(team_name))



def cost_store(team_name: str) -> CostStore:
    require_team(team_name)
    return CostStore(team_name)
