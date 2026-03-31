"""Tests for clawteam.team.manager — TeamManager lifecycle operations."""

import pytest

from clawteam.team.manager import TeamManager
from clawteam.team.models import get_data_dir


class TestCreateTeam:
    def test_create_basic(self, team_name):
        cfg = TeamManager.create_team(
            name=team_name,
            leader_name="lead",
            leader_id="abc123",
            description="Test team",
        )
        assert cfg.name == team_name
        assert cfg.lead_agent_id == "abc123"
        assert len(cfg.members) == 1
        assert cfg.members[0].name == "lead"
        assert cfg.members[0].agent_type == "leader"

    def test_create_sets_up_directories(self, team_name):
        TeamManager.create_team(name=team_name, leader_name="l", leader_id="x")
        data = get_data_dir()
        # leader inbox
        assert (data / "teams" / team_name / "inboxes" / "l").is_dir()
        # tasks dir
        assert (data / "tasks" / team_name).is_dir()

    def test_create_with_user_prefix(self, team_name):
        TeamManager.create_team(
            name=team_name, leader_name="lead", leader_id="x", user="bob"
        )
        data = get_data_dir()
        # inbox should be user_name format
        assert (data / "teams" / team_name / "inboxes" / "bob_lead").is_dir()

    def test_create_duplicate_raises(self, team_name):
        TeamManager.create_team(name=team_name, leader_name="a", leader_id="1")
        with pytest.raises(ValueError, match="already exists"):
            TeamManager.create_team(name=team_name, leader_name="b", leader_id="2")

    def test_rejects_path_traversal_team_name(self):
        with pytest.raises(ValueError, match="Invalid team name"):
            TeamManager.create_team(name="../escape", leader_name="lead", leader_id="x")

    def test_rejects_invalid_leader_name(self, team_name):
        with pytest.raises(ValueError, match="Invalid leader name"):
            TeamManager.create_team(name=team_name, leader_name="../lead", leader_id="x")


class TestGetTeam:
    def test_get_existing(self, team_name):
        TeamManager.create_team(name=team_name, leader_name="l", leader_id="x")
        cfg = TeamManager.get_team(team_name)
        assert cfg is not None
        assert cfg.name == team_name

    def test_get_nonexistent(self):
        assert TeamManager.get_team("ghost-team") is None


class TestAddMember:
    def test_add_member(self, team_name):
        TeamManager.create_team(name=team_name, leader_name="lead", leader_id="1")
        member = TeamManager.add_member(team_name, "worker", agent_id="2")
        assert member.name == "worker"
        assert member.agent_type == "general-purpose"

        cfg = TeamManager.get_team(team_name)
        assert len(cfg.members) == 2

    def test_add_member_creates_inbox(self, team_name):
        TeamManager.create_team(name=team_name, leader_name="lead", leader_id="1")
        TeamManager.add_member(team_name, "worker", agent_id="2")
        data = get_data_dir()
        assert (data / "teams" / team_name / "inboxes" / "worker").is_dir()

    def test_add_member_with_user(self, team_name):
        TeamManager.create_team(name=team_name, leader_name="lead", leader_id="1")
        TeamManager.add_member(team_name, "worker", agent_id="2", user="alice")
        data = get_data_dir()
        assert (data / "teams" / team_name / "inboxes" / "alice_worker").is_dir()

    def test_add_duplicate_raises(self, team_name):
        TeamManager.create_team(name=team_name, leader_name="lead", leader_id="1")
        TeamManager.add_member(team_name, "worker", agent_id="2")
        with pytest.raises(ValueError, match="already in team"):
            TeamManager.add_member(team_name, "worker", agent_id="3")

    def test_add_to_nonexistent_team(self):
        with pytest.raises(ValueError, match="not found"):
            TeamManager.add_member("nope", "worker", agent_id="x")

    def test_add_member_rejects_invalid_name(self, team_name):
        TeamManager.create_team(name=team_name, leader_name="lead", leader_id="1")
        with pytest.raises(ValueError, match="Invalid member name"):
            TeamManager.add_member(team_name, "../worker", agent_id="2")


class TestRemoveMember:
    def test_remove_existing(self, team_name):
        TeamManager.create_team(name=team_name, leader_name="lead", leader_id="1")
        TeamManager.add_member(team_name, "worker", agent_id="2")
        assert TeamManager.remove_member(team_name, "worker") is True
        cfg = TeamManager.get_team(team_name)
        assert len(cfg.members) == 1

    def test_remove_nonexistent_member(self, team_name):
        TeamManager.create_team(name=team_name, leader_name="lead", leader_id="1")
        assert TeamManager.remove_member(team_name, "ghost") is False

    def test_remove_from_nonexistent_team(self):
        assert TeamManager.remove_member("nope", "anyone") is False


class TestListMembers:
    def test_list(self, team_name):
        TeamManager.create_team(name=team_name, leader_name="lead", leader_id="1")
        TeamManager.add_member(team_name, "w1", agent_id="2")
        TeamManager.add_member(team_name, "w2", agent_id="3")
        members = TeamManager.list_members(team_name)
        names = {m.name for m in members}
        assert names == {"lead", "w1", "w2"}

    def test_list_nonexistent_team(self):
        assert TeamManager.list_members("nope") == []


class TestDiscoverTeams:
    def test_discover_multiple(self):
        TeamManager.create_team(name="alpha", leader_name="a", leader_id="1")
        TeamManager.create_team(name="beta", leader_name="b", leader_id="2")
        teams = TeamManager.discover_teams()
        names = {t["name"] for t in teams}
        assert "alpha" in names
        assert "beta" in names

    def test_discover_empty(self):
        # no teams created
        teams = TeamManager.discover_teams()
        assert teams == []


class TestGetLeader:
    def test_get_leader_name(self, team_name):
        TeamManager.create_team(name=team_name, leader_name="boss", leader_id="lead-id")
        assert TeamManager.get_leader_name(team_name) == "boss"

    def test_get_leader_inbox(self, team_name):
        TeamManager.create_team(
            name=team_name, leader_name="boss", leader_id="lead-id", user="joe"
        )
        assert TeamManager.get_leader_inbox(team_name) == "joe_boss"

    def test_leader_of_nonexistent_team(self):
        assert TeamManager.get_leader_name("nope") is None
        assert TeamManager.get_leader_inbox("nope") is None


class TestInboxNameFor:
    def test_without_user(self):
        from clawteam.team.models import TeamMember

        m = TeamMember(name="worker", agent_id="x")
        assert TeamManager.inbox_name_for(m) == "worker"

    def test_with_user(self):
        from clawteam.team.models import TeamMember

        m = TeamMember(name="worker", user="alice", agent_id="x")
        assert TeamManager.inbox_name_for(m) == "alice_worker"


class TestCleanup:
    def test_cleanup_removes_dirs(self, team_name):
        TeamManager.create_team(name=team_name, leader_name="l", leader_id="x")
        data = get_data_dir()
        assert (data / "teams" / team_name).is_dir()
        assert (data / "tasks" / team_name).is_dir()

        result = TeamManager.cleanup(team_name)
        assert result is True
        assert not (data / "teams" / team_name).exists()
        assert not (data / "tasks" / team_name).exists()

    def test_cleanup_nonexistent_team(self):
        assert TeamManager.cleanup("never-existed") is False

    def test_cleanup_rejects_path_traversal_team_name(self):
        with pytest.raises(ValueError, match="Invalid team name"):
            TeamManager.cleanup("../escape")
