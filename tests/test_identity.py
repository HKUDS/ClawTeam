"""Tests for clawteam.identity — AgentIdentity from_env / to_env."""

from clawteam.identity import AgentIdentity, _env, _env_bool


class TestEnvHelpers:
    def test_env_reads_oh_first(self, monkeypatch):
        monkeypatch.setenv("CLAWTEAM_AGENT_NAME", "alpha")
        monkeypatch.setenv("CLAUDE_CODE_AGENT_NAME", "beta")
        assert _env("CLAWTEAM_AGENT_NAME", "CLAUDE_CODE_AGENT_NAME") == "alpha"

    def test_env_falls_back_to_claude_code(self, monkeypatch):
        monkeypatch.delenv("CLAWTEAM_AGENT_NAME", raising=False)
        monkeypatch.setenv("CLAUDE_CODE_AGENT_NAME", "beta")
        assert _env("CLAWTEAM_AGENT_NAME", "CLAUDE_CODE_AGENT_NAME") == "beta"

    def test_env_returns_default_when_both_missing(self, monkeypatch):
        monkeypatch.delenv("CLAWTEAM_AGENT_NAME", raising=False)
        monkeypatch.delenv("CLAUDE_CODE_AGENT_NAME", raising=False)
        assert _env("CLAWTEAM_AGENT_NAME", "CLAUDE_CODE_AGENT_NAME", "fallback") == "fallback"

    def test_env_bool_true_values(self, monkeypatch):
        for val in ("1", "true", "yes", "True", "YES"):
            monkeypatch.setenv("CLAWTEAM_AGENT_LEADER", val)
            assert _env_bool("CLAWTEAM_AGENT_LEADER", "CLAUDE_CODE_AGENT_LEADER") is True

    def test_env_bool_false_values(self, monkeypatch):
        for val in ("0", "false", "no", ""):
            monkeypatch.setenv("CLAWTEAM_AGENT_LEADER", val)
            assert _env_bool("CLAWTEAM_AGENT_LEADER", "CLAUDE_CODE_AGENT_LEADER") is False

    def test_env_bool_missing_is_false(self, monkeypatch):
        monkeypatch.delenv("CLAWTEAM_AGENT_LEADER", raising=False)
        monkeypatch.delenv("CLAUDE_CODE_AGENT_LEADER", raising=False)
        assert _env_bool("CLAWTEAM_AGENT_LEADER", "CLAUDE_CODE_AGENT_LEADER") is False

    def test_env_bool_uses_first_present_key(self, monkeypatch):
        monkeypatch.setenv("CLAWTEAM_PLAN_MODE_REQUIRED", "0")
        monkeypatch.setenv("OH_PLAN_MODE_REQUIRED", "1")
        assert _env_bool("CLAWTEAM_PLAN_MODE_REQUIRED", "OH_PLAN_MODE_REQUIRED") is False


