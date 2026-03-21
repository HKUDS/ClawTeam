"""Tests for clawteam.config — load/save/get_effective."""


from clawteam.config import ClawTeamConfig, config_path, get_effective, load_config, save_config


class TestClawTeamConfig:
    def test_defaults(self):
        cfg = ClawTeamConfig()
        assert cfg.data_dir == ""
        assert cfg.user == ""
        assert cfg.default_backend == "tmux"
        assert cfg.skip_permissions is True
        assert cfg.timezone == "UTC"
        assert cfg.workspace == "auto"
        assert cfg.profiles == {}
        assert cfg.presets == {}

    def test_custom_values(self):
        cfg = ClawTeamConfig(user="alice", default_backend="subprocess", workspace="never")
        assert cfg.user == "alice"
        assert cfg.default_backend == "subprocess"
        assert cfg.workspace == "never"


class TestLoadSaveConfig:
    def test_load_returns_defaults_when_no_file(self):
        cfg = load_config()
        assert cfg == ClawTeamConfig()

    def test_save_then_load_roundtrip(self):
        cfg = ClawTeamConfig(user="bob", default_team="my-team", transport="file")
        save_config(cfg)
        loaded = load_config()
        assert loaded.user == "bob"
        assert loaded.default_team == "my-team"
        assert loaded.transport == "file"

    def test_save_creates_parent_dirs(self):
        """config_path() is under HOME which we redirect to tmp_path."""
        save_config(ClawTeamConfig(user="x"))
        assert config_path().exists()

    def test_load_handles_corrupt_json(self, tmp_path):
        p = config_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("not valid json {{{", encoding="utf-8")
        # should fall back to defaults, not crash
        cfg = load_config()
        assert cfg == ClawTeamConfig()


class TestGetEffective:
    def test_env_takes_priority(self, monkeypatch):
        save_config(ClawTeamConfig(user="from-file"))
        monkeypatch.setenv("CLAWTEAM_USER", "from-env")
        val, source = get_effective("user")
        assert val == "from-env"
        assert source == "env"

    def test_file_value_used_when_no_env(self, monkeypatch):
        monkeypatch.delenv("CLAWTEAM_USER", raising=False)
        save_config(ClawTeamConfig(user="file-user"))
        val, source = get_effective("user")
        assert val == "file-user"
        assert source == "file"

    def test_default_fallback(self, monkeypatch):
        monkeypatch.delenv("CLAWTEAM_USER", raising=False)
        # user defaults to "" in ClawTeamConfig, so no file value -> falls through
        val, source = get_effective("user")
        assert val == ""
        assert source == "default"

    def test_default_backend_treated_as_file(self, monkeypatch):
        """default_backend has a non-empty default ('tmux'), so load_config()
        returns the default value with source='default' when no config file
        overrides it."""
        monkeypatch.delenv("CLAWTEAM_DEFAULT_BACKEND", raising=False)
        val, source = get_effective("default_backend")
        assert val == "tmux"
        assert source == "default"

    def test_data_dir_env(self, monkeypatch):
        monkeypatch.setenv("CLAWTEAM_DATA_DIR", "/custom/path")
        val, source = get_effective("data_dir")
        assert val == "/custom/path"
        assert source == "env"

    def test_timezone_env(self, monkeypatch):
        monkeypatch.setenv("CLAWTEAM_TIMEZONE", "Asia/Shanghai")
        val, source = get_effective("timezone")
        assert val == "Asia/Shanghai"
        assert source == "env"

    def test_unknown_key_returns_empty(self):
        val, source = get_effective("nonexistent_key")
        assert val == ""
        assert source == "default"
