"""Pluggable task storage backends."""

from __future__ import annotations

from clawteam.store.base import BaseTaskStore, TaskLockError


def get_task_store(team_name: str, backend: str = "") -> BaseTaskStore:
    """Create a task store by backend name.

    Checks CLAWTEAM_TASK_STORE env var, then config, then falls back to
    the file-based store.
    """
    import os

    name = backend or os.environ.get("CLAWTEAM_TASK_STORE", "")
    if not name:
        from clawteam.config import load_config
        name = load_config().task_store or ""

    # only "file" for now; redis/sql can be added later
    from clawteam.store.file import FileTaskStore
    return FileTaskStore(team_name)


__all__ = ["BaseTaskStore", "TaskLockError", "get_task_store"]
