"""Tests for clawteam.team.mailbox — MailboxManager send/receive/broadcast."""

import json
import os
import socket
import time
from pathlib import Path

import pytest

from clawteam.team.mailbox import MailboxManager
from clawteam.team.manager import TeamManager
from clawteam.team.models import MessageType, get_data_dir
from clawteam.transport.file import FileTransport, try_lock


@staticmethod
def _make_mailbox(team_name: str) -> MailboxManager:
    """Create a mailbox with an explicit FileTransport (skip env/config resolution)."""
    transport = FileTransport(team_name)
    return MailboxManager(team_name, transport=transport)


def _inbox_path(team_name: str, agent_name: str) -> Path:
    inbox = get_data_dir() / "teams" / team_name / "inboxes" / agent_name
    inbox.mkdir(parents=True, exist_ok=True)
    return inbox


def _dead_letter_root(team_name: str, agent_name: str) -> Path:
    return get_data_dir() / "teams" / team_name / "dead_letters" / agent_name


def _peer_path(team_name: str, agent_name: str) -> Path:
    peer = get_data_dir() / "teams" / team_name / "peers" / f"{agent_name}.json"
    peer.parent.mkdir(parents=True, exist_ok=True)
    return peer


class TestSendReceive:
    def test_send_and_receive_single(self, team_name):
        mb = _make_mailbox(team_name)
        mb.send(from_agent="alice", to="bob", content="hey")

        msgs = mb.receive("bob")
        assert len(msgs) == 1
        assert msgs[0].from_agent == "alice"
        assert msgs[0].content == "hey"
        assert msgs[0].type == MessageType.message

    def test_receive_consumes_messages(self, team_name):
        mb = _make_mailbox(team_name)
        mb.send(from_agent="alice", to="bob", content="first")

        msgs = mb.receive("bob")
        assert len(msgs) == 1
        # second receive should be empty
        assert mb.receive("bob") == []

    def test_receive_all_messages_present(self, team_name):
        """All sent messages are received. Ordering is by filename (timestamp+uuid)
        which is mostly FIFO, but messages sent within the same ms can swap."""
        mb = _make_mailbox(team_name)
        for i in range(5):
            mb.send(from_agent="alice", to="bob", content=f"msg-{i}")

        msgs = mb.receive("bob", limit=10)
        contents = sorted(m.content for m in msgs)
        assert contents == sorted(f"msg-{i}" for i in range(5))

    def test_receive_limit(self, team_name):
        mb = _make_mailbox(team_name)
        for i in range(5):
            mb.send(from_agent="a", to="b", content=f"{i}")

        msgs = mb.receive("b", limit=3)
        assert len(msgs) == 3
        # remaining 2 should still be there
        rest = mb.receive("b", limit=10)
        assert len(rest) == 2

    def test_send_with_custom_type(self, team_name):
        mb = _make_mailbox(team_name)
        mb.send(
            from_agent="new-guy",
            to="leader",
            msg_type=MessageType.join_request,
            proposed_name="worker-1",
            capabilities="coding",
        )
        msgs = mb.receive("leader")
        assert msgs[0].type == MessageType.join_request
        assert msgs[0].proposed_name == "worker-1"

    def test_send_rejects_path_traversal_recipient(self, team_name):
        mb = _make_mailbox(team_name)
        with pytest.raises(ValueError, match="Invalid recipient name"):
            mb.send(from_agent="alice", to="../bob", content="nope")


class TestPeek:
    def test_peek_does_not_consume(self, team_name):
        mb = _make_mailbox(team_name)
        mb.send(from_agent="a", to="b", content="peeked")

        peeked = mb.peek("b")
        assert len(peeked) == 1
        # still there after peek
        peeked_again = mb.peek("b")
        assert len(peeked_again) == 1

    def test_peek_count(self, team_name):
        mb = _make_mailbox(team_name)
        assert mb.peek_count("bob") == 0
        mb.send(from_agent="a", to="bob", content="1")
        mb.send(from_agent="a", to="bob", content="2")
        assert mb.peek_count("bob") == 2

    def test_peek_skips_corrupt_messages(self, team_name):
        mb = _make_mailbox(team_name)
        mb.send(from_agent="a", to="bob", content="good")

        from clawteam.team.models import get_data_dir

        inbox = get_data_dir() / "teams" / team_name / "inboxes" / "bob"
        (inbox / "msg-corrupt.json").write_text("not valid json", encoding="utf-8")

        peeked = mb.peek("bob")
        assert len(peeked) == 1
        assert peeked[0].content == "good"


