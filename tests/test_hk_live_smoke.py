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
from clawteam.templates import load_template


@dataclass(frozen=True)
class HKLiveSmokeScenario:
    template_name: str
    goal: str


ACTIVE_HK_LIVE_SMOKE_MATRIX = (
    HKLiveSmokeScenario("code-review", "Run a live code-review room smoke test"),
    HKLiveSmokeScenario("hedge-fund", "Run a live hedge-fund room smoke test"),
    HKLiveSmokeScenario("research-paper", "Run a live research-paper room smoke test"),
    HKLiveSmokeScenario("software-dev", "Run a live software-dev room smoke test"),
    HKLiveSmokeScenario("strategy-room", "Run a live strategy-room room smoke test"),
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
                "import subprocess",
                "import sys",
                "from pathlib import Path",
                "",
                "def main() -> int:",
                '    trace_dir = Path(os.environ["TRACE_DIR"])',
                "    trace_dir.mkdir(parents=True, exist_ok=True)",
                '    artifact_path = trace_dir / f"{os.environ["CLAWTEAM_AGENT_NAME"]}.json"',
                "    artifact_path.write_text(",
                "        json.dumps(",
                "            {",
                '                "argv": sys.argv[1:],',
                '                "agent": os.environ["CLAWTEAM_AGENT_NAME"],',
                '                "team": os.environ["CLAWTEAM_TEAM_NAME"],',
                "            },",
                "            indent=2,",
                "        ),",
                '        encoding="utf-8",',
                "    )",
                "    subprocess.run(",
                "        [",
                '            os.environ.get("CLAWTEAM_BIN", "clawteam"),',
                '            "--json",',
                '            "inbox",',
                '            "room-update",',
                '            os.environ["CLAWTEAM_TEAM_NAME"],',
                '            "jarvis",',
                '            "--status",',
                '            "ready",',
                '            "--update-kind",',
                '            "execution",',
                '            "--final-delivery",',
                '            "live subprocess smoke finished",',
                '            "--artifact-file",',
                "            str(artifact_path),",
                '            "--next-action",',
                '            "Collect live smoke evidence",',
                "        ],",
                "        check=True,",
                "        stdout=subprocess.DEVNULL,",
                "        stderr=subprocess.DEVNULL,",
                "    )",
                "    return 0",
                "",
                'if __name__ == "__main__":',
                "    raise SystemExit(main())",
                "",
            ]
        ),
        encoding="utf-8",
    )
    path.chmod(0o755)


@pytest.mark.parametrize(
    "scenario",
    ACTIVE_HK_LIVE_SMOKE_MATRIX,
    ids=[scenario.template_name for scenario in ACTIVE_HK_LIVE_SMOKE_MATRIX],
)
def test_active_hk_templates_live_subprocess_smoke(monkeypatch, tmp_path, scenario: HKLiveSmokeScenario):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path / ".clawteam"))

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_clawteam_wrapper(bin_dir)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")

    trace_dir = tmp_path / "live-smoke-traces"
    monkeypatch.setenv("TRACE_DIR", str(trace_dir))

    agent_script = tmp_path / "fake-agent.py"
    _write_agent_script(agent_script)

    backend = SubprocessBackend()
    monkeypatch.setattr("clawteam.spawn.get_backend", lambda _: backend)

    source_plan = tmp_path / f"{scenario.template_name}-live-plan.md"
    source_plan.write_text(
        f"# Plan\nRun live subprocess smoke for {scenario.template_name}.\n",
        encoding="utf-8",
    )

    team_name = f"{scenario.template_name}-live"
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
    assert all(message.status == "ready" for message in messages)
    assert all(message.update_kind == "execution" for message in messages)
    assert all(message.final_delivery == "live subprocess smoke finished" for message in messages)
    assert all(message.next_action == "Collect live smoke evidence" for message in messages)

    for agent_name in expected_agents:
        artifact_path = trace_dir / f"{agent_name}.json"
        assert artifact_path.is_file()
        payload = json.loads(artifact_path.read_text(encoding="utf-8"))
        assert payload["agent"] == agent_name
        assert payload["team"] == team_name
        argv = payload["argv"]
        assert "-p" in argv
        prompt = argv[argv.index("-p") + 1]
        assert "Project Guard" in prompt
