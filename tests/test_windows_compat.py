import os

from typer.testing import CliRunner

from clawteam.cli.commands import app
from clawteam.config import ClawTeamConfig, load_config, save_config
from clawteam.fsutil import replace_file
from clawteam.spawn.registry import is_agent_alive, register_agent
from clawteam.team.manager import TeamManager


def test_windows_default_backend_matches_platform(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAWTEAM_CONFIG_DIR", str(tmp_path))
    cfg = load_config()
    if os.name == "nt":
        assert cfg.default_backend == "subprocess"
    else:
        assert cfg.default_backend == "tmux"


def test_replace_file_overwrites_destination(tmp_path):
    src = tmp_path / "src.txt"
    dst = tmp_path / "dst.txt"
    src.write_text("new", encoding="utf-8")
    dst.write_text("old", encoding="utf-8")
    replace_file(src, dst)
    assert dst.read_text(encoding="utf-8") == "new"
    assert not src.exists()


def test_registry_treats_windows_backend_like_subprocess(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path))
    TeamManager.create_team(name="demo", leader_name="leader", leader_id="lid")
    register_agent("demo", "worker", backend="windows", pid=os.getpid())
    assert is_agent_alive("demo", "worker") is True


def test_board_attach_is_helpful_on_windows(monkeypatch, tmp_path):
    if os.name != "nt":
        return
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path))
    TeamManager.create_team(name="demo", leader_name="leader", leader_id="lid")
    runner = CliRunner()
    result = runner.invoke(app, ["board", "attach", "demo"])
    assert result.exit_code == 1
    assert "not available on Windows" in result.output
    assert "board serve" in result.output


def test_config_persists_windows_backend_value(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAWTEAM_CONFIG_DIR", str(tmp_path))
    save_config(ClawTeamConfig(default_backend="windows"))
    cfg = load_config()
    assert cfg.default_backend == "windows"
