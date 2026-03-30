from __future__ import annotations

from unittest.mock import patch

import pytest

from clawteam.mcp.helpers import to_payload
from clawteam.mcp.tools.board import board_overview, board_team
from clawteam.mcp.tools.cost import cost_summary
from clawteam.mcp.tools.launch import team_launch
from clawteam.mcp.tools.mailbox import (
    mailbox_peek,
    mailbox_peek_count,
    mailbox_receive,
    mailbox_room_update,
    mailbox_send,
    mailbox_validation_result,
)
from clawteam.mcp.tools.plan import plan_approve, plan_get, plan_reject, plan_submit
from clawteam.mcp.tools.task import task_create, task_get, task_list, task_stats, task_update
from clawteam.mcp.tools.team import (
    team_cleanup,
    team_create,
    team_get,
    team_list,
    team_member_add,
    team_members_list,
)
from clawteam.mcp.tools.workspace import workspace_cross_branch_log
from clawteam.team.manager import TeamManager
from tests.test_spawn_cli import RecordingBackend


def test_to_payload_serializes_pydantic_aliases():
    team = TeamManager.create_team("demo", "leader", "leader001")
    payload = to_payload(team)
    assert payload["leadAgentId"] == "leader001"
    assert "createdAt" in payload


def test_team_tools_round_trip():
    created = team_create("demo", "leader", "leader001", description="demo")
    assert created["name"] == "demo"
    assert team_get("demo")["leadAgentId"] == "leader001"

    member = team_member_add("demo", "worker", "worker001", user="alice")
    assert member["agentId"] == "worker001"

    members = team_members_list("demo")
    assert [item["name"] for item in members] == ["leader", "worker"]

    teams = team_list()
    assert teams == [
        {
            "name": "demo",
            "description": "demo",
            "leadAgentId": "leader001",
            "memberCount": 2,
        }
    ]


def test_team_cleanup_removes_existing_team():
    team_create("demo", "leader", "leader001")

    assert team_cleanup("demo") == {"status": "cleaned", "team": "demo"}
    assert team_list() == []


def test_team_launch_matches_cli_launch_flow(monkeypatch, tmp_path):
    backend = RecordingBackend()
    monkeypatch.setattr("clawteam.spawn.get_backend", lambda _: backend)
    source_plan = tmp_path / "workspace-plan.md"
    source_plan.write_text("# Plan\nLaunch through MCP.\n", encoding="utf-8")

    launched = team_launch(
        "hedge-fund",
        goal="Analyze AAPL",
        team_name="fund1",
        plan_file=str(source_plan),
    )

    staged_path = tmp_path / ".clawteam" / "plans" / "fund1" / "launch-plan.md"

    assert launched["status"] == "launched"
    assert launched["team"] == "fund1"
    assert launched["template"] == "hedge-fund"
    assert launched["planFile"] == str(staged_path)
    assert staged_path.read_text(encoding="utf-8") == source_plan.read_text(encoding="utf-8")
    assert backend.calls
    assert all(str(staged_path) in call["prompt"] for call in backend.calls)


