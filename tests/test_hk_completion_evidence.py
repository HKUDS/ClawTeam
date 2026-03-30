from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from clawteam.spawn.subprocess_backend import SubprocessBackend
from clawteam.team.launch import launch_team_from_template
from clawteam.team.mailbox import MailboxManager
from clawteam.team.models import MessageType, TaskStatus
from clawteam.team.router import RuntimeRouter
from clawteam.team.tasks import TaskStore
from clawteam.templates import load_template


@dataclass(frozen=True)
class HKCompletionScenario:
    template_name: str
    goal: str
    maker_agent: str
    validator_agent: str
    final_update_kind: str


ACTIVE_HK_COMPLETION_MATRIX = (
    HKCompletionScenario(
        "code-review",
        "Produce a code-review completion package",
        "lead-reviewer",
        "arch-reviewer",
        "final-review",
    ),
    HKCompletionScenario(
        "hedge-fund",
        "Produce a hedge-fund completion package",
        "portfolio-manager",
        "risk-manager",
        "final-decision",
    ),
    HKCompletionScenario(
        "research-paper",
        "Produce a research-paper completion package",
        "principal-investigator",
        "methodology-designer",
        "final-paper",
    ),
    HKCompletionScenario(
        "software-dev",
        "Produce a software-dev completion package",
        "tech-lead",
        "qa-engineer",
        "integration",
    ),
    HKCompletionScenario(
        "strategy-room",
        "Produce a strategy-room completion package",
        "strategy-lead",
        "risk-mapper",
        "final-strategy",
    ),
)


