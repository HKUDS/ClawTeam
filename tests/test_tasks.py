"""Tests for clawteam.team.tasks — TaskStore CRUD + dependency tracking."""

from unittest.mock import patch

import pytest

from clawteam.team.models import TaskItem, TaskPriority, TaskStatus
from clawteam.team.tasks import TaskLockError, TaskStore


@pytest.fixture
def store(team_name):
    return TaskStore(team_name)


class TestTaskCreate:
    def test_create_basic(self, store):
        t = store.create("Write tests", description="pytest suite")
        assert t.subject == "Write tests"
        assert t.description == "pytest suite"
        assert t.status == TaskStatus.pending

    def test_create_with_owner(self, store):
        t = store.create("Fix bug", owner="alice")
        assert t.owner == "alice"

    def test_create_strips_owner_whitespace(self, store):
        t = store.create("Fix bug", owner="  alice  ")
        assert t.owner == "alice"

    def test_create_with_priority(self, store):
        t = store.create("urgent item", priority=TaskPriority.urgent)
        assert t.priority == TaskPriority.urgent

    def test_create_with_blocked_by_sets_blocked_status(self, store):
        t1 = store.create("first task")
        t2 = store.create("second task", blocked_by=[t1.id])
        assert t2.status == TaskStatus.blocked
        assert t1.id in t2.blocked_by

    def test_create_with_metadata(self, store):
        t = store.create("tagged task", metadata={"priority": "high"})
        assert t.metadata["priority"] == "high"

    def test_create_persists_to_disk(self, store):
        t = store.create("persistent")
        loaded = store.get(t.id)
        assert loaded is not None
        assert loaded.subject == "persistent"


class TestTaskGet:
    def test_get_existing(self, store):
        t = store.create("exists")
        got = store.get(t.id)
        assert got is not None
        assert got.id == t.id

    def test_get_nonexistent(self, store):
        assert store.get("does-not-exist") is None


class TestTaskUpdate:
    def test_update_status(self, store):
        t = store.create("wip")
        # need to mock is_agent_alive for the lock logic
        with patch("clawteam.team.tasks.TaskStore._acquire_lock"):
            updated = store.update(t.id, status=TaskStatus.in_progress, caller="agent-1")
        assert updated.status == TaskStatus.in_progress

    def test_update_subject_and_description(self, store):
        t = store.create("old title")
        updated = store.update(t.id, subject="new title", description="details")
        assert updated.subject == "new title"
        assert updated.description == "details"

    def test_update_owner(self, store):
        t = store.create("task")
        updated = store.update(t.id, owner="bob")
        assert updated.owner == "bob"

    def test_update_owner_strips_whitespace(self, store):
        t = store.create("task")
        updated = store.update(t.id, owner="  bob  ")
        assert updated.owner == "bob"

    def test_update_priority(self, store):
        t = store.create("task")
        updated = store.update(t.id, priority=TaskPriority.high)
        assert updated.priority == TaskPriority.high

    def test_update_add_blocks(self, store):
        t1 = store.create("blocker")
        t2 = store.create("other")
        updated = store.update(t1.id, add_blocks=[t2.id])
        assert t2.id in updated.blocks

    def test_update_add_blocked_by(self, store):
        t1 = store.create("dep")
        t2 = store.create("main")
        updated = store.update(t2.id, add_blocked_by=[t1.id])
        assert t1.id in updated.blocked_by

    def test_update_metadata_merge(self, store):
        t = store.create("m", metadata={"a": 1})
        updated = store.update(t.id, metadata={"b": 2})
        assert updated.metadata == {"a": 1, "b": 2}

    def test_update_nonexistent_returns_none(self, store):
        assert store.update("nope", status=TaskStatus.completed) is None

    def test_complete_clears_lock(self, store):
        t = store.create("locked")
        with patch("clawteam.team.tasks.TaskStore._acquire_lock"):
            store.update(t.id, status=TaskStatus.in_progress, caller="agent-1")
        completed = store.update(t.id, status=TaskStatus.completed)
        assert completed.locked_by == ""
        assert completed.locked_at == ""

    def test_updated_at_changes(self, store):
        t = store.create("ts-check")
        original_ts = t.updated_at
        updated = store.update(t.id, subject="changed")
        assert updated.updated_at >= original_ts


