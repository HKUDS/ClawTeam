"""Abstract base class for task storage backends."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from clawteam.paths import validate_identifier
from clawteam.team.models import TaskItem, TaskPriority, TaskStatus


class TaskLockError(Exception):
    """Raised when a task is locked by another agent."""


class BaseTaskStore(ABC):
    """Interface for task storage backends.

    Implementations must handle their own concurrency control (file locking,
    Redis transactions, etc.) appropriate to the storage medium.
    """

    def __init__(self, team_name: str):
        self.team_name = validate_identifier(team_name, "team name")

    @abstractmethod
    def create(
        self,
        subject: str,
        description: str = "",
        owner: str = "",
        priority: TaskPriority | None = None,
        blocks: list[str] | None = None,
        blocked_by: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> TaskItem:
        """Create a new task and return it."""

    @abstractmethod
    def get(self, task_id: str) -> TaskItem | None:
        """Fetch a single task by ID, or None if not found."""

    @abstractmethod
    def update(
        self,
        task_id: str,
        status: TaskStatus | None = None,
        owner: str | None = None,
        subject: str | None = None,
        description: str | None = None,
        priority: TaskPriority | None = None,
        add_blocks: list[str] | None = None,
        add_blocked_by: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        caller: str = "",
        force: bool = False,
    ) -> TaskItem | None:
        """Update fields on an existing task. Returns the updated task or None."""

    @abstractmethod
    def list_tasks(
        self,
        status: TaskStatus | None = None,
        owner: str | None = None,
        priority: TaskPriority | None = None,
        sort_by_priority: bool = False,
    ) -> list[TaskItem]:
        """List tasks, optionally filtered and sorted."""

    @abstractmethod
    def release_stale_locks(self) -> list[str]:
        """Release locks held by dead agents. Returns list of freed task IDs."""

    def get_stats(self) -> dict[str, Any]:
        """Aggregate task timing stats.

        Default implementation calls list_tasks(). Backends with native
        aggregation (e.g. SQL) can override for efficiency.
        """
        tasks = self.list_tasks()
        completed = [t for t in tasks if t.status == TaskStatus.completed]
        durations = [
            t.metadata["duration_seconds"]
            for t in completed
            if "duration_seconds" in t.metadata
        ]
        avg_duration = sum(durations) / len(durations) if durations else 0.0
        return {
            "total": len(tasks),
            "completed": len(completed),
            "in_progress": sum(1 for t in tasks if t.status == TaskStatus.in_progress),
            "pending": sum(1 for t in tasks if t.status == TaskStatus.pending),
            "blocked": sum(1 for t in tasks if t.status == TaskStatus.blocked),
            "timed_completed": len(durations),
            "avg_duration_seconds": round(avg_duration, 2),
        }