def _write_clawteam_wrapper(bin_dir: Path) -> Path:
    wrapper = bin_dir / "clawteam"
    wrapper.write_text(
        "\n".join(
            [
                "#!/bin/sh",
                f'exec {sys.executable!s} -m clawteam "$@"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    wrapper.chmod(0o755)
    return wrapper


def _write_agent_script(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "#!/usr/bin/env python3",
                "import json",
                "import os",
                "import re",
                "import subprocess",
                "import sys",
                "from pathlib import Path",
                "",
                "def _extract_prompt(argv):",
                '    if "-p" not in argv:',
                '        return ""',
                '    index = argv.index("-p")',
                "    return argv[index + 1] if index + 1 < len(argv) else ''",
                "",
                "def _load_tasks(stdout):",
                "    payload = json.loads(stdout or '[]')",
                "    if isinstance(payload, list):",
                "        return payload",
                "    if isinstance(payload, dict) and isinstance(payload.get('tasks'), list):",
                "        return payload['tasks']",
                "    return []",
                "",
                "def _complete_owned_tasks(clawteam_bin, team_name, agent_name):",
                "    result = subprocess.run(",
                "        [clawteam_bin, '--json', 'task', 'list', team_name, '--owner', agent_name],",
                "        check=True,",
                "        capture_output=True,",
                "        text=True,",
                "    )",
                "    task_ids = []",
                "    for task in _load_tasks(result.stdout):",
                "        task_id = task.get('id')",
                "        if not task_id:",
                "            continue",
                "        subprocess.run(",
                "            [clawteam_bin, '--json', 'task', 'update', team_name, task_id, '--status', 'completed'],",
                "            check=True,",
                "            stdout=subprocess.DEVNULL,",
                "            stderr=subprocess.DEVNULL,",
                "        )",
                "        task_ids.append(task_id)",
                "    return task_ids",
                "",
                "def _extract_template_name(team_name):",
                "    suffix = '-completion'",
                "    if team_name.endswith(suffix):",
                "        return team_name[:-len(suffix)]",
                "    return team_name",
                "",
                "def _detect_role(prompt, team_name):",
                "    maker_match = re.search(r\"Wait for ([\\w-]+)'s independent validation\", prompt)",
                "    if maker_match:",
                "        return 'maker', {'validator_agent': maker_match.group(1)}",
                "    validate_pattern = rf'clawteam inbox validate {re.escape(team_name)} ([\\w-]+) --maker-agent ([\\w-]+)'",
                "    validate_match = re.search(validate_pattern, prompt)",
                "    if validate_match and validate_match.group(1) == validate_match.group(2):",
                "        return 'validator', {'maker_agent': validate_match.group(1)}",
                "    return 'worker', {}",
                "",
                "def _build_completion_payload(template_name, team_name, task_ids):",
                "    base = {",
                "        'template': template_name,",
                "        'team': team_name,",
                "        'completedTaskIds': task_ids,",
                "    }",
                "    if template_name == 'code-review':",
                "        base.update({",
                "            'findings': [",
                "                {'severity': 'high', 'file': 'src/core.py', 'issue': 'State race on reviewer handoff'},",
                "                {'severity': 'medium', 'file': 'src/router.py', 'issue': 'Missing retry note for failed flush'},",
                "            ],",
                "            'synthesis': 'Prioritize the race fix, then land the routing retry clarification.',",
                "            'validationMode': 'independent architecture review',",
                "        })",
                "    elif template_name == 'hedge-fund':",
                "        base.update({",
                "            'researchInputs': ['10-K digest', 'earnings transcript', 'sector notes'],",
                "            'analysisOutputs': ['valuation sheet', 'position sizing memo'],",
                "            'synthesis': 'Long bias with explicit hedge sizing and earnings-watch posture.',",
                "            'risks': ['Guidance miss', 'multiple compression'],",
                "            'assumptions': ['Gross margin stability', 'no major supply shock'],",
                "        })",
                "    elif template_name == 'research-paper':",
                "        base.update({",
                "            'planArtifactUsed': True,",
                "            'sectionOutputs': ['problem statement', 'methodology', 'results', 'limitations'],",
                "            'finalSynthesis': 'Paper draft is coherent and ready for editorial review.',",
                "            'checkerSeparation': 'methodology-designer validates the principal investigator output',",
                "        })",
                "    elif template_name == 'software-dev':",
                "        base.update({",
                "            'buildArtifacts': ['dist/server.tar.gz', 'reports/junit.xml'],",
                "            'testEvidence': ['12 unit tests passed', '5 integration tests passed'],",
                "            'remainingRisks': ['Need staging canary before production'],",
                "            'completion': 'Patch is ready for a guarded merge.',",
                "        })",
                "    elif template_name == 'strategy-room':",
                "        base.update({",
                "            'supportingArtifacts': ['system-map.md', 'delivery-options.md', 'risk-register.md'],",
                "            'assumptions': ['Current team capacity holds for two sprints'],",
                "            'risks': ['Migration drag', 'cross-team dependency slippage'],",
                "            'recommendedPath': 'Phase the rollout behind explicit guardrails and checkpoints.',",
                "        })",
                "    return base",
                "",
                "def main():",
                "    argv = sys.argv[1:]",
                "    prompt = _extract_prompt(argv)",
                "    agent_name = os.environ['CLAWTEAM_AGENT_NAME']",
                "    team_name = os.environ['CLAWTEAM_TEAM_NAME']",
                "    clawteam_bin = os.environ.get('CLAWTEAM_BIN', 'clawteam')",
                "    template_name = _extract_template_name(team_name)",
                "    artifact_dir = Path(os.environ['HK_EVIDENCE_DIR'])",
                "    artifact_dir.mkdir(parents=True, exist_ok=True)",
                "",
                "    completed_task_ids = _complete_owned_tasks(clawteam_bin, team_name, agent_name)",
                "    role, role_details = _detect_role(prompt, team_name)",
                "    trace_path = artifact_dir / f'{agent_name}-trace.json'",
                "    trace_path.write_text(",
                "        json.dumps(",
                "            {",
                "                'agent': agent_name,",
                "                'team': team_name,",
                "                'template': template_name,",
                "                'role': role,",
                "                'roleDetails': role_details,",
                "                'prompt': prompt,",
                "                'completedTaskIds': completed_task_ids,",
                "            },",
                "            indent=2,",
                "        ),",
                "        encoding='utf-8',",
                "    )",
                "",
                "    if role == 'maker':",
                "        maker_agent = agent_name",
                "        validator_agent = role_details['validator_agent']",
                "        final_artifact = artifact_dir / f'{template_name}-completion.json'",
                "        final_artifact.write_text(",
                "            json.dumps(_build_completion_payload(template_name, team_name, completed_task_ids), indent=2),",
                "            encoding='utf-8',",
                "        )",
                "        subprocess.run(",
                "            [",
                "                clawteam_bin, '--json', 'inbox', 'room-update', team_name, 'jarvis',",
                "                '--summary', f'{template_name} completion package ready for Jarvis',",
                "                '--status', 'ready',",
                "                '--update-kind', 'completion',",
                "                '--final-delivery', 'final synthesis package prepared',",
                "                '--artifact-file', str(final_artifact),",
                "                '--artifact-file', str(trace_path),",
                "                '--next-action', 'Wait for independent validation package',",
                "            ],",
                "            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,",
                "        )",
                "    elif role == 'validator':",
                "        maker_agent = role_details['maker_agent']",
                "        final_artifact = artifact_dir / f'{template_name}-completion.json'",
                "        validation_artifact = artifact_dir / f'{template_name}-validation.json'",
                "        validation_artifact.write_text(",
                "            json.dumps(",
                "                {",
                "                    'validator': agent_name,",
                "                    'maker': maker_agent,",
                "                    'validatedArtifact': str(final_artifact),",
                "                    'verdict': 'pass',",
                "                    'evidence': [",
                "                        'maker artifact present',",
                "                        f'validator trace={trace_path}',",
                "                    ],",
                "                },",
                "                indent=2,",
                "            ),",
                "            encoding='utf-8',",
                "        )",
                "        subprocess.run(",
                "            [",
                "                clawteam_bin, '--json', 'inbox', 'validate', team_name, 'jarvis',",
                "                '--maker-agent', maker_agent,",
                "                '--claim', f'{template_name} completion package is independently validated',",
                "                '--evidence', 'maker artifact present',",
                "                '--evidence', f'validation_artifact={validation_artifact}',",
                "                '--verdict', 'pass',",
                "                '--follow-up', 'Return validated completion package to Jarvis',",
                "                '--artifact-file', str(validation_artifact),",
                "            ],",
                "            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,",
                "        )",
                "    return 0",
                "",
                "if __name__ == '__main__':",
                "    raise SystemExit(main())",
                "",
            ]
        ),
        encoding="utf-8",
    )
    path.chmod(0o755)


@pytest.mark.parametrize(
    "scenario",
    ACTIVE_HK_COMPLETION_MATRIX,
    ids=[scenario.template_name for scenario in ACTIVE_HK_COMPLETION_MATRIX],
)
def test_active_hk_templates_completion_evidence(monkeypatch, tmp_path, scenario: HKCompletionScenario):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path / ".clawteam"))

    evidence_dir = tmp_path / "completion-evidence"
    monkeypatch.setenv("HK_EVIDENCE_DIR", str(evidence_dir))

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_clawteam_wrapper(bin_dir)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")

    agent_script = tmp_path / "completion-agent.py"
    _write_agent_script(agent_script)

    backend = SubprocessBackend()
    monkeypatch.setattr("clawteam.spawn.get_backend", lambda _: backend)

    source_plan = tmp_path / f"{scenario.template_name}-completion-plan.md"
    source_plan.write_text(
        f"# Plan\nProduce completion evidence for {scenario.template_name}.\n",
        encoding="utf-8",
    )

    team_name = f"{scenario.template_name}-completion"
    template = load_template(scenario.template_name)
    expected_agents = [template.leader.name, *(agent.name for agent in template.agents)]

    launched = launch_team_from_template(
        scenario.template_name,
        goal=scenario.goal,
        plan_file=str(source_plan),
        team_name=team_name,
        backend="subprocess",
        command_override=[str(agent_script)],
    )

    assert launched["status"] == "launched"
    assert launched["backend"] == "subprocess"
    assert [agent["name"] for agent in launched["agents"]] == expected_agents

    for process in backend._processes.values():
        process.wait(timeout=10)
        assert process.returncode == 0

    tasks = TaskStore(team_name).list_tasks()
    assert tasks
    assert all(task.status == TaskStatus.completed for task in tasks)

    mailbox = MailboxManager(team_name)
    messages = mailbox.receive("jarvis", limit=10)
    assert len(messages) == 2

    room_update = next(message for message in messages if message.type == MessageType.room_update)
    validation = next(message for message in messages if message.type == MessageType.validation_result)
    router = RuntimeRouter(team_name, "jarvis")
    room_update_envelope = router.normalize_message(room_update)
    validation_envelope = router.normalize_message(validation)

    assert room_update.from_agent == scenario.maker_agent
    assert room_update.summary == f"{scenario.template_name} completion package ready for Jarvis"
    assert room_update.status == "ready"
    assert room_update.update_kind == "completion"
    assert room_update.final_delivery == "final synthesis package prepared"
    assert room_update.next_action == "Wait for independent validation package"
    assert room_update.artifact_files and len(room_update.artifact_files) == 2

    assert validation.from_agent == scenario.validator_agent
    assert validation.maker_agent == scenario.maker_agent
    assert validation.validation_verdict == "pass"
    assert validation.validation_follow_up == "Return validated completion package to Jarvis"
    assert validation.validation_claim == f"{scenario.template_name} completion package is independently validated"
    assert validation.artifact_files and len(validation.artifact_files) == 1
    assert validation.validation_evidence == [
        "maker artifact present",
        f"validation_artifact={evidence_dir / f'{scenario.template_name}-validation.json'}",
    ]

    completion_artifact = evidence_dir / f"{scenario.template_name}-completion.json"
    validation_artifact = evidence_dir / f"{scenario.template_name}-validation.json"
    maker_trace_path = evidence_dir / f"{scenario.maker_agent}-trace.json"
    validator_trace_path = evidence_dir / f"{scenario.validator_agent}-trace.json"
    assert completion_artifact.is_file()
    assert validation_artifact.is_file()
    assert room_update.artifact_files == [str(completion_artifact), str(maker_trace_path)]
    assert str(validation_artifact) in validation.artifact_files

    completion_payload = json.loads(completion_artifact.read_text(encoding="utf-8"))
    validation_payload = json.loads(validation_artifact.read_text(encoding="utf-8"))

    assert completion_payload["template"] == scenario.template_name
    assert completion_payload["team"] == team_name
    assert validation_payload["validator"] == scenario.validator_agent
    assert validation_payload["maker"] == scenario.maker_agent
    assert validation_payload["verdict"] == "pass"
    assert validation_payload["validatedArtifact"] == str(completion_artifact)
    assert set(validation_payload["evidence"]) == {
        "maker artifact present",
        f"validator trace={validator_trace_path}",
    }

    assert room_update_envelope.summary == room_update.summary
    assert room_update_envelope.recommended_next_action == "Wait for independent validation package"
    assert f"artifactFiles: {completion_artifact} | {maker_trace_path}" in room_update_envelope.evidence
    assert f"finalDelivery: {room_update.final_delivery}" in room_update_envelope.evidence

    assert validation_envelope.summary == f"{scenario.validator_agent} validation for {scenario.maker_agent}: pass"
    assert validation_envelope.recommended_next_action == "Return validated completion package to Jarvis"
    assert f"artifactFiles: {validation_artifact}" in validation_envelope.evidence
    assert (
        f"validationClaim: {scenario.template_name} completion package is independently validated"
        in validation_envelope.evidence
    )
    assert (
        f"validationEvidence: maker artifact present | validation_artifact={validation_artifact}"
        in validation_envelope.evidence
    )

    if scenario.template_name == "code-review":
        assert completion_payload["findings"]
        assert completion_payload["synthesis"]
        assert completion_payload["validationMode"] == "independent architecture review"
    elif scenario.template_name == "hedge-fund":
        assert completion_payload["researchInputs"]
        assert completion_payload["analysisOutputs"]
        assert completion_payload["risks"]
        assert completion_payload["assumptions"]
    elif scenario.template_name == "research-paper":
        assert completion_payload["planArtifactUsed"] is True
        assert completion_payload["sectionOutputs"]
        assert completion_payload["finalSynthesis"]
    elif scenario.template_name == "software-dev":
        assert completion_payload["buildArtifacts"]
        assert completion_payload["testEvidence"]
        assert completion_payload["remainingRisks"]
    elif scenario.template_name == "strategy-room":
        assert completion_payload["supportingArtifacts"]
        assert completion_payload["assumptions"]
        assert completion_payload["risks"]
        assert completion_payload["recommendedPath"]

    trace_payloads: dict[str, dict[str, object]] = {}
    for agent_name in expected_agents:
        trace_path = evidence_dir / f"{agent_name}-trace.json"
        assert trace_path.is_file()
        trace_payload = json.loads(trace_path.read_text(encoding="utf-8"))
        trace_payloads[agent_name] = trace_payload
        assert trace_payload["agent"] == agent_name
        assert trace_payload["team"] == team_name
        assert trace_payload["template"] == scenario.template_name
        assert "Project Guard" in trace_payload["prompt"]

    maker_trace = trace_payloads[scenario.maker_agent]
    validator_trace = trace_payloads[scenario.validator_agent]
    assert maker_trace["role"] == "maker"
    assert validator_trace["role"] == "validator"
    assert maker_trace["roleDetails"] == {"validator_agent": scenario.validator_agent}
    assert validator_trace["roleDetails"] == {"maker_agent": scenario.maker_agent}
    assert "Validation is independent." in maker_trace["prompt"]
    assert "Completion requires evidence." in maker_trace["prompt"]
    assert f"Wait for {scenario.validator_agent}'s independent validation" in maker_trace["prompt"]
    assert (
        f"clawteam inbox room-update {team_name} {scenario.validator_agent} --update-kind {scenario.final_update_kind}"
        in maker_trace["prompt"]
    )
    assert "Validation is independent." in validator_trace["prompt"]
    assert "validate it independently" in validator_trace["prompt"]
    assert (
        f"clawteam inbox validate {team_name} {scenario.maker_agent} --maker-agent {scenario.maker_agent}"
        in validator_trace["prompt"]
    )