class TestTaskList:
    def test_list_all(self, store):
        store.create("a")
        store.create("b")
        store.create("c")
        tasks = store.list_tasks()
        assert len(tasks) == 3

    def test_list_filter_by_status(self, store):
        store.create("pending-one")
        t2 = store.create("blocked-one", blocked_by=["fake-dep"])
        tasks = store.list_tasks(status=TaskStatus.blocked)
        assert len(tasks) == 1
        assert tasks[0].id == t2.id

    def test_list_filter_by_owner(self, store):
        store.create("alice-task", owner="alice")
        store.create("bob-task", owner="bob")
        tasks = store.list_tasks(owner="alice")
        assert len(tasks) == 1
        assert tasks[0].owner == "alice"

    def test_list_filter_by_owner_strips_filter_whitespace(self, store):
        store.create("alice-task", owner="alice")
        store.create("bob-task", owner="bob")
        tasks = store.list_tasks(owner="  alice  ")
        assert len(tasks) == 1
        assert tasks[0].owner == "alice"

    def test_list_filter_by_owner_case_insensitive(self, store):
        store.create("alice-task", owner="Alice")
        store.create("bob-task", owner="bob")
        tasks = store.list_tasks(owner="alice")
        assert len(tasks) == 1
        assert tasks[0].owner == "Alice"

    def test_list_filter_by_owner_case_insensitive_reverse(self, store):
        store.create("alice-task", owner="alice")
        tasks = store.list_tasks(owner="ALICE")
        assert len(tasks) == 1

    def test_list_empty(self, store):
        assert store.list_tasks() == []

    def test_list_filter_by_priority(self, store):
        store.create("urgent-task", priority=TaskPriority.urgent)
        store.create("low-task", priority=TaskPriority.low)
        tasks = store.list_tasks(priority=TaskPriority.urgent)
        assert len(tasks) == 1
        assert tasks[0].priority == TaskPriority.urgent

    def test_list_sort_by_priority(self, store):
        store.create("medium-task")
        store.create("low-task", priority=TaskPriority.low)
        store.create("urgent-task", priority=TaskPriority.urgent)
        store.create("high-task", priority=TaskPriority.high)

        tasks = store.list_tasks(sort_by_priority=True)
        assert [task.priority for task in tasks] == [
            TaskPriority.urgent,
            TaskPriority.high,
            TaskPriority.medium,
            TaskPriority.low,
        ]


class TestDependencyResolution:
    """When a task completes, its dependents should get unblocked."""

    def test_completing_task_unblocks_dependent(self, store):
        t1 = store.create("prerequisite")
        t2 = store.create("depends on t1", blocked_by=[t1.id])
        assert t2.status == TaskStatus.blocked

        store.update(t1.id, status=TaskStatus.completed)

        t2_after = store.get(t2.id)
        assert t2_after.status == TaskStatus.pending
        assert t1.id not in t2_after.blocked_by

    def test_partial_unblock_stays_blocked(self, store):
        """If a task depends on two things, completing one shouldn't unblock it."""
        t1 = store.create("dep-1")
        t2 = store.create("dep-2")
        t3 = store.create("needs both", blocked_by=[t1.id, t2.id])

        store.update(t1.id, status=TaskStatus.completed)

        t3_after = store.get(t3.id)
        assert t3_after.status == TaskStatus.blocked
        assert t2.id in t3_after.blocked_by

    def test_full_unblock_after_all_deps_complete(self, store):
        t1 = store.create("dep-1")
        t2 = store.create("dep-2")
        t3 = store.create("needs both", blocked_by=[t1.id, t2.id])

        store.update(t1.id, status=TaskStatus.completed)
        store.update(t2.id, status=TaskStatus.completed)

        t3_after = store.get(t3.id)
        assert t3_after.status == TaskStatus.pending
        assert t3_after.blocked_by == []


class TestTaskLocking:
    def test_lock_acquired_on_in_progress(self, store):
        t = store.create("lockable")
        # mock is_agent_alive to return None (unknown) so lock logic proceeds
        with patch("clawteam.spawn.registry.is_agent_alive", return_value=None):
            updated = store.update(t.id, status=TaskStatus.in_progress, caller="agent-a")
        assert updated.locked_by == "agent-a"

    def test_same_agent_can_relock(self, store):
        t = store.create("lockable")
        with patch("clawteam.spawn.registry.is_agent_alive", return_value=None):
            store.update(t.id, status=TaskStatus.in_progress, caller="agent-a")
            # same agent again, no error
            updated = store.update(t.id, status=TaskStatus.in_progress, caller="agent-a")
        assert updated.locked_by == "agent-a"

    def test_different_agent_blocked_by_lock(self, store):
        t = store.create("contested")
        with patch("clawteam.spawn.registry.is_agent_alive", return_value=True):
            store.update(t.id, status=TaskStatus.in_progress, caller="agent-a")
            with pytest.raises(TaskLockError):
                store.update(t.id, status=TaskStatus.in_progress, caller="agent-b")

    def test_force_overrides_lock(self, store):
        t = store.create("force-me")
        with patch("clawteam.spawn.registry.is_agent_alive", return_value=True):
            store.update(t.id, status=TaskStatus.in_progress, caller="agent-a")
            updated = store.update(
                t.id, status=TaskStatus.in_progress, caller="agent-b", force=True
            )
        assert updated.locked_by == "agent-b"

    def test_dead_agent_lock_is_released(self, store):
        t = store.create("stale-lock")
        with patch("clawteam.spawn.registry.is_agent_alive", return_value=None):
            store.update(t.id, status=TaskStatus.in_progress, caller="dead-agent")

        # now dead-agent is dead, another agent should be able to take over
        with patch("clawteam.spawn.registry.is_agent_alive", return_value=False):
            updated = store.update(t.id, status=TaskStatus.in_progress, caller="live-agent")
        assert updated.locked_by == "live-agent"


