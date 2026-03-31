from __future__ import annotations

import io
import json
from pathlib import Path

from clawteam.board.collector import BoardCollector
from clawteam.board.server import BoardHandler
from clawteam.team.mailbox import MailboxManager
from clawteam.team.manager import TeamManager


def _make_post_handler(path: str, payload: str = "", headers: dict[str, str] | None = None):
    handler = object.__new__(BoardHandler)
    handler.path = path
    handler.headers = {"Content-Length": str(len(payload.encode("utf-8"))), **(headers or {})}
    handler.rfile = io.BytesIO(payload.encode("utf-8"))
    handler.wfile = io.BytesIO()
    served: dict[str, object] = {}
    errors: list[tuple[int, str | None]] = []
    handler._serve_json = lambda data: served.setdefault("data", data)
    handler.send_error = lambda code, message=None: errors.append((code, message))
    return handler, served, errors


def test_collect_overview_does_not_call_collect_team(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path))
    TeamManager.create_team(
        name="demo",
        leader_name="leader",
        leader_id="leader001",
        description="demo team",
    )

    def fail_collect_team(self, team_name: str):
        raise AssertionError("collect_team should not be called for overview")

    monkeypatch.setattr(BoardCollector, "collect_team", fail_collect_team)

    teams = BoardCollector().collect_overview()

    assert teams == [
        {
            "name": "demo",
            "description": "demo team",
            "leader": "leader",
            "members": 1,
            "tasks": 0,
            "pendingMessages": 0,
        }
    ]


def test_collect_overview_sums_inbox_counts_for_all_members(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path))
    TeamManager.create_team(
        name="demo",
        leader_name="leader",
        leader_id="leader001",
        description="demo team",
    )
    TeamManager.add_member("demo", "worker", "worker001")
    MailboxManager("demo").send(from_agent="leader", to="worker", content="hello")

    def fail_collect_team(self, team_name: str):
        raise AssertionError("collect_team should not be called for overview")

    monkeypatch.setattr(BoardCollector, "collect_team", fail_collect_team)

    teams = BoardCollector().collect_overview()

    assert teams == [
        {
            "name": "demo",
            "description": "demo team",
            "leader": "leader",
            "members": 2,
            "tasks": 0,
            "pendingMessages": 1,
        }
    ]


def test_team_snapshot_cache_reuses_value_within_ttl():
    from clawteam.board.server import TeamSnapshotCache

    calls = {"count": 0}

    def loader():
        calls["count"] += 1
        return {"version": calls["count"]}

    cache = TeamSnapshotCache(ttl_seconds=60.0)

    first = cache.get("demo", loader)
    second = cache.get("demo", loader)

    assert first == {"version": 1}
    assert second == {"version": 1}
    assert calls["count"] == 1


def test_team_snapshot_cache_expires_after_ttl(monkeypatch):
    from clawteam.board.server import TeamSnapshotCache

    now = {"value": 100.0}
    monkeypatch.setattr("clawteam.board.server.time.monotonic", lambda: now["value"])

    calls = {"count": 0}

    def loader():
        calls["count"] += 1
        return {"version": calls["count"]}

    cache = TeamSnapshotCache(ttl_seconds=5.0)

    first = cache.get("demo", loader)
    now["value"] += 10.0
    second = cache.get("demo", loader)

    assert first == {"version": 1}
    assert second == {"version": 2}
    assert calls["count"] == 2


def test_collect_team_preserves_conflicts_field(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path))
    TeamManager.create_team(
        name="demo",
        leader_name="leader",
        leader_id="leader001",
        description="demo team",
    )

    data = BoardCollector().collect_team("demo")

    assert "conflicts" in data


def test_collect_team_exposes_member_inbox_identity(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path))
    TeamManager.create_team(
        name="demo",
        leader_name="leader",
        leader_id="leader001",
        description="demo team",
    )
    TeamManager.add_member("demo", "worker", "worker001", user="alice")

    data = BoardCollector().collect_team("demo")

    worker = next(member for member in data["members"] if member["name"] == "worker")
    assert worker["memberKey"] == "alice_worker"
    assert worker["inboxName"] == "alice_worker"


