"""File-based task store: each task is a JSON file on disk."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if sys.platform == "win32":
    import msvcrt
else:
    import fcntl

from clawteam.paths import ensure_within_root, validate_identifier
from clawteam.store.base import BaseTaskStore, TaskLockError
from clawteam.team.models import TaskItem, TaskPriority, TaskStatus, get_data_dir


def _tasks_root(team_name: str) -> Path:
    d = ensure_within_root(
        get_data_dir() / "tasks",
        validate_identifier(team_name, "team name"),
    )
    d.mkdir(parents=True, exist_ok=True)
    return d


def _task_path(team_name: str, task_id: str) -> Path:
    return _tasks_root(team_name) / f"task-{task_id}.json"


def _tasks_lock_path(team_name: str) -> Path:
    return _tasks_root(team_name) / ".tasks.lock"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class FileTaskStore(BaseTaskStore):
    """Task store backed by the local filesystem.

    Each task is stored as a separate JSON file:
    ``{data_dir}/tasks/{team}/task-{id}.json``

    Concurrent access is serialised with an OS-specific advisory lock.
    """

    @contextmanager
    def _write_lock(self):
        lock_path = _tasks_lock_path(self.team_name)
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+", encoding="utf-8") as lock_file:
            if sys.platform == "win32":
                pos = lock_file.tell()
                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
                lock_file.seek(pos)
            else:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                if sys.platform == "win32":
                    pos = lock_file.tell()
                    lock_file.seek(0)
                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
                    lock_file.seek(pos)
                else:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

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
        task = TaskItem(
            subject=subject,
            description=description,
            owner=owner,
            priority=priority or TaskPriority.medium,
            blocks=blocks or [],
            blocked_by=blocked_by or [],
            metadata=metadata or {},
        )
        self._validate_blocked_by_unlocked(task.id, task.blocked_by)
        if task.blocked_by:
            task.status = TaskStatus.blocked
        with self._write_lock():
            self._save_unlocked(task)
        return task

    def get(self, task_id: str) -> TaskItem | None:
        return self._get_unlocked(task_id)

    def _get_unlocked(self, task_id: str) -> TaskItem | None:
        path = _task_path(self.team_name, task_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return TaskItem.model_validate(data)
        except Exception:
            return None

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
        with self._write_lock():
            task = self._get_unlocked(task_id)
            if not task:
                return None

            if status == TaskStatus.in_progress:
                self._acquire_lock(task, caller, force)
                if not task.started_at:
                    task.started_at = _now_iso()

            if status in (TaskStatus.completed, TaskStatus.pending):
                task.locked_by = ""
                task.locked_at = ""

            # duration tracking
            if status == TaskStatus.completed and task.started_at:
                try:
                    start = datetime.fromisoformat(task.started_at)
                    duration_secs = (datetime.now(timezone.utc) - start).total_seconds()
                    task.metadata["duration_seconds"] = round(duration_secs, 2)
                except (ValueError, TypeError):
                    pass

            if status is not None:
                task.status = status
            if owner is not None:
                task.owner = owner
            if subject is not None:
                task.subject = subject
            if description is not None:
                task.description = description
            if priority is not None:
                task.priority = priority
            if add_blocks:
                for b in add_blocks:
                    if b not in task.blocks:
                        task.blocks.append(b)
            if add_blocked_by:
                proposed_blocked_by = list(task.blocked_by)
                for b in add_blocked_by:
                    if b not in proposed_blocked_by:
                        proposed_blocked_by.append(b)
                self._validate_blocked_by_unlocked(task.id, proposed_blocked_by)
                task.blocked_by = proposed_blocked_by
                if task.blocked_by and task.status == TaskStatus.pending:
                    task.status = TaskStatus.blocked
            if metadata:
                task.metadata.update(metadata)
            task.updated_at = _now_iso()

            if task.status == TaskStatus.completed:
                self._resolve_dependents_unlocked(task_id)

            self._save_unlocked(task)
            return task

    def _acquire_lock(self, task: TaskItem, caller: str, force: bool) -> None:
        if task.locked_by and task.locked_by != caller and not force:
            from clawteam.spawn.registry import is_agent_alive
            alive = is_agent_alive(self.team_name, task.locked_by)
            if alive is not False:
                raise TaskLockError(
                    f"Task '{task.id}' is locked by '{task.locked_by}' "
                    f"(since {task.locked_at}). Use --force to override."
                )
        task.locked_by = caller or ""
        task.locked_at = _now_iso() if caller else ""

    def release_stale_locks(self) -> list[str]:
        from clawteam.spawn.registry import is_agent_alive

        released = []
        with self._write_lock():
            for task in self._list_tasks_unlocked():
                if not task.locked_by:
                    continue
                alive = is_agent_alive(self.team_name, task.locked_by)
                if alive is False:
                    task.locked_by = ""
                    task.locked_at = ""
                    task.updated_at = _now_iso()
                    self._save_unlocked(task)
                    released.append(task.id)
        return released

    def list_tasks(
        self,
        status: TaskStatus | None = None,
        owner: str | None = None,
        priority: TaskPriority | None = None,
        sort_by_priority: bool = False,
    ) -> list[TaskItem]:
        return self._list_tasks_unlocked(
            status=status,
            owner=owner,
            priority=priority,
            sort_by_priority=sort_by_priority,
        )

    def _list_tasks_unlocked(
        self,
        status: TaskStatus | None = None,
        owner: str | None = None,
        priority: TaskPriority | None = None,
        sort_by_priority: bool = False,
    ) -> list[TaskItem]:
        root = _tasks_root(self.team_name)
        tasks = []
        for f in sorted(root.glob("task-*.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                task = TaskItem.model_validate(data)
                if status and task.status != status:
                    continue
                if owner and task.owner != owner:
                    continue
                if priority and task.priority != priority:
                    continue
                tasks.append(task)
            except Exception:
                continue
        if sort_by_priority:
            priority_order = {
                TaskPriority.urgent: 0,
                TaskPriority.high: 1,
                TaskPriority.medium: 2,
                TaskPriority.low: 3,
            }
            tasks.sort(key=lambda task: (priority_order.get(task.priority, 2), task.created_at, task.id))
        return tasks

    def _validate_blocked_by_unlocked(self, task_id: str, blocked_by: list[str]) -> None:
        if task_id in blocked_by:
            raise ValueError(f"Task '{task_id}' cannot be blocked by itself")

        graph: dict[str, list[str]] = {
            task.id: list(task.blocked_by)
            for task in self._list_tasks_unlocked()
        }
        graph[task_id] = list(blocked_by)

        visiting: set[str] = set()
        visited: set[str] = set()

        def _visit(node: str) -> bool:
            if node in visiting:
                return True
            if node in visited:
                return False
            visiting.add(node)
            for dep in graph.get(node, []):
                if dep in graph and _visit(dep):
                    return True
            visiting.remove(node)
            visited.add(node)
            return False

        for node in graph:
            if _visit(node):
                raise ValueError("Task dependencies cannot contain cycles")

    def _save_unlocked(self, task: TaskItem) -> None:
        path = _task_path(self.team_name, task.id)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            dir=path.parent,
            prefix=f"{path.stem}-",
            suffix=".tmp",
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as tmp_file:
                tmp_file.write(task.model_dump_json(indent=2, by_alias=True))
            os.replace(tmp_name, str(path))
        except BaseException:
            Path(tmp_name).unlink(missing_ok=True)
            raise

    def _resolve_dependents_unlocked(self, completed_task_id: str) -> None:
        root = _tasks_root(self.team_name)
        for f in root.glob("task-*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                task = TaskItem.model_validate(data)
                if completed_task_id in task.blocked_by:
                    task.blocked_by.remove(completed_task_id)
                    if not task.blocked_by and task.status == TaskStatus.blocked:
                        task.status = TaskStatus.pending
                    task.updated_at = _now_iso()
                    self._save_unlocked(task)
            except Exception:
                continue