class TestDurationTracking:
    """Tests for the started_at / duration tracking feature."""

    def test_started_at_set_on_in_progress(self, store):
        t = store.create("timed task")
        assert t.started_at == ""

        with patch("clawteam.team.tasks.TaskStore._acquire_lock"):
            updated = store.update(t.id, status=TaskStatus.in_progress, caller="a")
        assert updated.started_at != ""

    def test_started_at_not_overwritten_on_second_in_progress(self, store):
        """If a task goes in_progress twice, keep the original start time."""
        t = store.create("double start")
        with patch("clawteam.team.tasks.TaskStore._acquire_lock"):
            updated = store.update(t.id, status=TaskStatus.in_progress, caller="a")
        first_start = updated.started_at

        with patch("clawteam.team.tasks.TaskStore._acquire_lock"):
            updated2 = store.update(t.id, status=TaskStatus.in_progress, caller="a")
        assert updated2.started_at == first_start

    def test_duration_computed_on_completion(self, store):
        t = store.create("will complete")
        with patch("clawteam.team.tasks.TaskStore._acquire_lock"):
            store.update(t.id, status=TaskStatus.in_progress, caller="a")

        completed = store.update(t.id, status=TaskStatus.completed)
        assert "duration_seconds" in completed.metadata
        # duration should be non-negative (task just started moments ago)
        assert completed.metadata["duration_seconds"] >= 0

    def test_no_duration_without_started_at(self, store):
        """Completing a task that was never in_progress shouldn't crash."""
        t = store.create("skip to done")
        completed = store.update(t.id, status=TaskStatus.completed)
        assert "duration_seconds" not in completed.metadata

    def test_started_at_persists_through_serialization(self, store):
        t = store.create("persist check")
        with patch("clawteam.team.tasks.TaskStore._acquire_lock"):
            store.update(t.id, status=TaskStatus.in_progress, caller="a")

        reloaded = store.get(t.id)
        assert reloaded.started_at != ""

    def test_started_at_alias(self):
        """The field should serialize as 'startedAt' (camelCase)."""
        t = TaskItem(subject="alias test")
        dumped = t.model_dump(by_alias=True)
        assert "startedAt" in dumped


class TestGetStats:
    def test_stats_empty_team(self, store):
        stats = store.get_stats()
        assert stats["total"] == 0
        assert stats["completed"] == 0
        assert stats["avg_duration_seconds"] == 0.0

    def test_stats_counts(self, store):
        store.create("one")
        store.create("two")
        t3 = store.create("three")
        store.update(t3.id, status=TaskStatus.completed)

        stats = store.get_stats()
        assert stats["total"] == 3
        assert stats["completed"] == 1
        assert stats["pending"] == 2

    def test_stats_with_timed_tasks(self, store):
        t = store.create("timed")
        with patch("clawteam.team.tasks.TaskStore._acquire_lock"):
            store.update(t.id, status=TaskStatus.in_progress, caller="a")
        store.update(t.id, status=TaskStatus.completed)

        stats = store.get_stats()
        assert stats["timed_completed"] == 1
        assert stats["avg_duration_seconds"] >= 0

    def test_stats_avg_excludes_untimed(self, store):
        """Tasks completed without going through in_progress shouldn't affect avg."""
        # one task goes through the full flow
        t1 = store.create("full flow")
        with patch("clawteam.team.tasks.TaskStore._acquire_lock"):
            store.update(t1.id, status=TaskStatus.in_progress, caller="a")
        store.update(t1.id, status=TaskStatus.completed)

        # another task jumps straight to completed
        t2 = store.create("shortcut")
        store.update(t2.id, status=TaskStatus.completed)

        stats = store.get_stats()
        assert stats["completed"] == 2
        assert stats["timed_completed"] == 1