def test_collect_team_normalizes_message_participants(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path))
    TeamManager.create_team(
        name="demo",
        leader_name="leader",
        leader_id="leader001",
        description="demo team",
    )
    TeamManager.add_member("demo", "worker", "worker001", user="alice")
    mailbox = MailboxManager("demo")
    mailbox.send(from_agent="leader", to="worker", content="hello")
    mailbox.broadcast(from_agent="leader", content="broadcast")

    data = BoardCollector().collect_team("demo")

    direct = next(msg for msg in data["messages"] if msg.get("content") == "hello")
    assert direct["fromKey"] == "leader"
    assert direct["fromLabel"] == "leader"
    assert direct["toKey"] == "alice_worker"
    assert direct["toLabel"] == "worker"
    assert direct["isBroadcast"] is False

    broadcast = next(
        msg
        for msg in data["messages"]
        if msg.get("content") == "broadcast" and msg.get("to") == "alice_worker"
    )
    assert broadcast["fromKey"] == "leader"
    assert broadcast["toKey"] == "alice_worker"
    assert broadcast["toLabel"] == "worker"
    assert broadcast["isBroadcast"] is True


def test_collect_overview_preserves_broken_team_fallback(monkeypatch):
    def fake_discover():
        return [
            {
                "name": "good",
                "description": "good team",
                "memberCount": 1,
            },
            {
                "name": "broken",
                "description": "broken team",
                "memberCount": 7,
            },
        ]

    def fake_summary(self, team_name: str):
        if team_name == "broken":
            raise ValueError("boom")
        return {
            "name": "good",
            "description": "good team",
            "leader": "lead",
            "members": 1,
            "tasks": 3,
            "pendingMessages": 2,
        }

    monkeypatch.setattr(TeamManager, "discover_teams", staticmethod(fake_discover))
    monkeypatch.setattr(BoardCollector, "collect_team_summary", fake_summary)

    overview = BoardCollector().collect_overview()

    assert overview == [
        {
            "name": "good",
            "description": "good team",
            "leader": "lead",
            "members": 1,
            "tasks": 3,
            "pendingMessages": 2,
        },
        {
            "name": "broken",
            "description": "broken team",
            "leader": "",
            "members": 7,
            "tasks": 0,
            "pendingMessages": 0,
        },
    ]


def test_serve_team_reads_fresh_snapshot_without_cache(monkeypatch):
    calls = {"count": 0}
    served = {}

    class FakeCache:
        def get(self, team_name, loader):
            raise AssertionError("team cache should not be used for /api/team")

    handler = object.__new__(BoardHandler)
    handler.collector = type(
        "Collector",
        (),
        {
            "collect_team": staticmethod(
                lambda team_name: calls.__setitem__("count", calls["count"] + 1)
                or {"team": {"name": team_name}}
            )
        },
    )()
    handler.team_cache = FakeCache()
    handler._serve_json = lambda data: served.setdefault("data", data)

    handler._serve_team("demo")

    assert calls["count"] == 1
    assert served["data"] == {"team": {"name": "demo"}}


def test_serve_sse_uses_shared_team_snapshot_cache(monkeypatch):
    calls = {"count": 0}

    class FakeCache:
        def get(self, team_name, loader):
            calls["count"] += 1
            return loader()

    handler = object.__new__(BoardHandler)
    handler.collector = type(
        "Collector",
        (),
        {"collect_team": staticmethod(lambda team_name: {"team": {"name": team_name}})},
    )()
    handler.team_cache = FakeCache()
    handler.interval = 0.0
    handler.wfile = io.BytesIO()
    handler.send_response = lambda code: None
    handler.send_header = lambda name, value: None
    handler.end_headers = lambda: None
    monkeypatch.setattr(
        handler.wfile,
        "flush",
        lambda: (_ for _ in ()).throw(BrokenPipeError()),
    )

    handler._serve_sse("demo")

    assert calls["count"] == 1


def test_do_post_creates_task_for_team_path(monkeypatch):
    created: dict[str, str] = {}

    class FakeTaskStore:
        def __init__(self, team_name: str):
            created["team_name"] = team_name

        def create(self, subject: str, description: str, owner: str):
            created["subject"] = subject
            created["description"] = description
            created["owner"] = owner
            return type("Task", (), {"id": "task-123"})()

    monkeypatch.setattr("clawteam.team.tasks.TaskStore", FakeTaskStore)
    payload = json.dumps({"subject": "Test task", "description": "details", "owner": "leader"})
    handler, served, errors = _make_post_handler("/api/team/demo/task", payload=payload)

    handler.do_POST()

    assert created == {
        "team_name": "demo",
        "subject": "Test task",
        "description": "details",
        "owner": "leader",
    }
    assert served["data"] == {"status": "ok", "task_id": "task-123"}
    assert errors == []


