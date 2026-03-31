from __future__ import annotations

import io
import socket
from pathlib import Path

import pytest

from clawteam.board.collector import BoardCollector
from clawteam.board.server import BoardHandler, _fetch_proxy_content, _normalize_proxy_target
from clawteam.team.mailbox import MailboxManager
from clawteam.team.manager import TeamManager


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


def test_serve_proxy_returns_504_on_timeout(monkeypatch):
    handler = object.__new__(BoardHandler)
    handler.proxy_timeout_seconds = 0.01
    handler.proxy_max_bytes = 2 * 1024 * 1024
    handler.proxy_chunk_size = 1024
    handler.wfile = io.BytesIO()

    captured = {}
    handler.send_error = lambda code, msg=None: captured.setdefault("error", (code, msg))
    handler.send_response = lambda code: captured.setdefault("status", code)
    handler.send_header = lambda name, value: None
    handler.end_headers = lambda: None

    def fake_urlopen(req, timeout=None):
        raise socket.timeout("slow upstream")

    monkeypatch.setattr("clawteam.board.server.urllib.request.urlopen", fake_urlopen)

    handler._serve_proxy("https://example.com/slow.txt")

    assert captured["error"] == (504, "Proxy request timed out")


def test_serve_proxy_returns_413_for_oversized_content_length(monkeypatch):
    handler = object.__new__(BoardHandler)
    handler.proxy_timeout_seconds = 1
    handler.proxy_max_bytes = 1024
    handler.proxy_chunk_size = 256
    handler.wfile = io.BytesIO()

    captured = {}
    handler.send_error = lambda code, msg=None: captured.setdefault("error", (code, msg))
    handler.send_response = lambda code: captured.setdefault("status", code)
    handler.send_header = lambda name, value: None
    handler.end_headers = lambda: None

    class FakeResponse:
        def __init__(self):
            self.headers = {"Content-Length": "2048"}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self, size=-1):
            return b""

    monkeypatch.setattr(
        "clawteam.board.server.urllib.request.urlopen",
        lambda req, timeout=None: FakeResponse(),
    )

    handler._serve_proxy("https://example.com/large.txt")

    assert captured["error"] == (413, "Response too large")


def test_serve_proxy_streams_chunks_without_content_length(monkeypatch):
    handler = object.__new__(BoardHandler)
    handler.proxy_timeout_seconds = 1
    handler.proxy_max_bytes = 4096
    handler.proxy_chunk_size = 4
    handler.wfile = io.BytesIO()

    headers = []
    status = {}
    handler.send_error = lambda code, msg=None: (_ for _ in ()).throw(AssertionError((code, msg)))
    handler.send_response = lambda code: status.setdefault("code", code)
    handler.send_header = lambda name, value: headers.append((name, value))
    handler.end_headers = lambda: None

    class FakeResponse:
        def __init__(self):
            self.headers = {}
            self._chunks = [b"abcd", b"ef", b""]

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self, size=-1):
            return self._chunks.pop(0)

    monkeypatch.setattr(
        "clawteam.board.server.urllib.request.urlopen",
        lambda req, timeout=None: FakeResponse(),
    )

    handler._serve_proxy("https://example.com/chunked.txt")

    assert status["code"] == 200
    assert ("Content-Length", "6") in headers
    assert handler.wfile.getvalue() == b"abcdef"


def test_serve_proxy_returns_413_for_oversized_chunked_response(monkeypatch):
    handler = object.__new__(BoardHandler)
    handler.proxy_timeout_seconds = 1
    handler.proxy_max_bytes = 5
    handler.proxy_chunk_size = 4
    handler.wfile = io.BytesIO()

    captured = {"statuses": []}
    handler.send_error = lambda code, msg=None: captured.setdefault("error", (code, msg))
    handler.send_response = lambda code: captured["statuses"].append(code)
    handler.send_header = lambda name, value: None
    handler.end_headers = lambda: None

    class FakeResponse:
        def __init__(self):
            self.headers = {}
            self._chunks = [b"abcd", b"ef", b""]

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self, size=-1):
            return self._chunks.pop(0)

    monkeypatch.setattr(
        "clawteam.board.server.urllib.request.urlopen",
        lambda req, timeout=None: FakeResponse(),
    )

    handler._serve_proxy("https://example.com/chunked-large.txt")

    assert captured["error"] == (413, "Response too large")
    assert captured["statuses"] == []
