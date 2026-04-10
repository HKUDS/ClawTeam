"""Tests for clawteam.events — EventBus, hooks, and global bus."""

import time
from subprocess import CompletedProcess

from clawteam.events.bus import EventBus
from clawteam.events.types import (
    AfterWorkerSpawn,
    BeforeWorkerSpawn,
    TaskCompleted,
    WorkerExit,
)


class TestEventBus:
    def test_subscribe_and_emit(self):
        bus = EventBus()
        received = []
        bus.subscribe(WorkerExit, lambda e: received.append(e))
        bus.emit(WorkerExit(team_name="t", agent_name="a"))
        assert len(received) == 1
        assert received[0].agent_name == "a"

    def test_priority_ordering(self):
        bus = EventBus()
        order = []
        bus.subscribe(WorkerExit, lambda e: order.append("low"), priority=10)
        bus.subscribe(WorkerExit, lambda e: order.append("high"), priority=0)
        bus.emit(WorkerExit(team_name="t"))
        assert order == ["high", "low"]

    def test_unsubscribe(self):
        bus = EventBus()
        calls = []

        def handler(_event):
            calls.append(1)

        bus.subscribe(WorkerExit, handler)
        bus.emit(WorkerExit(team_name="t"))
        assert len(calls) == 1
        bus.unsubscribe(WorkerExit, handler)
        bus.emit(WorkerExit(team_name="t"))
        assert len(calls) == 1  # no new call

    def test_veto_pattern(self):
        bus = EventBus()

        def veto_handler(e):
            e.veto = True

        bus.subscribe(BeforeWorkerSpawn, veto_handler)
        event = BeforeWorkerSpawn(team_name="t", agent_name="a", command=["claude"])
        bus.emit(event)
        assert event.veto is True

    def test_emit_collects_results(self):
        bus = EventBus()
        bus.subscribe(WorkerExit, lambda e: "ok")
        bus.subscribe(WorkerExit, lambda e: 42)
        results = bus.emit(WorkerExit(team_name="t"))
        assert results == ["ok", 42]

    def test_handler_exception_does_not_crash(self):
        bus = EventBus()
        bus.subscribe(WorkerExit, lambda e: 1 / 0)
        bus.subscribe(WorkerExit, lambda e: "ok")
        results = bus.emit(WorkerExit(team_name="t"))
        assert "ok" in results

    def test_emit_async(self):
        bus = EventBus()
        received = []
        bus.subscribe(TaskCompleted, lambda e: received.append(e.task_id))
        bus.emit_async(TaskCompleted(team_name="t", task_id="123"))
        time.sleep(0.5)
        assert received == ["123"]

    def test_handler_count(self):
        bus = EventBus()
        assert bus.handler_count() == 0
        bus.subscribe(WorkerExit, lambda e: None)
        bus.subscribe(AfterWorkerSpawn, lambda e: None)
        assert bus.handler_count() == 2
        assert bus.handler_count(WorkerExit) == 1

    def test_clear(self):
        bus = EventBus()
        bus.subscribe(WorkerExit, lambda e: None)
        bus.clear()
        assert bus.handler_count() == 0

    def test_different_event_types_isolated(self):
        bus = EventBus()
        exit_calls = []
        spawn_calls = []
        bus.subscribe(WorkerExit, lambda e: exit_calls.append(1))
        bus.subscribe(AfterWorkerSpawn, lambda e: spawn_calls.append(1))
        bus.emit(WorkerExit(team_name="t"))
        assert len(exit_calls) == 1
        assert len(spawn_calls) == 0


class TestHookManager:
    def test_shell_hook(self, tmp_path):
        from clawteam.events.hooks import HookDef, HookManager

        bus = EventBus()
        mgr = HookManager(bus)

        marker = tmp_path / "marker.txt"
        hook = HookDef(
            event="WorkerExit",
            action="shell",
            command=f"touch {marker}",
        )
        assert mgr.register_hook(hook) is True
        bus.emit(WorkerExit(team_name="test"))
        assert marker.exists()

    def test_shell_hook_exports_clawteam_and_legacy_env_vars(self, monkeypatch):
        from clawteam.events.hooks import HookDef, HookManager

        bus = EventBus()
        mgr = HookManager(bus)
        captured = {}

        def fake_run(command, shell, env, capture_output, timeout):
            captured.update(env)
            return CompletedProcess(args=command, returncode=0)

        monkeypatch.setattr("clawteam.events.hooks.subprocess.run", fake_run)

        hook = HookDef(event="WorkerExit", action="shell", command="echo ok")
        assert mgr.register_hook(hook) is True

        bus.emit(WorkerExit(team_name="test", agent_name="worker", abandoned_tasks=["t1", "t2"]))

        assert captured["CLAWTEAM_EVENT_TYPE"] == "WorkerExit"
        assert captured["CLAWTEAM_AGENT_NAME"] == "worker"
        assert captured["OH_AGENT_NAME"] == "worker"
        assert captured["CLAWTEAM_ABANDONED_TASKS"] == "t1,t2"
        assert captured["OH_ABANDONED_TASKS"] == "t1,t2"

    def test_disabled_hook_not_loaded(self):
        from clawteam.events.hooks import HookDef, HookManager

        bus = EventBus()
        mgr = HookManager(bus)
        count = mgr.load_hooks([
            HookDef(event="WorkerExit", action="shell", command="echo hi", enabled=False),
        ])
        assert count == 0

    def test_unknown_event_type(self):
        from clawteam.events.hooks import HookDef, HookManager

        bus = EventBus()
        mgr = HookManager(bus)
        assert mgr.register_hook(HookDef(event="NoSuchEvent", action="shell", command="echo")) is False

    def test_unregister_all(self):
        from clawteam.events.hooks import HookDef, HookManager

        bus = EventBus()
        mgr = HookManager(bus)
        mgr.load_hooks([
            HookDef(event="WorkerExit", action="shell", command="echo a"),
            HookDef(event="TaskCompleted", action="shell", command="echo b"),
        ])
        assert bus.handler_count() == 2
        mgr.unregister_all()
        assert bus.handler_count() == 0


class TestGlobalBus:
    def test_singleton(self):
        from clawteam.events.global_bus import get_event_bus, reset_event_bus

        reset_event_bus()
        bus1 = get_event_bus()
        bus2 = get_event_bus()
        assert bus1 is bus2
        reset_event_bus()

    def test_reset(self):
        from clawteam.events.global_bus import get_event_bus, reset_event_bus

        reset_event_bus()
        bus1 = get_event_bus()
        bus1.subscribe(WorkerExit, lambda e: None)
        reset_event_bus()
        bus2 = get_event_bus()
        assert bus2.handler_count() == 0
        reset_event_bus()