class TestBroadcast:
    def test_broadcast_to_all_except_sender(self, team_name):
        mb = _make_mailbox(team_name)
        # set up inboxes so list_recipients finds them
        from clawteam.team.models import get_data_dir

        for name in ["alice", "bob", "carol"]:
            inbox = get_data_dir() / "teams" / team_name / "inboxes" / name
            inbox.mkdir(parents=True, exist_ok=True)

        sent = mb.broadcast(from_agent="alice", content="announcement")
        recipients = {m.to for m in sent}
        assert "alice" not in recipients  # sender excluded
        assert "bob" in recipients
        assert "carol" in recipients

    def test_broadcast_with_exclude(self, team_name):
        mb = _make_mailbox(team_name)
        from clawteam.team.models import get_data_dir

        for name in ["alice", "bob", "carol", "dave"]:
            inbox = get_data_dir() / "teams" / team_name / "inboxes" / name
            inbox.mkdir(parents=True, exist_ok=True)

        sent = mb.broadcast(from_agent="alice", content="hi", exclude=["carol"])
        recipients = {m.to for m in sent}
        assert "alice" not in recipients
        assert "carol" not in recipients
        assert "bob" in recipients
        assert "dave" in recipients

    def test_broadcast_excludes_namespaced_inboxes(self, team_name):
        TeamManager.create_team(
            name=team_name,
            leader_name="lead",
            leader_id="leader001",
            user="alice",
        )
        TeamManager.add_member(team_name, "worker", agent_id="worker001", user="alice")
        TeamManager.add_member(team_name, "reviewer", agent_id="review001", user="alice")

        mb = _make_mailbox(team_name)
        sent = mb.broadcast(from_agent="worker", content="hi", exclude=["reviewer"])

        recipients = {m.to for m in sent}
        assert "alice_worker" not in recipients
        assert "alice_reviewer" not in recipients
        assert "alice_lead" in recipients

    def test_receive_skips_corrupt_messages(self, team_name):
        mb = _make_mailbox(team_name)
        mb.send(from_agent="a", to="bob", content="good")

        from clawteam.team.models import get_data_dir

        inbox = get_data_dir() / "teams" / team_name / "inboxes" / "bob"
        (inbox / "msg-corrupt.json").write_text("not valid json", encoding="utf-8")

        received = mb.receive("bob")
        assert len(received) == 1
        assert received[0].content == "good"

    def test_broadcast_empty_team(self, team_name):
        mb = _make_mailbox(team_name)
        # no inboxes created, nothing to send to
        sent = mb.broadcast(from_agent="lonely", content="anyone?")
        assert sent == []


