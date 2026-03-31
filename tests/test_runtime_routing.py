from __future__ import annotations

from datetime import datetime, timezone

from clawteam.team.models import MessageType, TeamMessage
from clawteam.team.router import RuntimeRouter
from clawteam.team.routing_policy import DefaultRoutingPolicy, RuntimeEnvelope
from clawteam.team.watcher import InboxWatcher


def _utc(hour: int, minute: int = 0, second: int = 0) -> datetime:
    return datetime(2026, 3, 24, hour, minute, second, tzinfo=timezone.utc)


def test_runtime_router_normalizes_team_message_to_runtime_envelope(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path))
    router = RuntimeRouter(team_name="demo", agent_name="worker")
    message = TeamMessage(
        type=MessageType.message,
        from_agent="leader",
        to="worker",
        content="Auth module complete.",
        summary="12 tests passed",
        plan_file="/tmp/plan.md",
    )

    envelope = router.normalize_message(message)

    assert envelope.source == "leader"
    assert envelope.target == "worker"
    assert envelope.channel == "direct"
    assert envelope.priority == "medium"
    assert envelope.summary == "Auth module complete."
    assert "summary: 12 tests passed" in envelope.evidence
    assert "planFile: /tmp/plan.md" in envelope.evidence


def test_default_routing_policy_throttles_same_source_target_and_tracks_pending_state(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path))
    policy = DefaultRoutingPolicy(team_name="demo", throttle_seconds=30)

    first = RuntimeEnvelope(source="leader", target="worker", summary="Initial update")
    first_decision = policy.decide(first, now=_utc(10, 0, 0))
    policy.record_dispatch_result(first_decision, success=True, now=_utc(10, 0, 0))

    second = RuntimeEnvelope(source="leader", target="worker", summary="Second update")
    second_decision = policy.decide(second, now=_utc(10, 0, 5))

    assert first_decision.action == "inject"
    assert second_decision.action == "aggregate"

    state = policy.read_state()
    route = state["routes"]["leader->worker"]
    assert route["pendingCount"] == 1
    assert route["pendingSummaries"] == ["Second update"]
    assert route["flushAfter"] == _utc(10, 0, 30).isoformat()


def test_runtime_router_dispatches_and_flushes_aggregated_messages(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path))

    class StubBackend:
        def __init__(self):
            self.calls: list[tuple[str, str, RuntimeEnvelope]] = []

        def inject_runtime_message(self, team, agent_name, envelope):
            self.calls.append((team, agent_name, envelope))
            return True, "ok"

    backend = StubBackend()
    policy = DefaultRoutingPolicy(team_name="demo", throttle_seconds=30)
    router = RuntimeRouter(
        team_name="demo",
        agent_name="alice_worker",
        session_agent_name="worker",
        backend=backend,
        policy=policy,
    )

    router.route_message(
        TeamMessage(type=MessageType.message, from_agent="leader", to="worker", content="Initial update"),
        now=_utc(10, 0, 0),
    )
    aggregate_decision = router.route_message(
        TeamMessage(type=MessageType.message, from_agent="leader", to="worker", content="Second update"),
        now=_utc(10, 0, 5),
    )
    flushed = router.flush_due(now=_utc(10, 0, 31))

    assert aggregate_decision.action == "aggregate"
    assert len(backend.calls) == 2
    assert backend.calls[0][0:2] == ("demo", "worker")
    assert backend.calls[1][2].summary == "1 queued runtime update from leader."
    assert "Second update" in backend.calls[1][2].evidence[0]
    assert len(flushed) == 1

    state = policy.read_state()
    route = state["routes"]["leader->worker"]
    assert route["pendingCount"] == 0
    assert route["lastDispatchStatus"] == "flushed"
    assert route["lastInjectedAt"] == _utc(10, 0, 31).isoformat()


def test_default_routing_policy_failed_initial_injection_uses_retry_backoff(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path))
    policy = DefaultRoutingPolicy(team_name="demo", throttle_seconds=30)

    first = RuntimeEnvelope(source="leader", target="worker", summary="Initial update")
    decision = policy.decide(first, now=_utc(10, 0, 0))
    policy.record_dispatch_result(
        decision,
        success=False,
        now=_utc(10, 0, 0),
        error="tmux target missing",
    )

    state = policy.read_state()
    route = state["routes"]["leader->worker"]
    assert route["pendingCount"] == 1
    assert route["lastDispatchStatus"] == "failed"
    assert route["flushAfter"] == _utc(10, 0, 30).isoformat()
    assert policy.flush_due(now=_utc(10, 0, 1)) == []
    assert len(policy.flush_due(now=_utc(10, 0, 30))) == 1


