from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from clawteam.spawn.subprocess_backend import SubprocessBackend
from clawteam.team.launch import launch_team_from_template
from clawteam.team.mailbox import MailboxManager
from clawteam.team.models import MessageType, TaskStatus
from clawteam.team.tasks import TaskStore
from clawteam.templates import load_template


@dataclass(frozen=True)
class HKLiveFlowScenario:
    template_name: str
    goal: str
    maker_agent: str
    validator_agent: str


ACTIVE_HK_LIVE_FLOW_MATRIX = (
    HKLiveFlowScenario("code-review", "Run a live code-review validation flow", "lead-reviewer", "arch-reviewer"),
    HKLiveFlowScenario("hedge-fund", "Run a live hedge-fund validation flow", "portfolio-manager", "risk-manager"),
    HKLiveFlowScenario(
        "research-paper",
        "Run a live research-paper validation flow",
        "principal-investigator",
        "methodology-designer",
    ),
    HKLiveFlowScenario("software-dev", "Run a live software-dev validation flow", "tech-lead", "qa-engineer"),
    HKLiveFlowScenario("strategy-room", "Run a live strategy-room validation flow", "strategy-lead", "risk-mapper"),
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
                "def _extract_maker_agent(prompt):",
                r"    match = re.search(r'--maker-agent\s+([A-Za-z0-9_-]+)', prompt)",
                "    return match.group(1) if match else None",
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
                "def main():",
                "    argv = sys.argv[1:]",
                "    prompt = _extract_prompt(argv)",
                "    maker_agent = _extract_maker_agent(prompt)",
                "    agent_name = os.environ['CLAWTEAM_AGENT_NAME']",
                "    team_name = os.environ['CLAWTEAM_TEAM_NAME']",
                "    clawteam_bin = os.environ.get('CLAWTEAM_BIN', 'clawteam')",
                "    trace_dir = Path(os.environ['TRACE_DIR'])",
                "    trace_dir.mkdir(parents=True, exist_ok=True)",
                "    completed_task_ids = _complete_owned_tasks(clawteam_bin, team_name, agent_name)",
                "    artifact_path = trace_dir / f'{agent_name}.json'",
                "    artifact_path.write_text(",
                "        json.dumps(",
                "            {",
                "                'agent': agent_name,",
                "                'team': team_name,",
                "                'prompt': prompt,",
                "                'makerAgent': maker_agent,",
                "                'completedTaskIds': completed_task_ids,",
                "                'kind': 'validation_result' if maker_agent else 'room_update',",
                "            },",
                "            indent=2,",
                "        ),",
                "        encoding='utf-8',",
                "    )",
                "    if maker_agent:",
                "        subprocess.run(",
                "            [",
                "                clawteam_bin,",
                "                '--json',",
                "                'inbox',",
                "                'validate',",
                "                team_name,",
                "                'jarvis',",
                "                '--maker-agent',",
                "                maker_agent,",
                "                '--claim',",
                "                f'{agent_name} validated {maker_agent} output',",
                "                '--evidence',",
                "                f'completed_tasks={len(completed_task_ids)}',",
                "                '--evidence',",
                "                f'artifact={artifact_path}',",
                "                '--verdict',",
                "                'pass',",
                "                '--follow-up',",
                "                'Collect validated completion evidence',",
                "                '--artifact-file',",
                "                str(artifact_path),",
                "            ],",
                "            check=True,",
                "            stdout=subprocess.DEVNULL,",
                "            stderr=subprocess.DEVNULL,",
                "        )",
                "    else:",
                "        subprocess.run(",
                "            [",
                "                clawteam_bin,",
                "                '--json',",
                "                'inbox',",
                "                'room-update',",
                "                team_name,",
                "                'jarvis',",
                "                '--status',",
                "                'ready',",
                "                '--update-kind',",
                "                'execution',",
                "                '--final-delivery',",
                "                'live subprocess flow finished',",
                "                '--artifact-file',",
                "                str(artifact_path),",
                "                '--next-action',",
                "                'Collect validated completion evidence',",
                "            ],",
                "            check=True,",
                "            stdout=subprocess.DEVNULL,",
                "            stderr=subprocess.DEVNULL,",
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
    ACTIVE_HK_LIVE_FLOW_MATRIX,
    ids=[scenario.template_name for scenario in ACTIVE_HK_LIVE_FLOW_MATRIX],
)
def test_active_hk_templates_live_subprocess_flow(monkeypatch, tmp_path, scenario: HKLiveFlowScenario):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path / ".clawteam"))

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_clawteam_wrapper(bin_dir)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")

    trace_dir = tmp_path / "live-flow-traces"
    monkeypatch.setenv("TRACE_DIR", str(trace_dir))

    agent_script = tmp_path / "fake-agent-flow.py"
    _write_agent_script(agent_script)

    backend = SubprocessBackend()
    monkeypatch.setattr("clawteam.spawn.get_backend", lambda _: backend)

    source_plan = tmp_path / f"{scenario.template_name}-live-flow-plan.md"
    source_plan.write_text(
        f"# Plan\nRun live flow smoke for {scenario.template_name}.\n",
        encoding="utf-8",
    )

    team_name = f"{scenario.template_name}-live-flow"
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

    mailbox = MailboxManager(team_name)
    messages = mailbox.receive("jarvis", limit=len(expected_agents))

    assert len(messages) == len(expected_agents)
    assert {message.from_agent for message in messages} == set(expected_agents)

    validation_messages = [message for message in messages if message.type == MessageType.validation_result]
    room_update_messages = [message for message in messages if message.type == MessageType.room_update]

    assert len(validation_messages) == 1
    assert len(room_update_messages) == len(expected_agents) - 1

    validation = validation_messages[0]
    assert validation.from_agent == scenario.validator_agent
    assert validation.maker_agent == scenario.maker_agent
    assert validation.validation_verdict == "pass"
    assert validation.validation_follow_up == "Collect validated completion evidence"
    assert validation.artifact_files
    assert any(item.startswith("artifact=") for item in validation.validation_evidence or [])

    assert all(message.status == "ready" for message in room_update_messages)
    assert all(message.update_kind == "execution" for message in room_update_messages)
    assert all(message.final_delivery == "live subprocess flow finished" for message in room_update_messages)
    assert all(message.next_action == "Collect validated completion evidence" for message in room_update_messages)

    tasks = TaskStore(team_name).list_tasks()
    assert tasks
    assert all(task.status == TaskStatus.completed for task in tasks)

    for agent_name in expected_agents:
        artifact_path = trace_dir / f"{agent_name}.json"
        assert artifact_path.is_file()
        payload = json.loads(artifact_path.read_text(encoding="utf-8"))
        assert payload["agent"] == agent_name
        assert payload["team"] == team_name
        assert "Project Guard" in payload["prompt"]
        if agent_name == scenario.validator_agent:
            assert payload["kind"] == "validation_result"
            assert payload["makerAgent"] == scenario.maker_agent
        else:
            assert payload["kind"] == "room_update"
