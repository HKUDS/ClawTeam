"""Task store compatibility shim.

This module preserves the historic ``clawteam.team.tasks`` import path while
delegating the implementation to :mod:`clawteam.store`.
"""

from __future__ import annotations

from clawteam.store.base import BaseTaskStore, TaskLockError
from clawteam.store.file import FileTaskStore

TaskStore = FileTaskStore

__all__ = ["BaseTaskStore", "TaskLockError", "TaskStore"]