class TestReceiveQuarantine:
    def test_receive_quarantines_schema_invalid_message_and_returns_valid_message(self, team_name):
        mb = _make_mailbox(team_name)
        inbox = _inbox_path(team_name, "bob")

        mb.send(from_agent="a", to="bob", content="good")
        (inbox / "msg-invalid.json").write_text(
            json.dumps({"type": "message"}), encoding="utf-8"
        )

        received = mb.receive("bob", limit=10)

        assert [msg.content for msg in received] == ["good"]
        assert list(inbox.glob("msg-*.json")) == []

        dead_letters = _dead_letter_root(team_name, "bob")
        assert dead_letters.exists()
        assert len(list(dead_letters.glob("*.json"))) >= 1
        assert len(list(dead_letters.glob("*.meta.json"))) >= 1

    def test_receive_limit_preserves_current_file_budget_with_invalid_first(self, team_name):
        mb = _make_mailbox(team_name)
        inbox = _inbox_path(team_name, "bob")

        (inbox / "msg-0001-invalid.json").write_text(
            json.dumps({"type": "message"}), encoding="utf-8"
        )
        (inbox / "msg-0002-valid.json").write_text(
            json.dumps(
                {
                    "type": "message",
                    "from": "alice",
                    "to": "bob",
                    "content": "later",
                }
            ),
            encoding="utf-8",
        )

        first = mb.receive("bob", limit=1)
        second = mb.receive("bob", limit=1)

        assert first == []
        assert [msg.content for msg in second] == ["later"]
        dead_letters = _dead_letter_root(team_name, "bob")
        assert dead_letters.exists()

    def test_peek_schema_invalid_message_does_not_quarantine_or_consume(self, team_name):
        mb = _make_mailbox(team_name)
        inbox = _inbox_path(team_name, "bob")

        (inbox / "msg-invalid.json").write_text(
            json.dumps({"type": "message"}), encoding="utf-8"
        )

        peeked = mb.peek("bob")

        assert peeked == []
        assert (inbox / "msg-invalid.json").exists()
        assert not _dead_letter_root(team_name, "bob").exists()

    def test_p2p_offline_fallback_receive_matches_file_quarantine_behavior(self, team_name):
        from clawteam.transport.p2p import P2PTransport

        transport = P2PTransport(team_name)
        mb = MailboxManager(team_name, transport=transport)
        inbox = _inbox_path(team_name, "bob")

        mb.send(from_agent="a", to="bob", content="good")
        (inbox / "msg-invalid.json").write_text(
            json.dumps({"type": "message"}), encoding="utf-8"
        )

        received = mb.receive("bob", limit=10)

        assert [msg.content for msg in received] == ["good"]
        assert list(inbox.glob("msg-*.json")) == []
        assert _dead_letter_root(team_name, "bob").exists()
        transport.close()

    def test_receive_recovers_preclaimed_consumed_message(self, team_name):
        mb = _make_mailbox(team_name)
        inbox = _inbox_path(team_name, "bob")

        (inbox / "msg-0001-valid.json").write_text(
            json.dumps(
                {
                    "type": "message",
                    "from": "alice",
                    "to": "bob",
                    "content": "recovered",
                }
            ),
            encoding="utf-8",
        )
        (inbox / "msg-0001-valid.json").rename(inbox / "msg-0001-valid.consumed")

        received = mb.receive("bob", limit=10)

        assert [msg.content for msg in received] == ["recovered"]

    def test_peek_count_includes_preclaimed_consumed_message(self, team_name):
        mb = _make_mailbox(team_name)
        inbox = _inbox_path(team_name, "bob")

        (inbox / "msg-0001-valid.json").write_text(
            json.dumps(
                {
                    "type": "message",
                    "from": "alice",
                    "to": "bob",
                    "content": "recovered",
                }
            ),
            encoding="utf-8",
        )
        (inbox / "msg-0001-valid.json").rename(inbox / "msg-0001-valid.consumed")

        assert mb.peek_count("bob") == 1

    def test_receive_skips_locked_preclaimed_consumed_message(self, team_name):
        mb = _make_mailbox(team_name)
        inbox = _inbox_path(team_name, "bob")
        consumed = inbox / "msg-0001-valid.consumed"

        consumed.write_text(
            json.dumps(
                {
                    "type": "message",
                    "from": "alice",
                    "to": "bob",
                    "content": "locked",
                }
            ),
            encoding="utf-8",
        )

        with consumed.open("rb") as locked_file:
            try_lock(locked_file)
            assert mb.receive("bob", limit=10) == []
            assert consumed.exists()

        received = mb.receive("bob", limit=10)
        assert [msg.content for msg in received] == ["locked"]

    def test_peek_and_count_skip_locked_preclaimed_consumed_message(self, team_name):
        mb = _make_mailbox(team_name)
        inbox = _inbox_path(team_name, "bob")
        consumed = inbox / "msg-0001-valid.consumed"

        consumed.write_text(
            json.dumps(
                {
                    "type": "message",
                    "from": "alice",
                    "to": "bob",
                    "content": "locked",
                }
            ),
            encoding="utf-8",
        )

        with consumed.open("rb") as locked_file:
            try_lock(locked_file)
            assert mb.peek("bob") == []
            assert mb.peek_count("bob") == 0


