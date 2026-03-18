"""Tests for clawteam.team.snapshot — team state checkpoint/restore."""

import json

import pytest

from clawteam.team.costs import CostStore
from clawteam.team.manager import TeamManager
from clawteam.team.models import get_data_dir
from clawteam.team.snapshot import SnapshotManager, SnapshotMeta, _snapshots_root
from clawteam.team.tasks import TaskStore


def _setup_team(team_name: str) -> None:
    """Create a team with some state to snapshot."""
    TeamManager.create_team(
        name=team_name,
        leader_name="leader",
        leader_id="lid001",
        description="snapshot test team",
    )


@pytest.fixture
def team_with_data(team_name):
    """A team with tasks, costs, and an event log entry."""
    _setup_team(team_name)

    ts = TaskStore(team_name)
    ts.create("task one", owner="leader")
    ts.create("task two", owner="worker")

    cs = CostStore(team_name)
    cs.report("leader", provider="openai", model="gpt-4", cost_cents=12.5)

    # drop a message into the event log via mailbox
    from clawteam.team.mailbox import MailboxManager
    mb = MailboxManager(team_name)
    mb.send("leader", "leader", content="hello from leader")

    return team_name


class TestSnapshotCreate:
    def test_basic(self, team_with_data):
        mgr = SnapshotManager(team_with_data)
        meta = mgr.create()
        assert isinstance(meta, SnapshotMeta)
        assert meta.team_name == team_with_data
        assert meta.member_count == 1
        assert meta.task_count == 2
        assert meta.cost_event_count == 1
        assert meta.event_count >= 1

    def test_with_tag(self, team_with_data):
        meta = SnapshotManager(team_with_data).create(tag="before-deploy")
        assert meta.tag == "before-deploy"
        assert "before-deploy" in meta.id

    def test_snapshot_file_written(self, team_with_data):
        meta = SnapshotManager(team_with_data).create()
        path = _snapshots_root(team_with_data) / f"snap-{meta.id}.json"
        assert path.exists()
        bundle = json.loads(path.read_text("utf-8"))
        assert "meta" in bundle
        assert "config" in bundle
        assert "tasks" in bundle
        assert len(bundle["tasks"]) == 2

    def test_nonexistent_team(self, team_name):
        with pytest.raises(ValueError, match="not found"):
            SnapshotManager("no-such-team").create()

    def test_captures_inbox_messages(self, team_with_data):
        # send a message that stays in inbox (don't consume it)
        from clawteam.team.mailbox import MailboxManager
        mb = MailboxManager(team_with_data)
        mb.send("leader", "leader", content="pending msg")

        meta = SnapshotManager(team_with_data).create()
        path = _snapshots_root(team_with_data) / f"snap-{meta.id}.json"
        bundle = json.loads(path.read_text("utf-8"))
        # should have captured the inbox messages
        total_inbox = sum(len(v) for v in bundle["inboxes"].values())
        assert total_inbox >= 1


class TestSnapshotList:
    def test_empty(self, team_name):
        _setup_team(team_name)
        assert SnapshotManager(team_name).list_snapshots() == []

    def test_lists_created(self, team_with_data):
        mgr = SnapshotManager(team_with_data)
        mgr.create(tag="first")
        mgr.create(tag="second")
        snaps = mgr.list_snapshots()
        assert len(snaps) == 2
        # newest first
        assert snaps[0].tag == "second"
        assert snaps[1].tag == "first"


class TestSnapshotRestore:
    def test_dry_run(self, team_with_data):
        mgr = SnapshotManager(team_with_data)
        meta = mgr.create()
        summary = mgr.restore(meta.id, dry_run=True)
        assert summary["dry_run"] is True
        assert summary["tasks"] == 2
        assert summary["config"] is True

    def test_restore_tasks(self, team_with_data):
        mgr = SnapshotManager(team_with_data)
        meta = mgr.create(tag="checkpoint")

        # wipe the tasks
        ts = TaskStore(team_with_data)
        data_dir = get_data_dir()
        tasks_dir = data_dir / "tasks" / team_with_data
        for f in tasks_dir.glob("task-*.json"):
            f.unlink()
        assert ts.list_tasks() == []

        # restore
        summary = mgr.restore(meta.id)
        assert summary["dry_run"] is False
        assert summary["tasks"] == 2
        restored = ts.list_tasks()
        assert len(restored) == 2

    def test_restore_config(self, team_with_data):
        mgr = SnapshotManager(team_with_data)
        meta = mgr.create()

        # overwrite the config
        team_dir = get_data_dir() / "teams" / team_with_data
        (team_dir / "config.json").write_text('{"name": "broken"}')

        mgr.restore(meta.id)
        cfg = TeamManager.get_team(team_with_data)
        assert cfg is not None
        assert cfg.description == "snapshot test team"

    def test_restore_events(self, team_with_data):
        mgr = SnapshotManager(team_with_data)
        meta = mgr.create()

        # wipe events
        events_dir = get_data_dir() / "teams" / team_with_data / "events"
        for f in events_dir.glob("evt-*.json"):
            f.unlink()

        summary = mgr.restore(meta.id)
        assert summary["events"] >= 1
        restored_files = list(events_dir.glob("evt-*.json"))
        assert len(restored_files) >= 1

    def test_restore_nonexistent_snapshot(self, team_with_data):
        with pytest.raises(ValueError, match="not found"):
            SnapshotManager(team_with_data).restore("nope")

    def test_restore_costs(self, team_with_data):
        mgr = SnapshotManager(team_with_data)
        meta = mgr.create()

        # wipe costs
        costs_dir = get_data_dir() / "costs" / team_with_data
        for f in costs_dir.glob("cost-*.json"):
            f.unlink()
        assert CostStore(team_with_data).list_events() == []

        mgr.restore(meta.id)
        assert len(CostStore(team_with_data).list_events()) == 1


class TestSnapshotDelete:
    def test_delete_existing(self, team_with_data):
        mgr = SnapshotManager(team_with_data)
        meta = mgr.create()
        assert mgr.delete(meta.id) is True
        assert mgr.list_snapshots() == []

    def test_delete_nonexistent(self, team_with_data):
        assert SnapshotManager(team_with_data).delete("nope") is False


class TestSnapshotRoundTrip:
    """End-to-end: create → snapshot → cleanup → restore → verify."""

    def test_full_cycle(self, team_name):
        _setup_team(team_name)
        ts = TaskStore(team_name)
        ts.create("important task", owner="leader", metadata={"key": "val"})

        mgr = SnapshotManager(team_name)
        meta = mgr.create(tag="full-cycle")

        # nuke everything except the snapshot
        TeamManager.cleanup(team_name)
        assert TeamManager.get_team(team_name) is None

        # restore
        mgr.restore(meta.id)
        cfg = TeamManager.get_team(team_name)
        assert cfg is not None
        assert cfg.name == team_name

        tasks = TaskStore(team_name).list_tasks()
        assert len(tasks) == 1
        assert tasks[0].subject == "important task"
        assert tasks[0].metadata.get("key") == "val"
