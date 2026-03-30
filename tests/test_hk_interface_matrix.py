from __future__ import annotations

from dataclasses import dataclass

import pytest

from clawteam.mcp.tools.launch import team_launch
from clawteam.mcp.tools.team import team_cleanup
from clawteam.team.manager import TeamManager
from clawteam.team.tasks import TaskStore
from clawteam.templates import load_template


@dataclass(frozen=True)
class HKInterfaceScenario:
    template_name: str


ACTIVE_HK_INTERFACE_MATRIX = (
    HKInterfaceScenario("code-review"),
    HKInterfaceScenario("hedge-fund"),
    HKInterfaceScenario("research-paper"),
    HKInterfaceScenario("software-dev"),
    HKInterfaceScenario("strategy-room"),
)


class RecordingBackend:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def spawn(self, **kwargs):
        self.calls.append(kwargs)
        return f"Agent '{kwargs['agent_name']}' spawned"

    def list_running(self):
        return []


@pytest.mark.parametrize(
    "scenario",
    ACTIVE_HK_INTERFACE_MATRIX,
    ids=[scenario.template_name for scenario in ACTIVE_HK_INTERFACE_MATRIX],
)
def test_active_hk_template_interface_matrix(monkeypatch, tmp_path, scenario: HKInterfaceScenario):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path / ".clawteam"))
    monkeypatch.setattr("clawteam.templates._USER_DIR", tmp_path / ".clawteam" / "templates")

    backend = RecordingBackend()
    monkeypatch.setattr("clawteam.spawn.get_backend", lambda _: backend)

    source_plan = tmp_path / f"{scenario.template_name}-launch-plan.md"
    source_plan.write_text(
        f"# Plan\nValidate the {scenario.template_name} launch interface.\n",
        encoding="utf-8",
    )

    team_name = f"{scenario.template_name}-interface"
    template = load_template(scenario.template_name)
    launched = team_launch(
        scenario.template_name,
        goal=f"Validate {scenario.template_name} launch and cleanup interfaces",
        team_name=team_name,
        plan_file=str(source_plan),
    )

    staged_plan_path = tmp_path / ".clawteam" / "plans" / team_name / "launch-plan.md"
    expected_member_names = [template.leader.name, *(agent.name for agent in template.agents)]

    assert launched["status"] == "launched"
    assert launched["team"] == team_name
    assert launched["template"] == scenario.template_name
    assert launched["backend"] == "tmux"
    assert launched["planFile"] == str(staged_plan_path)
    assert [agent["name"] for agent in launched["agents"]] == expected_member_names
    assert len(launched["agents"]) == len(expected_member_names)
    assert staged_plan_path.read_text(encoding="utf-8") == source_plan.read_text(encoding="utf-8")

    config = TeamManager.get_team(team_name)
    assert config is not None
    assert config.name == team_name
    assert config.lead_agent_id == launched["agents"][0]["id"]

    members = TeamManager.list_members(team_name)
    assert [member.name for member in members] == expected_member_names

    tasks = TaskStore(team_name).list_tasks()
    assert len(tasks) == len(template.tasks)
    assert sorted(task.subject for task in tasks) == sorted(task.subject for task in template.tasks)

    assert [call["agent_name"] for call in backend.calls] == expected_member_names
    assert all(call["team_name"] == team_name for call in backend.calls)
    assert all(str(staged_plan_path) in call["prompt"] for call in backend.calls)

    cleanup = team_cleanup(team_name)
    assert cleanup == {"status": "cleaned", "team": team_name}
    assert TeamManager.get_team(team_name) is None
    assert not (tmp_path / ".clawteam" / "teams" / team_name).exists()
    assert not (tmp_path / ".clawteam" / "tasks" / team_name).exists()
    assert not (tmp_path / ".clawteam" / "plans" / team_name).exists()