def test_do_post_invalid_json_returns_400_error(monkeypatch):
    class FakeTaskStore:
        def __init__(self, team_name: str):
            raise AssertionError("TaskStore should not be instantiated for invalid JSON")

    monkeypatch.setattr("clawteam.team.tasks.TaskStore", FakeTaskStore)
    handler, served, errors = _make_post_handler("/api/team/demo/task", payload="{not-json")

    handler.do_POST()

    assert "data" not in served
    assert len(errors) == 1
    assert errors[0][0] == 400


def test_do_post_missing_or_empty_subject_is_forwarded_as_empty(monkeypatch):
    calls: list[str] = []

    class FakeTaskStore:
        def __init__(self, team_name: str):
            pass

        def create(self, subject: str, description: str, owner: str):
            calls.append(subject)
            return type("Task", (), {"id": "task-1"})()

    monkeypatch.setattr("clawteam.team.tasks.TaskStore", FakeTaskStore)

    missing_subject, served_missing, errors_missing = _make_post_handler(
        "/api/team/demo/task",
        payload=json.dumps({"description": "details"}),
    )
    missing_subject.do_POST()

    empty_subject, served_empty, errors_empty = _make_post_handler(
        "/api/team/demo/task",
        payload=json.dumps({"subject": "", "description": "details"}),
    )
    empty_subject.do_POST()

    assert calls == ["", ""]
    assert served_missing["data"] == {"status": "ok", "task_id": "task-1"}
    assert served_empty["data"] == {"status": "ok", "task_id": "task-1"}
    assert errors_missing == []
    assert errors_empty == []


def test_do_post_task_path_variants_return_404(monkeypatch):
    class FakeTaskStore:
        def __init__(self, team_name: str):
            raise AssertionError("TaskStore should not be instantiated for invalid paths")

    monkeypatch.setattr("clawteam.team.tasks.TaskStore", FakeTaskStore)
    invalid_paths = [
        "/api/team/demo",
        "/api/team/demo/task/extra",
        "/api/team/demo/extra/task",
        "/api/team//task",
        "/api/team/task",
    ]

    for path in invalid_paths:
        handler, served, errors = _make_post_handler(path, payload=json.dumps({"subject": "x"}))
        handler.do_POST()
        assert "data" not in served
        assert errors == [(404, None)]


def test_do_post_decodes_urlencoded_team_name(monkeypatch):
    captured: dict[str, str] = {}

    class FakeTaskStore:
        def __init__(self, team_name: str):
            captured["team_name"] = team_name

        def create(self, subject: str, description: str, owner: str):
            return type("Task", (), {"id": "task-encoded"})()

    monkeypatch.setattr("clawteam.team.tasks.TaskStore", FakeTaskStore)
    handler, served, errors = _make_post_handler(
        "/api/team/demo%20team/task",
        payload=json.dumps({"subject": "encoded"}),
    )

    handler.do_POST()

    assert captured["team_name"] == "demo team"
    assert served["data"] == {"status": "ok", "task_id": "task-encoded"}
    assert errors == []



def test_do_post_rejects_decoded_team_name_with_path_separator(monkeypatch):
    class FakeTaskStore:
        def __init__(self, team_name: str):
            raise AssertionError("TaskStore should not be instantiated for unsafe team names")

    monkeypatch.setattr("clawteam.team.tasks.TaskStore", FakeTaskStore)
    handler, served, errors = _make_post_handler(
        "/api/team/%2Ftmp%2Fevil/task",
        payload=json.dumps({"subject": "encoded"}),
    )

    handler.do_POST()

    assert "data" not in served
    assert errors == [(404, None)]


def test_do_post_rejects_decoded_team_name_with_nested_path_separator(monkeypatch):
    class FakeTaskStore:
        def __init__(self, team_name: str):
            raise AssertionError("TaskStore should not be instantiated for unsafe team names")

    monkeypatch.setattr("clawteam.team.tasks.TaskStore", FakeTaskStore)
    handler, served, errors = _make_post_handler(
        "/api/team/demo%2Fevil/task",
        payload=json.dumps({"subject": "encoded"}),
    )

    handler.do_POST()

    assert "data" not in served
    assert errors == [(404, None)]


def test_do_post_rejects_decoded_team_name_with_traversal_component(monkeypatch):
    class FakeTaskStore:
        def __init__(self, team_name: str):
            raise AssertionError("TaskStore should not be instantiated for unsafe team names")

    monkeypatch.setattr("clawteam.team.tasks.TaskStore", FakeTaskStore)
    handler, served, errors = _make_post_handler(
        "/api/team/%2E%2E/task",
        payload=json.dumps({"subject": "encoded"}),
    )

    handler.do_POST()

    assert "data" not in served
    assert errors == [(404, None)]
