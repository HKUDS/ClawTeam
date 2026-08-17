from __future__ import annotations

import json

from typer.testing import CliRunner

from clawteam.cli.commands import app
from clawteam.templates import AgentDef, TemplateDef


class _FailingBackend:
    def spawn(self, **_kwargs) -> str:
        return "Error: executable 'codex' not found or not executable"


class _MixedBackend:
    def __init__(self) -> None:
        self._results = iter(["Spawned leader in tmux session", "Error: worker command not found"])

    def spawn(self, **_kwargs) -> str:
        return next(self._results)


def _template() -> TemplateDef:
    return TemplateDef(
        name="codex-demo",
        command=["codex"],
        backend="tmux",
        leader=AgentDef(name="leader", type="leader", task="do {goal}"),
    )


def _two_agent_template() -> TemplateDef:
    return TemplateDef(
        name="codex-demo",
        command=["codex"],
        backend="tmux",
        leader=AgentDef(name="leader", type="leader", task="do {goal}"),
        agents=[AgentDef(name="worker", type="worker", task="help {goal}")],
    )


def _patch_launch_dependencies(monkeypatch) -> None:
    monkeypatch.setattr("clawteam.templates.load_template", lambda _name: _template())
    monkeypatch.setattr("clawteam.spawn.get_backend", lambda _name: _FailingBackend())


def test_launch_json_reports_total_spawn_failure(monkeypatch, tmp_path) -> None:
    _patch_launch_dependencies(monkeypatch)
    result = CliRunner().invoke(
        app,
        ["--json", "launch", "codex-demo", "--team-name", "json-failure"],
        env={"HOME": str(tmp_path), "CLAWTEAM_DATA_DIR": str(tmp_path / ".clawteam")},
    )

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["status"] == "failed"
    assert payload["agents"][0]["success"] is False
    assert "not found" in payload["agents"][0]["result"]


def test_launch_human_output_omits_tmux_attach_when_all_spawns_fail(monkeypatch, tmp_path) -> None:
    _patch_launch_dependencies(monkeypatch)
    result = CliRunner().invoke(
        app,
        ["launch", "codex-demo", "--team-name", "human-failure"],
        env={"HOME": str(tmp_path), "CLAWTEAM_DATA_DIR": str(tmp_path / ".clawteam")},
    )

    assert result.exit_code == 1
    assert "failed to launch" in result.stdout
    assert "not found" in result.stdout
    assert "tmux attach" not in result.stdout


def test_launch_json_reports_partial_spawn_failure(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("clawteam.templates.load_template", lambda _name: _two_agent_template())
    monkeypatch.setattr("clawteam.spawn.get_backend", lambda _name: _MixedBackend())

    result = CliRunner().invoke(
        app,
        ["--json", "launch", "codex-demo", "--team-name", "partial-failure"],
        env={"HOME": str(tmp_path), "CLAWTEAM_DATA_DIR": str(tmp_path / ".clawteam")},
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "partial"
    assert [agent["success"] for agent in payload["agents"]] == [True, False]
