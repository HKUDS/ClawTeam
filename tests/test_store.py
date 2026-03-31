"""Tests for the pluggable task store abstraction layer."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from clawteam.store import BaseTaskStore, TaskLockError, get_task_store
from clawteam.store.base import BaseTaskStore as BaseTaskStoreFromBase
from clawteam.store.file import FileTaskStore
from clawteam.team.models import TaskPriority, TaskStatus
from clawteam.team.tasks import TaskStore  # backward compat alias


class TestBackwardCompat:
    """Verify the old import path still works."""

    def test_taskstore_is_filetaskstore(self):
        assert TaskStore is FileTaskStore

    def test_tasklockerror_importable_from_old_path(self):
        from clawteam.team.tasks import TaskLockError as OldLockError
        assert OldLockError is TaskLockError

    def test_basetaskstore_importable_from_old_path(self):
        from clawteam.team.tasks import BaseTaskStore as OldBase
        assert OldBase is BaseTaskStoreFromBase

    def test_old_import_creates_working_store(self, team_name):
        store = TaskStore(team_name)
        t = store.create("compat test")
        assert store.get(t.id).subject == "compat test"


class TestFileTaskStoreIsBaseTaskStore:
    def test_filetaskstore_inherits_base(self):
        assert issubclass(FileTaskStore, BaseTaskStore)

    def test_isinstance_check(self, team_name):
        store = FileTaskStore(team_name)
        assert isinstance(store, BaseTaskStore)


class TestFactory:
    def test_default_returns_filetaskstore(self, team_name):
        store = get_task_store(team_name)
        assert isinstance(store, FileTaskStore)
        assert store.team_name == team_name

    def test_explicit_file_backend(self, team_name):
        store = get_task_store(team_name, backend="file")
        assert isinstance(store, FileTaskStore)

    def test_env_var_override(self, team_name):
        with patch.dict(os.environ, {"CLAWTEAM_TASK_STORE": "file"}):
            store = get_task_store(team_name)
        assert isinstance(store, FileTaskStore)

    def test_unknown_backend_falls_back_to_file(self, team_name):
        # until other backends exist, unknown names still get FileTaskStore
        store = get_task_store(team_name, backend="nonexistent")
        assert isinstance(store, FileTaskStore)

    def test_invalid_team_name_is_rejected(self):
        with pytest.raises(ValueError, match="Invalid team name"):
            get_task_store("../escape")


class TestBaseTaskStoreABC:
    """Verify the ABC can't be instantiated directly and get_stats has a
    working default implementation."""

    def test_cannot_instantiate_directly(self):
        with pytest.raises(TypeError):
            BaseTaskStore("test-team")

    def test_get_stats_default_impl(self, team_name):
        store = FileTaskStore(team_name)
        store.create("a")
        store.create("b")
        t3 = store.create("c")
        store.update(t3.id, status=TaskStatus.completed)

        stats = store.get_stats()
        assert stats["total"] == 3
        assert stats["completed"] == 1
        assert stats["pending"] == 2
        assert stats["avg_duration_seconds"] == 0.0  # no timed tasks


class TestStoreRoundTrip:
    """End-to-end tests through the factory to verify wiring."""

    def test_create_get_roundtrip(self, team_name):
        store = get_task_store(team_name)
        created = store.create("roundtrip", description="via factory")
        fetched = store.get(created.id)
        assert fetched.subject == "roundtrip"
        assert fetched.description == "via factory"

    def test_list_through_factory(self, team_name):
        store = get_task_store(team_name)
        store.create("one", priority=TaskPriority.high)
        store.create("two", priority=TaskPriority.low)
        tasks = store.list_tasks(priority=TaskPriority.high)
        assert len(tasks) == 1
        assert tasks[0].subject == "one"

    def test_dependency_resolution_through_factory(self, team_name):
        store = get_task_store(team_name)
        t1 = store.create("prerequisite")
        t2 = store.create("blocked task", blocked_by=[t1.id])
        assert t2.status == TaskStatus.blocked

        store.update(t1.id, status=TaskStatus.completed)
        t2_after = store.get(t2.id)
        assert t2_after.status == TaskStatus.pending


class TestConfigIntegration:
    def test_task_store_in_config(self):
        from clawteam.config import ClawTeamConfig
        cfg = ClawTeamConfig()
        assert hasattr(cfg, "task_store")
        assert cfg.task_store == ""

    def test_task_store_env_var_in_get_effective(self):
        from clawteam.config import get_effective
        with patch.dict(os.environ, {"CLAWTEAM_TASK_STORE": "redis"}):
            val, source = get_effective("task_store")
        assert val == "redis"
        assert source == "env"
