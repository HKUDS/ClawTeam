from __future__ import annotations

from dataclasses import dataclass

import pytest

from clawteam.team.launch import launch_team_from_template
from clawteam.team.mailbox import MailboxManager
from clawteam.team.manager import TeamManager
from clawteam.team.models import MessageType
from clawteam.team.router import RuntimeRouter
from clawteam.team.tasks import TaskStore
from clawteam.templates import list_templates, load_template


@dataclass(frozen=True)
class ActiveTemplateScenario:
    template_name: str
    goal: str
    leader_name: str
    maker_agent: str
    validator_agent: str
    leader_wait_phrase: str


ACTIVE_HK_TEMPLATE_MATRIX = (
    ActiveTemplateScenario(
        template_name="code-review",
        goal="Review the HK launch diff",
        leader_name="lead-reviewer",
        maker_agent="lead-reviewer",
        validator_agent="arch-reviewer",
        leader_wait_phrase="Wait for arch-reviewer's independent validation",
    ),
    ActiveTemplateScenario(
        template_name="hedge-fund",
        goal="Analyze AAPL for Q2 positioning",
        leader_name="portfolio-manager",
        maker_agent="portfolio-manager",
        validator_agent="risk-manager",
        leader_wait_phrase="Wait for risk-manager's independent validation",
    ),
    ActiveTemplateScenario(
        template_name="research-paper",
        goal="Draft a retrieval evaluation paper",
        leader_name="principal-investigator",
        maker_agent="principal-investigator",
        validator_agent="methodology-designer",
        leader_wait_phrase="Wait for methodology-designer's independent validation",
    ),
    ActiveTemplateScenario(
        template_name="software-dev",
        goal="Ship launch verification tooling",
        leader_name="tech-lead",
        maker_agent="tech-lead",
        validator_agent="qa-engineer",
        leader_wait_phrase="Wait for qa-engineer's independent validation",
    ),
    ActiveTemplateScenario(
        template_name="strategy-room",
        goal="Choose the next rollout path",
        leader_name="strategy-lead",
        maker_agent="strategy-lead",
        validator_agent="risk-mapper",
        leader_wait_phrase="Wait for risk-mapper's independent validation",
    ),
)

ACTIVE_HK_TEMPLATE_NAMES = tuple(sorted(scenario.template_name for scenario in ACTIVE_HK_TEMPLATE_MATRIX))


class RecordingBackend:
    def __init__(self):
        self.calls: list[dict] = []

    def spawn(self, **kwargs):
        self.calls.append(kwargs)
        return f"Agent '{kwargs['agent_name']}' spawned"

    def list_running(self):
        return []


def _install_room_skill(home_dir, name: str, content: str) -> None:
    skill_dir = home_dir / ".claude" / "skills" / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")


def test_active_hk_template_inventory_matches_restored_baseline():
    builtin_names = sorted(template["name"] for template in list_templates() if template["source"] == "builtin")

    assert builtin_names == list(ACTIVE_HK_TEMPLATE_NAMES)


@pytest.mark.parametrize(
    "scenario",
    ACTIVE_HK_TEMPLATE_MATRIX,
    ids=[scenario.template_name for scenario in ACTIVE_HK_TEMPLATE_MATRIX],
)
def test_active_hk_template_rollout_matrix(monkeypatch, tmp_path, scenario: ActiveTemplateScenario):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path / ".clawteam"))

    backend = RecordingBackend()
    monkeypatch.setattr("clawteam.spawn.get_backend", lambda _: backend)

    skill_name = "room-reviewer"
    skill_text = "Always preserve evidence and keep the maker separate from the checker."
    _install_room_skill(tmp_path, skill_name, skill_text)

    source_plan = tmp_path / f"{scenario.template_name}-launch-plan.md"
    source_plan.write_text(
        f"# Plan\nLaunch {scenario.template_name} through the shared HK refinement flow.\n",
        encoding="utf-8",
    )
    artifact_path = tmp_path / f"{scenario.template_name}-artifact.md"
    artifact_path.write_text(
        f"# Artifact\nStructured result for {scenario.template_name}.\n",
        encoding="utf-8",
    )

    team_name = f"{scenario.template_name}-rollout"
    template = load_template(scenario.template_name)
    launched = launch_team_from_template(
        scenario.template_name,
        goal=scenario.goal,
        team_name=team_name,
        plan_file=str(source_plan),
        skill=[skill_name],
    )

    staged_plan_path = tmp_path / ".clawteam" / "plans" / team_name / "launch-plan.md"
    members = TeamManager.list_members(team_name)
    tasks = TaskStore(team_name).list_tasks()

    assert launched["status"] == "launched"
    assert launched["team"] == team_name
    assert launched["planFile"] == str(staged_plan_path)
    assert launched["skills"] == [skill_name]
    assert staged_plan_path.read_text(encoding="utf-8") == source_plan.read_text(encoding="utf-8")
    assert [member.name for member in members] == [template.leader.name, *(agent.name for agent in template.agents)]
    assert len(tasks) == len(template.tasks)

    prompts_by_agent = {call["agent_name"]: call["prompt"] for call in backend.calls}
    assert scenario.leader_wait_phrase in prompts_by_agent[scenario.leader_name]
    assert f"--maker-agent {scenario.maker_agent}" in prompts_by_agent[scenario.validator_agent]
    assert all("## Project Guard" in call["prompt"] for call in backend.calls)
    assert all(str(staged_plan_path) in call["prompt"] for call in backend.calls)
    assert all(call["system_prompt"] == skill_text for call in backend.calls)

    mailbox = MailboxManager(team_name)
    mailbox.send_room_update(
        from_agent=scenario.maker_agent,
        to="jarvis",
        status="ready",
        final_delivery="Room output prepared",
        artifact_files=[str(artifact_path)],
        next_action="Wait for independent validation delivery",
        update_kind="completion",
    )
    mailbox.send_validation_result(
        from_agent=scenario.validator_agent,
        to="jarvis",
        maker_agent=scenario.maker_agent,
        claim=f"{scenario.template_name} output is ready for Jarvis",
        evidence=[
            "launch path verified",
            f"artifact={artifact_path}",
        ],
        verdict="pass",
        follow_up="Return the validated result to Jarvis",
        artifact_files=[str(artifact_path)],
    )

    received = mailbox.receive("jarvis")
    assert {message.type for message in received} == {
        MessageType.room_update,
        MessageType.validation_result,
    }
    received_by_type = {message.type: message for message in received}

    router = RuntimeRouter(team_name=team_name, agent_name="jarvis")
    update_envelope = router.normalize_message(received_by_type[MessageType.room_update])
    validation_envelope = router.normalize_message(received_by_type[MessageType.validation_result])

    assert update_envelope.summary == f"{scenario.maker_agent} room update: completion; status=ready"
    assert f"finalDelivery: Room output prepared" in update_envelope.evidence
    assert f"artifactFiles: {artifact_path}" in update_envelope.evidence
    assert update_envelope.recommended_next_action == "Wait for independent validation delivery"

    assert validation_envelope.summary == f"{scenario.validator_agent} validation for {scenario.maker_agent}: pass"
    assert f"validationClaim: {scenario.template_name} output is ready for Jarvis" in validation_envelope.evidence
    assert f"validationEvidence: launch path verified | artifact={artifact_path}" in validation_envelope.evidence
    assert validation_envelope.recommended_next_action == "Return the validated result to Jarvis"
