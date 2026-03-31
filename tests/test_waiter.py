"""Tests for clawteam.team.waiter — TaskWaiter blocking + completion logic."""

from __future__ import annotations

import signal
from unittest.mock import MagicMock, patch

import pytest

from clawteam.team.models import TaskItem, TaskStatus, TeamMessage
from clawteam.team.waiter import TaskWaiter, WaitResult


def _make_task(
    task_id: str = "t1",
    status: TaskStatus = TaskStatus.pending,
    owner: str = "",
    subject: str = "test task",
) -> TaskItem:
    return TaskItem(id=task_id, subject=subject, status=status, owner=owner)


def _make_message(from_agent: str = "alice", content: str = "hello") -> TeamMessage:
    return TeamMessage(**{"from": from_agent, "content": content})


@pytest.fixture
def mailbox():
    m = MagicMock()
    m.receive.return_value = []
    return m


@pytest.fixture
def store():
    s = MagicMock()
    s.list_tasks.return_value = []
    return s


@pytest.fixture
def waiter(mailbox, store):
    return TaskWaiter(
        team_name="test-team",
        agent_name="leader",
        mailbox=mailbox,
        task_store=store,
        poll_interval=0.01,
    )


class TestZeroTasks:
    """The bug fixed in this PR: zero tasks should complete immediately."""

    def test_zero_tasks_completes_immediately(self, waiter, store):
        store.list_tasks.return_value = []
        result = waiter.wait()
        assert result.status == "completed"
        assert result.total == 0
        assert result.completed == 0
        assert result.elapsed >= 0

    def test_zero_tasks_returns_empty_details(self, waiter, store):
        store.list_tasks.return_value = []
        result = waiter.wait()
        assert result.task_details == []


class TestNormalCompletion:

    def test_all_tasks_completed(self, waiter, store):
        tasks = [
            _make_task("t1", TaskStatus.completed),
            _make_task("t2", TaskStatus.completed),
        ]
        store.list_tasks.return_value = tasks
        result = waiter.wait()
        assert result.status == "completed"
        assert result.total == 2
        assert result.completed == 2

    def test_tasks_complete_over_time(self, waiter, store, mailbox):
        pending = [_make_task("t1", TaskStatus.in_progress)]
        done = [_make_task("t1", TaskStatus.completed)]
        store.list_tasks.side_effect = [pending, done, done]
        mailbox.receive.return_value = []

        result = waiter.wait()
        assert result.status == "completed"
        assert result.total == 1
        assert result.completed == 1

    def test_task_details_included(self, waiter, store):
        tasks = [_make_task("t1", TaskStatus.completed, subject="setup")]
        store.list_tasks.return_value = tasks
        result = waiter.wait()
        assert len(result.task_details) == 1
        assert result.task_details[0]["id"] == "t1"
        assert result.task_details[0]["subject"] == "setup"
        assert result.task_details[0]["status"] == "completed"


class TestTimeout:

    def test_timeout_returns_status(self, store, mailbox):
        store.list_tasks.return_value = [_make_task("t1", TaskStatus.in_progress)]
        mailbox.receive.return_value = []
        waiter = TaskWaiter(
            team_name="test-team",
            agent_name="leader",
            mailbox=mailbox,
            task_store=store,
            poll_interval=0.01,
            timeout=0.05,
        )
        result = waiter.wait()
        assert result.status == "timeout"
        assert result.total == 1
        assert result.in_progress == 1

    def test_timeout_includes_elapsed(self, store, mailbox):
        store.list_tasks.return_value = [_make_task("t1", TaskStatus.pending)]
        mailbox.receive.return_value = []
        waiter = TaskWaiter(
            team_name="test-team",
            agent_name="leader",
            mailbox=mailbox,
            task_store=store,
            poll_interval=0.01,
            timeout=0.03,
        )
        result = waiter.wait()
        assert result.elapsed >= 0.03


class TestInterrupt:

    def test_signal_interrupt(self, waiter, store, mailbox):
        store.list_tasks.return_value = [_make_task("t1", TaskStatus.pending)]
        mailbox.receive.return_value = []

        call_count = 0

        def _list_then_stop():
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                waiter._running = False
            return [_make_task("t1", TaskStatus.pending)]

        store.list_tasks.side_effect = _list_then_stop
        result = waiter.wait()
        assert result.status == "interrupted"

    def test_signal_handlers_restored(self, waiter, store):
        store.list_tasks.return_value = []
        prev_int = signal.getsignal(signal.SIGINT)
        prev_term = signal.getsignal(signal.SIGTERM)
        waiter.wait()
        assert signal.getsignal(signal.SIGINT) is prev_int
        assert signal.getsignal(signal.SIGTERM) is prev_term


class TestProgressCallback:

    def test_progress_called_on_change(self, store, mailbox):
        pending = [_make_task("t1", TaskStatus.pending)]
        done = [_make_task("t1", TaskStatus.completed)]
        store.list_tasks.side_effect = [pending, done, done]
        mailbox.receive.return_value = []

        progress = MagicMock()
        waiter = TaskWaiter(
            team_name="test-team",
            agent_name="leader",
            mailbox=mailbox,
            task_store=store,
            poll_interval=0.01,
            on_progress=progress,
        )
        waiter.wait()
        assert progress.call_count >= 1

    def test_progress_not_called_when_unchanged(self, store, mailbox):
        pending = [_make_task("t1", TaskStatus.pending)]
        done = [_make_task("t1", TaskStatus.completed)]
        store.list_tasks.side_effect = [pending, pending, done, done]
        mailbox.receive.return_value = []

        progress = MagicMock()
        waiter = TaskWaiter(
            team_name="test-team",
            agent_name="leader",
            mailbox=mailbox,
            task_store=store,
            poll_interval=0.01,
            on_progress=progress,
        )
        waiter.wait()
        # "pending" state reported once, "completed" state once → 2 calls
        assert progress.call_count == 2