def test_team_launch_accepts_skills(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    backend = RecordingBackend()
    monkeypatch.setattr("clawteam.spawn.get_backend", lambda _: backend)

    skills_root = tmp_path / ".claude" / "skills"
    skill_dir = skills_root / "reviewer"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("Always review carefully.", encoding="utf-8")

    launched = team_launch(
        "hedge-fund",
        goal="Analyze AAPL",
        team_name="fund1",
        skill=["reviewer"],
    )

    assert launched["skills"] == ["reviewer"]
    assert backend.calls
    assert all(call["system_prompt"] == "Always review carefully." for call in backend.calls)


def test_task_tools_round_trip(team_name):
    TeamManager.create_team(team_name, "leader", "leader001")

    created = task_create(team_name, "Implement MCP", owner="worker", metadata={"area": "mcp"})
    assert created["subject"] == "Implement MCP"
    assert created["metadata"] == {"area": "mcp"}

    listed = task_list(team_name)
    assert len(listed) == 1
    assert listed[0]["id"] == created["id"]

    fetched = task_get(team_name, created["id"])
    assert fetched["owner"] == "worker"

    updated = task_update(team_name, created["id"], subject="Ship MCP", description="done")
    assert updated["subject"] == "Ship MCP"
    assert updated["description"] == "done"

    stats = task_stats(team_name)
    assert stats["total"] == 1
    assert stats["pending"] == 1


def test_task_update_surfaces_missing_task(team_name):
    TeamManager.create_team(team_name, "leader", "leader001")
    with pytest.raises(ValueError, match="Task 'missing' not found"):
        task_update(team_name, "missing", subject="nope")


def test_task_update_surfaces_lock_conflict(team_name):
    TeamManager.create_team(team_name, "leader", "leader001")
    task = task_create(team_name, "Lock me")

    with patch("clawteam.spawn.registry.is_agent_alive", return_value=True):
        task_update(team_name, task["id"], status="in_progress", caller="agent-a")
        with pytest.raises(ValueError, match="locked by 'agent-a'"):
            task_update(team_name, task["id"], status="in_progress", caller="agent-b")



def test_mailbox_tools_peek_and_receive(team_name):
    TeamManager.create_team(team_name, "leader", "leader001")
    team_member_add(team_name, "worker", "worker001")

    message = mailbox_send(team_name, from_agent="leader", to="worker", content="hello")
    assert message["from"] == "leader"
    assert message["to"] == "worker"

    count = mailbox_peek_count(team_name, "worker")
    assert count == {"agentName": "worker", "count": 1}

    pending = mailbox_peek(team_name, "worker")
    assert len(pending) == 1
    assert pending[0]["content"] == "hello"

    received = mailbox_receive(team_name, "worker")
    assert len(received) == 1
    assert received[0]["content"] == "hello"
    assert mailbox_peek_count(team_name, "worker")["count"] == 0


def test_mailbox_room_update_tool(team_name):
    TeamManager.create_team(team_name, "leader", "leader001")
    team_member_add(team_name, "worker", "worker001")

    message = mailbox_room_update(
        team_name,
        from_agent="worker",
        to="leader",
        status="blocked",
        blocker="Waiting on checker",
        final_delivery="Patch prepared",
        artifact_files=["/tmp/patch.diff"],
        next_action="Assign reviewer",
        update_kind="execution",
    )

    assert message["type"] == "room_update"
    assert message["status"] == "blocked"
    assert message["artifactFiles"] == ["/tmp/patch.diff"]
    assert message["nextAction"] == "Assign reviewer"


def test_mailbox_validation_result_tool(team_name):
    TeamManager.create_team(team_name, "leader", "leader001")
    team_member_add(team_name, "worker", "worker001")
    team_member_add(team_name, "checker", "checker001")

    message = mailbox_validation_result(
        team_name,
        from_agent="checker",
        to="leader",
        maker_agent="worker",
        claim="Patch is ready",
        evidence=["8 tests passed"],
        verdict="pass",
        follow_up="Ship it",
    )

    assert message["type"] == "validation_result"
    assert message["makerAgent"] == "worker"
    assert message["validationClaim"] == "Patch is ready"
    assert message["validationEvidence"] == ["8 tests passed"]
    assert message["validationVerdict"] == "pass"



def test_plan_tools(team_name):
    TeamManager.create_team(team_name, "leader", "leader001")
    plan = plan_submit(team_name, "worker", "leader", "# Plan", summary="summary")
    assert "planId" in plan

    fetched = plan_get(team_name, plan["planId"], "worker")
    assert fetched["content"] == "# Plan"

    assert plan_approve(team_name, "leader", plan["planId"], "worker") == {
        "ok": True,
        "planId": plan["planId"],
    }
    assert plan_reject(team_name, "leader", plan["planId"], "worker", feedback="redo") == {
        "ok": True,
        "planId": plan["planId"],
    }


def test_cost_summary_defaults_to_empty(team_name):
    TeamManager.create_team(team_name, "leader", "leader001")

    summary = cost_summary(team_name)
    assert summary["teamName"] == team_name
    assert summary["eventCount"] == 0
    assert summary["totalCostCents"] == 0


def test_board_tools(team_name):
    TeamManager.create_team(team_name, "leader", "leader001", description="demo")
    overview = board_overview()
    assert overview[0]["name"] == team_name

    team = board_team(team_name)
    assert team["team"]["name"] == team_name
    assert team["team"]["leaderName"] == "leader"


def test_workspace_cross_branch_log_returns_empty_text_payload_without_entries(team_name):
    TeamManager.create_team(team_name, "leader", "leader001")

    result = workspace_cross_branch_log(team_name)

    assert result == "[]"