def test_default_routing_policy_failed_flush_uses_retry_backoff(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path))
    policy = DefaultRoutingPolicy(team_name="demo", throttle_seconds=30)

    first = RuntimeEnvelope(source="leader", target="worker", summary="Initial update")
    first_decision = policy.decide(first, now=_utc(10, 0, 0))
    policy.record_dispatch_result(first_decision, success=True, now=_utc(10, 0, 0))

    second = RuntimeEnvelope(source="leader", target="worker", summary="Second update")
    policy.decide(second, now=_utc(10, 0, 5))

    flush_decision = policy.flush_due(now=_utc(10, 0, 31))[0]
    policy.record_dispatch_result(
        flush_decision,
        success=False,
        now=_utc(10, 0, 31),
        error="tmux target missing",
    )

    state = policy.read_state()
    route = state["routes"]["leader->worker"]
    assert route["pendingCount"] == 1
    assert route["lastDispatchStatus"] == "failed"
    assert route["flushAfter"] == _utc(10, 1, 1).isoformat()
    assert policy.flush_due(now=_utc(10, 0, 32)) == []
    assert len(policy.flush_due(now=_utc(10, 1, 1))) == 1


def test_inbox_watcher_default_mode_preserves_existing_output_and_exec_behavior():
    class DummyMailbox:
        def receive(self, *_args, **_kwargs):
            return []

    message = TeamMessage(type=MessageType.message, from_agent="leader", to="worker", content="hello")
    watcher = InboxWatcher(team_name="demo", agent_name="worker", mailbox=DummyMailbox(), exec_cmd="echo ok")
    seen: list[str] = []
    exec_seen: list[str] = []

    watcher._output = lambda msg: seen.append(msg.content or "")
    watcher._run_callback = lambda msg: exec_seen.append(msg.content or "")
    watcher._handle_message(message)

    assert seen == ["hello"]
    assert exec_seen == ["hello"]


def test_inbox_watcher_runtime_mode_routes_messages():
    class DummyMailbox:
        def receive(self, *_args, **_kwargs):
            return []

    class DummyRouter:
        def __init__(self):
            self.messages: list[TeamMessage] = []

        def route_message(self, msg, now=None):
            self.messages.append(msg)
            return None

    message = TeamMessage(type=MessageType.message, from_agent="leader", to="worker", content="hello")
    router = DummyRouter()
    watcher = InboxWatcher(team_name="demo", agent_name="worker", mailbox=DummyMailbox(), runtime_router=router)
    watcher._output = lambda _msg: None
    watcher._handle_message(message)

    assert [msg.content for msg in router.messages] == ["hello"]


def test_inbox_watcher_json_mode_keeps_runtime_warning_off_stdout(capsys):
    class DummyMailbox:
        def receive(self, *_args, **_kwargs):
            return []

    class FailingRouter:
        def route_message(self, _msg, now=None):
            raise RuntimeError("route boom")

    message = TeamMessage(type=MessageType.message, from_agent="leader", to="worker", content="hello")
    watcher = InboxWatcher(
        team_name="demo",
        agent_name="worker",
        mailbox=DummyMailbox(),
        json_output=True,
        runtime_router=FailingRouter(),
    )

    watcher._handle_message(message)
    captured = capsys.readouterr()

    assert captured.out.strip() == message.model_dump_json(by_alias=True, exclude_none=True)
    assert captured.err.strip() == "[warn] runtime routing failed: route boom"


def test_inbox_watcher_json_mode_flush_warning_goes_to_stderr(capsys):
    class DummyMailbox:
        def receive(self, *_args, **_kwargs):
            return []

    class FailingRouter:
        def flush_due(self, now=None):
            raise RuntimeError("flush boom")

    watcher = InboxWatcher(
        team_name="demo",
        agent_name="worker",
        mailbox=DummyMailbox(),
        json_output=True,
        runtime_router=FailingRouter(),
    )

    watcher._flush_runtime_routes()
    captured = capsys.readouterr()

    assert captured.out == ""
    assert captured.err.strip() == "[warn] runtime flush failed: flush boom"


def test_inbox_watcher_default_mode_keeps_runtime_warning_readable_on_stdout(capsys):
    class DummyMailbox:
        def receive(self, *_args, **_kwargs):
            return []

    class FailingRouter:
        def route_message(self, _msg, now=None):
            raise RuntimeError("route boom")

    message = TeamMessage(type=MessageType.message, from_agent="leader", to="worker", content="hello")
    watcher = InboxWatcher(
        team_name="demo",
        agent_name="worker",
        mailbox=DummyMailbox(),
        runtime_router=FailingRouter(),
    )

    watcher._handle_message(message)
    captured = capsys.readouterr()

    assert captured.err == ""
    assert "[warn] runtime routing failed: route boom" in captured.out