class TestFromEnv:
    def test_from_env_with_oh_vars(self, monkeypatch):
        monkeypatch.setenv("CLAWTEAM_AGENT_ID", "id-123")
        monkeypatch.setenv("CLAWTEAM_AGENT_NAME", "worker-1")
        monkeypatch.setenv("CLAWTEAM_AGENT_TYPE", "researcher")
        monkeypatch.setenv("CLAWTEAM_TEAM_NAME", "my-team")
        monkeypatch.setenv("CLAWTEAM_AGENT_LEADER", "1")

        identity = AgentIdentity.from_env()
        assert identity.agent_id == "id-123"
        assert identity.agent_name == "worker-1"
        assert identity.agent_type == "researcher"
        assert identity.team_name == "my-team"
        assert identity.is_leader is True
        assert identity.in_team is True

    def test_from_env_with_claude_code_fallback(self, monkeypatch):
        monkeypatch.delenv("CLAWTEAM_AGENT_NAME", raising=False)
        monkeypatch.setenv("CLAUDE_CODE_AGENT_NAME", "claude-agent")
        identity = AgentIdentity.from_env()
        assert identity.agent_name == "claude-agent"

    def test_from_env_plan_mode_uses_oh_before_claude_code(self, monkeypatch):
        monkeypatch.delenv("CLAWTEAM_PLAN_MODE_REQUIRED", raising=False)
        monkeypatch.setenv("OH_PLAN_MODE_REQUIRED", "1")
        monkeypatch.setenv("CLAUDE_CODE_PLAN_MODE_REQUIRED", "0")

        identity = AgentIdentity.from_env()
        assert identity.plan_mode_required is True

    def test_from_env_plan_mode_falls_back_to_claude_code(self, monkeypatch):
        monkeypatch.delenv("CLAWTEAM_PLAN_MODE_REQUIRED", raising=False)
        monkeypatch.delenv("OH_PLAN_MODE_REQUIRED", raising=False)
        monkeypatch.setenv("CLAUDE_CODE_PLAN_MODE_REQUIRED", "true")

        identity = AgentIdentity.from_env()
        assert identity.plan_mode_required is True

    def test_from_env_plan_mode_clawteam_overrides_oh_and_claude_code_true(self, monkeypatch):
        monkeypatch.setenv("CLAWTEAM_PLAN_MODE_REQUIRED", "1")
        monkeypatch.setenv("OH_PLAN_MODE_REQUIRED", "0")
        monkeypatch.setenv("CLAUDE_CODE_PLAN_MODE_REQUIRED", "0")

        identity = AgentIdentity.from_env()
        assert identity.plan_mode_required is True

    def test_from_env_plan_mode_clawteam_overrides_oh_and_claude_code_false(self, monkeypatch):
        monkeypatch.setenv("CLAWTEAM_PLAN_MODE_REQUIRED", "0")
        monkeypatch.setenv("OH_PLAN_MODE_REQUIRED", "1")
        monkeypatch.setenv("CLAUDE_CODE_PLAN_MODE_REQUIRED", "true")

        identity = AgentIdentity.from_env()
        assert identity.plan_mode_required is False

    def test_from_env_defaults(self, monkeypatch):
        for key in ("CLAWTEAM_AGENT_ID", "CLAWTEAM_AGENT_NAME", "CLAWTEAM_AGENT_TYPE",
                     "CLAWTEAM_TEAM_NAME", "CLAWTEAM_AGENT_LEADER", "CLAWTEAM_USER"):
            monkeypatch.delenv(key, raising=False)
        for key in ("CLAUDE_CODE_AGENT_ID", "CLAUDE_CODE_AGENT_NAME", "CLAUDE_CODE_AGENT_TYPE",
                     "CLAUDE_CODE_TEAM_NAME", "CLAUDE_CODE_AGENT_LEADER"):
            monkeypatch.delenv(key, raising=False)

        identity = AgentIdentity.from_env()
        assert identity.agent_name == "agent"
        assert identity.agent_type == "general-purpose"
        assert identity.team_name is None
        assert identity.is_leader is False
        assert identity.in_team is False

    def test_from_env_user_from_config(self, tmp_path, monkeypatch):
        monkeypatch.delenv("CLAWTEAM_USER", raising=False)
        from clawteam.config import ClawTeamConfig, save_config
        cfg = ClawTeamConfig(user="config-user")
        save_config(cfg)

        identity = AgentIdentity.from_env()
        assert identity.user == "config-user"


class TestToEnv:
    def test_to_env_basic(self):
        identity = AgentIdentity(
            agent_id="abc123",
            agent_name="worker",
            agent_type="coder",
            is_leader=False,
        )
        env = identity.to_env()
        assert env["CLAWTEAM_AGENT_ID"] == "abc123"
        assert env["CLAWTEAM_AGENT_NAME"] == "worker"
        assert env["CLAWTEAM_AGENT_TYPE"] == "coder"
        assert env["CLAWTEAM_AGENT_LEADER"] == "0"
        assert "CLAWTEAM_USER" not in env
        assert "CLAWTEAM_TEAM_NAME" not in env

    def test_to_env_with_team_and_user(self):
        identity = AgentIdentity(
            agent_id="x",
            agent_name="lead",
            user="alice",
            team_name="alpha",
            is_leader=True,
        )
        env = identity.to_env()
        assert env["CLAWTEAM_USER"] == "alice"
        assert env["CLAWTEAM_TEAM_NAME"] == "alpha"
        assert env["CLAWTEAM_AGENT_LEADER"] == "1"

    def test_roundtrip_from_to_env(self, monkeypatch):
        original = AgentIdentity(
            agent_id="rt-id",
            agent_name="rt-agent",
            user="bob",
            agent_type="analyst",
            team_name="team-rt",
            is_leader=True,
            plan_mode_required=True,
        )
        for k, v in original.to_env().items():
            monkeypatch.setenv(k, v)
        restored = AgentIdentity.from_env()
        assert restored.agent_id == original.agent_id
        assert restored.agent_name == original.agent_name
        assert restored.agent_type == original.agent_type
        assert restored.team_name == original.team_name
        assert restored.is_leader == original.is_leader
        assert restored.plan_mode_required == original.plan_mode_required


class TestInTeam:
    def test_in_team_true(self):
        assert AgentIdentity(team_name="t").in_team is True

    def test_in_team_false(self):
        assert AgentIdentity(team_name=None).in_team is False