class TestMessageDraining:

    def test_messages_received_count(self, store, mailbox):
        msg1 = _make_message("alice", "hi")
        msg2 = _make_message("bob", "yo")
        mailbox.receive.side_effect = [[msg1, msg2], [], []]
        store.list_tasks.return_value = []

        waiter = TaskWaiter(
            team_name="test-team",
            agent_name="leader",
            mailbox=mailbox,
            task_store=store,
            poll_interval=0.01,
        )
        result = waiter.wait()
        assert result.messages_received >= 2

    def test_on_message_callback_invoked(self, store, mailbox):
        msg = _make_message("alice", "done")
        mailbox.receive.side_effect = [[msg], [], []]
        store.list_tasks.return_value = []

        handler = MagicMock()
        waiter = TaskWaiter(
            team_name="test-team",
            agent_name="leader",
            mailbox=mailbox,
            task_store=store,
            poll_interval=0.01,
            on_message=handler,
        )
        waiter.wait()
        handler.assert_called_with(msg)

    def test_final_drain_on_completion(self, store, mailbox):
        tasks_done = [_make_task("t1", TaskStatus.completed)]
        store.list_tasks.return_value = tasks_done
        late_msg = _make_message("bob", "late update")
        mailbox.receive.side_effect = [[], [late_msg], []]

        handler = MagicMock()
        waiter = TaskWaiter(
            team_name="test-team",
            agent_name="leader",
            mailbox=mailbox,
            task_store=store,
            poll_interval=0.01,
            on_message=handler,
        )
        result = waiter.wait()
        assert result.messages_received >= 1


class TestDeadAgentRecovery:

    def test_dead_agent_tasks_reset_to_pending(self, store, mailbox):
        in_progress_task = _make_task("t1", TaskStatus.in_progress, owner="dead-worker")
        done_task = _make_task("t1", TaskStatus.completed, owner="dead-worker")

        call_count = 0

        def _evolving_list():
            nonlocal call_count
            call_count += 1
            if call_count <= 1:
                return [in_progress_task]
            return [done_task]

        store.list_tasks.side_effect = _evolving_list
        mailbox.receive.return_value = []

        dead_callback = MagicMock()
        waiter = TaskWaiter(
            team_name="test-team",
            agent_name="leader",
            mailbox=mailbox,
            task_store=store,
            poll_interval=0.01,
            on_agent_dead=dead_callback,
        )

        with patch(
            "clawteam.team.waiter.list_dead_agents",
            return_value=["dead-worker"],
            create=True,
        ), patch(
            "clawteam.spawn.registry.list_dead_agents",
            return_value=["dead-worker"],
        ):
            result = waiter.wait()
        assert result.status == "completed"

    def test_dead_agent_reported_only_once(self, store, mailbox):
        tasks = [_make_task("t1", TaskStatus.in_progress, owner="flaky")]
        done = [_make_task("t1", TaskStatus.completed)]

        call_count = 0

        def _evolving():
            nonlocal call_count
            call_count += 1
            return done if call_count > 2 else tasks

        store.list_tasks.side_effect = _evolving
        mailbox.receive.return_value = []

        dead_callback = MagicMock()
        waiter = TaskWaiter(
            team_name="test-team",
            agent_name="leader",
            mailbox=mailbox,
            task_store=store,
            poll_interval=0.01,
            on_agent_dead=dead_callback,
        )

        with patch(
            "clawteam.spawn.registry.list_dead_agents",
            return_value=["flaky"],
        ):
            waiter.wait()

        dead_calls = [c for c in dead_callback.call_args_list if c[0][0] == "flaky"]
        assert len(dead_calls) == 1

    def test_import_error_skips_dead_check(self, store, mailbox):
        """If spawn.registry is unavailable, dead-agent check is silently skipped."""
        store.list_tasks.return_value = []
        mailbox.receive.return_value = []
        waiter = TaskWaiter(
            team_name="test-team",
            agent_name="leader",
            mailbox=mailbox,
            task_store=store,
            poll_interval=0.01,
        )
        with patch(
            "clawteam.team.waiter.list_dead_agents",
            side_effect=ImportError,
            create=True,
        ):
            result = waiter.wait()
        assert result.status == "completed"


class TestWaitResult:

    def test_default_values(self):
        r = WaitResult(status="completed")
        assert r.elapsed == 0.0
        assert r.total == 0
        assert r.completed == 0
        assert r.in_progress == 0
        assert r.pending == 0
        assert r.blocked == 0
        assert r.messages_received == 0
        assert r.task_details == []

    def test_mixed_status_counts(self, store, mailbox):
        tasks = [
            _make_task("t1", TaskStatus.completed),
            _make_task("t2", TaskStatus.in_progress),
            _make_task("t3", TaskStatus.pending),
            _make_task("t4", TaskStatus.blocked),
        ]
        store.list_tasks.return_value = tasks
        mailbox.receive.return_value = []

        waiter = TaskWaiter(
            team_name="test-team",
            agent_name="leader",
            mailbox=mailbox,
            task_store=store,
            poll_interval=0.01,
            timeout=0.03,
        )
        result = waiter.wait()
        assert result.status == "timeout"
        assert result.total == 4
        assert result.completed == 1
        assert result.in_progress == 1
        assert result.pending == 1
        assert result.blocked == 1
