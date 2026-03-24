from __future__ import annotations

from typer.testing import CliRunner

from clawteam.cli.commands import app
from clawteam.config import ClawTeamConfig, load_config, save_config
from clawteam.team.manager import TeamManager


def test_config_cli_supports_all_keys_and_bool_values(tmp_path):
    runner = CliRunner()
    env = {
        "HOME": str(tmp_path),
        "CLAWTEAM_DATA_DIR": str(tmp_path / ".clawteam"),
    }

    result = runner.invoke(app, ["config", "set", "skip_permissions", "false"], env=env)
    assert result.exit_code == 0
    assert load_config().skip_permissions is False

    result = runner.invoke(app, ["config", "set", "workspace", "never"], env=env)
    assert result.exit_code == 0
    assert load_config().workspace == "never"

    result = runner.invoke(app, ["config", "get", "workspace"], env=env)
    assert result.exit_code == 0
    assert "workspace = never" in result.output


def test_team_approve_join_errors_when_request_missing(tmp_path):
    runner = CliRunner()
    env = {
        "HOME": str(tmp_path),
        "CLAWTEAM_DATA_DIR": str(tmp_path / ".clawteam"),
        "CLAWTEAM_AGENT_ID": "leader001",
        "CLAWTEAM_AGENT_NAME": "leader",
    }

    TeamManager.create_team(
        name="demo",
        leader_name="leader",
        leader_id="leader001",
    )

    result = runner.invoke(app, ["team", "approve-join", "demo", "missing-req"], env=env)

    assert result.exit_code == 1
    assert "No join request found with id 'missing-req'" in result.output
    assert [member.name for member in TeamManager.list_members("demo")] == ["leader"]


def test_task_cli_supports_priority_create_update_and_list(tmp_path):
    runner = CliRunner()
    env = {
        "HOME": str(tmp_path),
        "CLAWTEAM_DATA_DIR": str(tmp_path / ".clawteam"),
    }

    create_result = runner.invoke(
        app,
        ["task", "create", "demo", "important work", "--priority", "urgent", "--owner", "alice"],
        env=env,
    )
    assert create_result.exit_code == 0
    assert "Priority: urgent" in create_result.output

    list_result = runner.invoke(
        app,
        ["task", "list", "demo", "--priority", "urgent", "--sort-priority"],
        env=env,
    )
    assert list_result.exit_code == 0
    assert "urgent" in list_result.output
    assert "important work" in list_result.output

    task_id = create_result.output.split("Task created: ")[1].splitlines()[0].strip()
    update_result = runner.invoke(
        app,
        ["task", "update", "demo", task_id, "--priority", "low"],
        env=env,
    )
    assert update_result.exit_code == 0

    get_result = runner.invoke(
        app,
        ["task", "get", "demo", task_id],
        env=env,
    )
    assert get_result.exit_code == 0
    assert "Priority: low" in get_result.output


def test_inbox_cli_missing_subcommand_shows_send_hint(tmp_path):
    runner = CliRunner()
    env = {
        "HOME": str(tmp_path),
        "CLAWTEAM_DATA_DIR": str(tmp_path / ".clawteam"),
    }

    result = runner.invoke(app, ["inbox", "demo", "lead", "hello"], env=env)

    assert result.exit_code == 2
    assert "No such command 'demo'" in result.output
    assert "Use `clawteam inbox send <team> <recipient>" in result.output
    assert "<message>`." in result.output



def test_team_status_uses_configured_timezone(tmp_path):
    runner = CliRunner()
    env = {
        "HOME": str(tmp_path),
        "CLAWTEAM_DATA_DIR": str(tmp_path / ".clawteam"),
    }

    save_config(ClawTeamConfig(timezone="Asia/Shanghai"))
    TeamManager.create_team(
        name="demo",
        leader_name="leader",
        leader_id="leader001",
    )

    result = runner.invoke(app, ["team", "status", "demo"], env=env)

    assert result.exit_code == 0
    assert "CST" in result.output


def test_inbox_send_rejects_empty_content(tmp_path):
    runner = CliRunner()
    env = {
        "HOME": str(tmp_path),
        "CLAWTEAM_DATA_DIR": str(tmp_path / ".clawteam"),
        "CLAWTEAM_AGENT_NAME": "sender",
        "CLAWTEAM_AGENT_ID": "s001",
    }
    result = runner.invoke(app, ["inbox", "send", "demo", "bob", ""], env=env)
    assert result.exit_code == 1
    assert "cannot be empty" in result.output


def test_inbox_send_rejects_invalid_message_type(tmp_path):
    runner = CliRunner()
    env = {
        "HOME": str(tmp_path),
        "CLAWTEAM_DATA_DIR": str(tmp_path / ".clawteam"),
        "CLAWTEAM_AGENT_NAME": "sender",
        "CLAWTEAM_AGENT_ID": "s001",
    }
    result = runner.invoke(
        app, ["inbox", "send", "demo", "bob", "hello", "--type", "bogus"], env=env
    )
    assert result.exit_code == 1
    assert "Invalid message type" in result.output
    assert "bogus" in result.output


def test_inbox_broadcast_rejects_empty_content(tmp_path):
    runner = CliRunner()
    env = {
        "HOME": str(tmp_path),
        "CLAWTEAM_DATA_DIR": str(tmp_path / ".clawteam"),
        "CLAWTEAM_AGENT_NAME": "sender",
        "CLAWTEAM_AGENT_ID": "s001",
    }
    result = runner.invoke(app, ["inbox", "broadcast", "demo", "   "], env=env)
    assert result.exit_code == 1
    assert "cannot be empty" in result.output


def test_inbox_broadcast_rejects_invalid_message_type(tmp_path):
    runner = CliRunner()
    env = {
        "HOME": str(tmp_path),
        "CLAWTEAM_DATA_DIR": str(tmp_path / ".clawteam"),
        "CLAWTEAM_AGENT_NAME": "sender",
        "CLAWTEAM_AGENT_ID": "s001",
    }
    result = runner.invoke(
        app, ["inbox", "broadcast", "demo", "hello world", "--type", "nope"], env=env
    )
    assert result.exit_code == 1
    assert "Invalid message type" in result.output
