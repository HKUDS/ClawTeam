from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from clawteam.cli import commands
from clawteam.cli.commands import app
from clawteam.config import AgentProfile
from clawteam.spawn.profiles import apply_profile


def test_apply_profile_maps_claude_provider_and_model(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_PROXY_TOKEN", "secret-token")
    profile = AgentProfile(
        agent="claude",
        model="opus",
        base_url="https://proxy.example.com",
        api_key_env="ANTHROPIC_PROXY_TOKEN",
        args=["--debug"],
    )

    command, env, agent = apply_profile(profile)

    assert agent == "claude"
    assert command == ["claude", "--model", "opus", "--debug"]
    assert env["ANTHROPIC_BASE_URL"] == "https://proxy.example.com"
    assert env["ANTHROPIC_AUTH_TOKEN"] == "secret-token"


def test_apply_profile_maps_kimi_env_and_command(monkeypatch):
    monkeypatch.setenv("MOONSHOT_API_KEY", "moonshot-token")
    profile = AgentProfile(
        command=["kimi", "--config-file", "~/.kimi/config.toml"],
        model="kimi-k2-thinking-turbo",
        base_url="https://api.moonshot.cn/v1",
        api_key_env="MOONSHOT_API_KEY",
    )

    command, env, agent = apply_profile(profile)

    assert agent == "kimi"
    assert command[:4] == ["kimi", "--config-file", "~/.kimi/config.toml", "--model"]
    assert command[-1] == "kimi-k2-thinking-turbo"
    assert env["KIMI_BASE_URL"] == "https://api.moonshot.cn/v1"
    assert env["KIMI_API_KEY"] == "moonshot-token"


def test_apply_profile_maps_gemini_base_url_and_key(monkeypatch):
    monkeypatch.setenv("GEMINI_PROFILE_KEY", "gemini-secret")
    profile = AgentProfile(
        agent="gemini",
        model="gemini-2.5-pro",
        base_url="https://openrouter.ai/api",
        api_key_env="GEMINI_PROFILE_KEY",
    )

    command, env, agent = apply_profile(profile)

    assert agent == "gemini"
    assert command == ["gemini", "--model", "gemini-2.5-pro"]
    assert env["GOOGLE_GEMINI_BASE_URL"] == "https://openrouter.ai/api"
    assert env["GEMINI_API_KEY"] == "gemini-secret"


def test_apply_profile_respects_explicit_target_env_overrides(monkeypatch):
    monkeypatch.setenv("CUSTOM_PROVIDER_KEY", "provider-secret")
    profile = AgentProfile(
        agent="claude",
        base_url="https://api.example.com/anthropic",
        base_url_env="CUSTOM_BASE_URL",
        api_key_env="CUSTOM_PROVIDER_KEY",
        api_key_target_env="ANTHROPIC_API_KEY",
    )

    _, env, _ = apply_profile(profile)

    assert env["CUSTOM_BASE_URL"] == "https://api.example.com/anthropic"
    assert env["ANTHROPIC_API_KEY"] == "provider-secret"


def test_profile_cli_set_list_show_remove(tmp_path):
    runner = CliRunner()
    env = {
        "HOME": str(tmp_path),
        "CLAWTEAM_DATA_DIR": str(tmp_path / ".clawteam"),
    }

    result = runner.invoke(
        app,
        [
            "profile",
            "set",
            "moonshot-kimi",
            "--command",
            "kimi --config-file ~/.kimi/config.toml",
            "--model",
            "kimi-k2-thinking-turbo",
            "--base-url",
            "https://api.moonshot.cn/v1",
            "--api-key-env",
            "MOONSHOT_API_KEY",
            "--env-map",
            "KIMI_API_KEY=MOONSHOT_API_KEY",
            "--arg",
            "--debug",
        ],
        env=env,
    )
    assert result.exit_code == 0

    result = runner.invoke(app, ["profile", "list"], env=env)
    assert result.exit_code == 0
    assert "moonshot-kimi" in result.output

    result = runner.invoke(app, ["profile", "show", "moonshot-kimi"], env=env)
    assert result.exit_code == 0
    assert "kimi-k2-thinking-turbo" in result.output
    assert "https://api.moonshot.cn/v1" in result.output

    result = runner.invoke(app, ["profile", "remove", "moonshot-kimi"], env=env)
    assert result.exit_code == 0
    assert "Removed profile 'moonshot-kimi'" in result.output


def test_profile_doctor_claude_creates_state_file(tmp_path):
    runner = CliRunner()
    env = {
        "HOME": str(tmp_path),
        "CLAWTEAM_DATA_DIR": str(tmp_path / ".clawteam"),
    }

    result = runner.invoke(app, ["profile", "doctor", "claude"], env=env)

    assert result.exit_code == 0
    state = json.loads((Path(tmp_path) / ".claude.json").read_text(encoding="utf-8"))
    assert state["hasCompletedOnboarding"] is True


def test_profile_doctor_claude_updates_existing_state_file(tmp_path):
    runner = CliRunner()
    env = {
        "HOME": str(tmp_path),
        "CLAWTEAM_DATA_DIR": str(tmp_path / ".clawteam"),
    }
    state_path = Path(tmp_path) / ".claude.json"
    state_path.write_text(
        json.dumps({"theme": "dark", "hasCompletedOnboarding": False}),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["profile", "doctor", "claude"], env=env)

    assert result.exit_code == 0
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["theme"] == "dark"
    assert state["hasCompletedOnboarding"] is True


def test_apply_profile_pi_model_flag_is_injected():
    """Pi profiles should receive --model from profile.model."""
    profile = AgentProfile(
        agent="pi",
        model="anthropic/claude-sonnet-4.6",
    )

    command, env, agent = apply_profile(profile)

    assert agent == "pi"
    assert command == ["pi", "--model", "anthropic/claude-sonnet-4.6"]
    assert env == {}


def test_apply_profile_pi_model_not_duplicated_when_already_present():
    """If --model is already in the command, profile.model should not add another."""
    profile = AgentProfile(
        agent="pi",
        model="anthropic/claude-sonnet-4.6",
        command=["pi", "--model", "google/gemini-2.5-pro"],
    )

    command, env, agent = apply_profile(profile)

    assert agent == "pi"
    assert command == ["pi", "--model", "google/gemini-2.5-pro"]


def test_apply_profile_pi_no_base_url_or_api_key_env_injection(monkeypatch):
    """Pi resolves base URL and API keys from --provider or provider-specific env."""
    monkeypatch.setenv("MY_API_KEY", "test-key")
    profile = AgentProfile(
        agent="pi",
        model="google/gemini-2.5-pro",
        api_key_env="MY_API_KEY",
    )

    command, env, agent = apply_profile(profile)

    assert agent == "pi"
    assert command == ["pi", "--model", "google/gemini-2.5-pro"]
    # Pi has no built-in base_url_env or api_key_target_env mapping,
    # so the profile's api_key_env should NOT produce an automatic injection.
    assert "ANTHROPIC_AUTH_TOKEN" not in env
    assert "OPENAI_API_KEY" not in env


def test_profile_wizard_generates_profile_from_preset(monkeypatch, tmp_path):
    runner = CliRunner()
    env = {
        "HOME": str(tmp_path),
        "CLAWTEAM_DATA_DIR": str(tmp_path / ".clawteam"),
    }

    class _Prompt:
        def __init__(self, value):
            self._value = value

        def ask(self):
            return self._value

    class FakeQuestionary:
        answers = iter(
            [
                "quick",
                "claude",
                "moonshot-cn",
                "claude-moonshot-wizard",
                False,
                False,
                False,
                False,
            ]
        )

        class Choice:
            def __init__(self, title, value):
                self.title = title
                self.value = value

        @classmethod
        def _next(cls):
            return next(cls.answers)

        @classmethod
        def select(cls, *args, **kwargs):
            return _Prompt(cls._next())

        @classmethod
        def text(cls, *args, **kwargs):
            return _Prompt(cls._next())

        @classmethod
        def confirm(cls, *args, **kwargs):
            return _Prompt(cls._next())

    monkeypatch.setattr(commands, "_load_questionary", lambda: FakeQuestionary)
    monkeypatch.setattr(commands, "_profile_wizard_style", lambda _questionary: None)

    result = runner.invoke(app, ["profile", "wizard"], env=env)

    assert result.exit_code == 0
    show = runner.invoke(app, ["profile", "show", "claude-moonshot-wizard"], env=env)
    assert show.exit_code == 0
    assert "Moonshot China endpoints" in show.output
    assert "kimi-k2.5" in show.output
    assert "https://api.moonshot.cn/anthropic" in show.output
