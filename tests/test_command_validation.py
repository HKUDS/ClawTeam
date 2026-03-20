"""Tests for clawteam.spawn.command_validation — CLI detection helpers."""

from clawteam.spawn.command_validation import (
    is_claude_command,
    is_codex_command,
    is_gemini_command,
    is_interactive_cli,
    is_kimi_command,
    is_nanobot_command,
    is_opencode_command,
    is_qwen_command,
)


class TestCLIDetection:
    def test_is_kimi_command(self):
        assert is_kimi_command(["kimi"]) is True
        assert is_kimi_command(["/usr/local/bin/kimi"]) is True
        assert is_kimi_command(["kimi", "--yolo"]) is True
        assert is_kimi_command(["claude"]) is False
        assert is_kimi_command([]) is False

    def test_is_qwen_command(self):
        assert is_qwen_command(["qwen"]) is True
        assert is_qwen_command(["qwen-code"]) is True
        assert is_qwen_command(["/opt/bin/qwen"]) is True
        assert is_qwen_command(["qwen-other"]) is False
        assert is_qwen_command([]) is False

    def test_is_opencode_command(self):
        assert is_opencode_command(["opencode"]) is True
        assert is_opencode_command(["/usr/bin/opencode"]) is True
        assert is_opencode_command(["opencode", "run"]) is True
        assert is_opencode_command(["openclaw"]) is False
        assert is_opencode_command([]) is False

    def test_existing_detectors_unchanged(self):
        assert is_claude_command(["claude"]) is True
        assert is_claude_command(["claude-code"]) is True
        assert is_codex_command(["codex"]) is True
        assert is_codex_command(["codex-cli"]) is True
        assert is_nanobot_command(["nanobot"]) is True
        assert is_gemini_command(["gemini"]) is True

    def test_is_interactive_cli_includes_new_clis(self):
        assert is_interactive_cli(["kimi"]) is True
        assert is_interactive_cli(["qwen"]) is True
        assert is_interactive_cli(["opencode"]) is True
        # Existing ones still included
        assert is_interactive_cli(["claude"]) is True
        assert is_interactive_cli(["codex"]) is True
        assert is_interactive_cli(["nanobot"]) is True
        assert is_interactive_cli(["gemini"]) is True
        # Unknown CLI
        assert is_interactive_cli(["my-custom-agent"]) is False
        assert is_interactive_cli([]) is False