class TestFileTransport:
    def test_fetch_consume_skips_message_if_claim_fails(self, team_name, monkeypatch):
        transport = FileTransport(team_name)
        transport.deliver("bob", b'{"type":"message","from":"alice","to":"bob","content":"hello"}')

        from clawteam.team.models import get_data_dir

        inbox = get_data_dir() / "teams" / team_name / "inboxes" / "bob"
        message_files = list(inbox.glob("msg-*.json"))
        assert len(message_files) == 1

        original_replace = os.replace

        def fake_replace(src, target):
            if src == str(message_files[0]):
                raise OSError("claimed by another consumer")
            return original_replace(src, target)

        monkeypatch.setattr(os, "replace", fake_replace)

        assert transport.fetch("bob", consume=True) == []
        assert len(list(inbox.glob("msg-*.json"))) == 1

    def test_p2p_fetch_consume_reuses_claim_path(self, team_name, monkeypatch):
        from clawteam.transport.claimed import ClaimedMessage
        from clawteam.transport.p2p import P2PTransport

        transport = P2PTransport(team_name)
        seen = {"calls": 0, "acks": 0}

        def fake_claim(agent_name: str, limit: int = 10):
            assert agent_name == "bob"
            assert limit == 3
            seen["calls"] += 1
            return [
                ClaimedMessage(
                    data=b"raw-message",
                    ack=lambda: seen.__setitem__("acks", seen["acks"] + 1),
                    quarantine=lambda error: None,
                )
            ]

        monkeypatch.setattr(transport, "claim_messages", fake_claim)

        assert transport.fetch("bob", limit=3, consume=True) == [b"raw-message"]
        assert seen == {"calls": 1, "acks": 1}

        transport.close()


class TestP2PLease:
    def test_remote_peer_addr_uses_fresh_lease_instead_of_local_pid(self, team_name):
        from clawteam.transport.p2p import P2PTransport

        transport = P2PTransport(team_name)
        now_ms = int(time.time() * 1000)
        _peer_path(team_name, "bob").write_text(
            json.dumps(
                {
                    "host": "remote-host",
                    "port": 43123,
                    "pid": 999999999,
                    "heartbeatAtMs": now_ms,
                    "leaseExpiresAtMs": now_ms + 5000,
                }
            ),
            encoding="utf-8",
        )

        assert transport._get_peer_addr("bob") == "tcp://remote-host:43123"

        transport.close()

    def test_remote_peer_addr_rejects_stale_lease_even_if_local_pid_is_alive(self, team_name):
        from clawteam.transport.p2p import P2PTransport

        transport = P2PTransport(team_name)
        now_ms = int(time.time() * 1000)
        peer_file = _peer_path(team_name, "bob")
        peer_file.write_text(
            json.dumps(
                {
                    "host": "remote-host",
                    "port": 43123,
                    "pid": os.getpid(),
                    "heartbeatAtMs": now_ms - 6000,
                    "leaseExpiresAtMs": now_ms - 1000,
                }
            ),
            encoding="utf-8",
        )

        assert transport._get_peer_addr("bob") is None
        assert not peer_file.exists()

        transport.close()

    def test_same_host_peer_addr_keeps_live_pid_even_when_lease_is_stale(self, team_name):
        from clawteam.transport.p2p import P2PTransport

        transport = P2PTransport(team_name)
        now_ms = int(time.time() * 1000)
        peer_file = _peer_path(team_name, "bob")
        peer_file.write_text(
            json.dumps(
                {
                    "host": socket.gethostname(),
                    "port": 43123,
                    "pid": os.getpid(),
                    "heartbeatAtMs": now_ms - 6000,
                    "leaseExpiresAtMs": now_ms - 1000,
                }
            ),
            encoding="utf-8",
        )

        assert transport._get_peer_addr("bob") == f"tcp://{socket.gethostname()}:43123"
        assert peer_file.exists()

        transport.close()


class TestEventLog:
    def test_send_logs_event(self, team_name):
        mb = _make_mailbox(team_name)
        mb.send(from_agent="a", to="b", content="logged")

        events = mb.get_event_log()
        assert len(events) == 1
        assert events[0].content == "logged"

    def test_broadcast_logs_per_recipient(self, team_name):
        mb = _make_mailbox(team_name)
        from clawteam.team.models import get_data_dir

        for name in ["x", "y"]:
            inbox = get_data_dir() / "teams" / team_name / "inboxes" / name
            inbox.mkdir(parents=True, exist_ok=True)

        mb.broadcast(from_agent="z", content="bc")
        # z excluded from recipients, so 2 events (x and y)
        events = mb.get_event_log()
        assert len(events) == 2

    def test_event_log_limit(self, team_name):
        mb = _make_mailbox(team_name)
        for i in range(20):
            mb.send(from_agent="a", to="b", content=f"{i}")

        events = mb.get_event_log(limit=5)
        assert len(events) == 5
