from __future__ import annotations

from unittest.mock import patch

import pytest

from clawteam.mcp.helpers import to_payload
from clawteam.mcp.tools.board import board_overview, board_team
from clawteam.mcp.tools.cost import cost_summary
from clawteam.mcp.tools.mailbox import (
    mailbox_peek,
    mailbox_peek_count,
    mailbox_receive,
    mailbox_send,
)
from clawteam.mcp.tools.plan import plan_approve, plan_get, plan_reject, plan_submit
from clawteam.mcp.tools.task import task_create, task_get, task_list, task_stats, task_update
from clawteam.mcp.tools.team import (
    team_create,
    team_get,
    team_list,
    team_member_add,
    team_members_list,
)
from clawteam.mcp.tools.workspace import workspace_cross_branch_log
from clawteam.team.manager import TeamManager


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
