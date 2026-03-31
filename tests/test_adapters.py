"""Tests for clawteam.spawn.adapters — CLI detection and command preparation."""

from __future__ import annotations

from clawteam.spawn.adapters import (
    NativeCliAdapter,
    command_basename,
    is_interactive_cli,
    is_opencode_command,
    is_pi_command,
    is_qwen_command,
)


class TestCLIDetection:
    """Each detector must accept full paths, bare names, and reject others."""

    def test_is_qwen_command(self):
        assert is_qwen_command(["qwen"])
        assert is_qwen_command(["qwen-code"])
        assert is_qwen_command(["/usr/local/bin/qwen"])
        assert not is_qwen_command(["claude"])
        assert not is_qwen_command([])

    def test_is_opencode_command(self):
        assert is_opencode_command(["opencode"])
        assert is_opencode_command(["/opt/bin/opencode"])
        assert not is_opencode_command(["openai"])
        assert not is_opencode_command([])

    def test_is_pi_command(self):
        assert is_pi_command(["pi"])
        assert is_pi_command(["/usr/local/bin/pi"])
        assert not is_pi_command(["python"])
        assert not is_pi_command([])

    def test_is_interactive_cli_covers_all_known(self):
        for cmd in ["claude", "codex", "nanobot", "gemini", "kimi", "qwen", "opencode", "pi"]:
            assert is_interactive_cli([cmd]), f"{cmd} should be interactive"

    def test_is_interactive_cli_rejects_unknown(self):
        assert not is_interactive_cli(["my-custom-agent"])
        assert not is_interactive_cli([])

    def test_command_basename_normalisation(self):
        assert command_basename(["/usr/local/bin/Claude"]) == "claude"
        assert command_basename([]) == ""


class TestPrepareCommandSkipPermissions:
    """Verify the skip_permissions flag maps to the correct CLI flag."""

    adapter = NativeCliAdapter()

    def test_qwen_gets_yolo(self):
        result = self.adapter.prepare_command(
            ["qwen"], skip_permissions=True,
        )
        assert "--yolo" in result.final_command

    def test_opencode_gets_yolo(self):
        result = self.adapter.prepare_command(
            ["opencode"], skip_permissions=True,
        )
        assert "--yolo" in result.final_command

    def test_claude_unchanged(self):
        result = self.adapter.prepare_command(
            ["claude"], skip_permissions=True,
        )
        assert "--dangerously-skip-permissions" in result.final_command


class TestPrepareCommandPrompt:
    """Prompt delivery: via command args or post_launch_prompt."""

    adapter = NativeCliAdapter()

    def test_qwen_prompt_via_flag(self):
        result = self.adapter.prepare_command(
            ["qwen"], prompt="do work",
        )
        assert "-p" in result.final_command
        assert "do work" in result.final_command
        assert result.post_launch_prompt is None

    def test_opencode_prompt_via_flag(self):
        result = self.adapter.prepare_command(
            ["opencode"], prompt="analyse this",
        )
        assert "-p" in result.final_command
        assert "analyse this" in result.final_command
        assert result.post_launch_prompt is None

    def test_claude_interactive_gets_post_launch_prompt(self):
        result = self.adapter.prepare_command(
            ["claude"], prompt="hello", interactive=True,
        )
        assert result.post_launch_prompt == "hello"
        assert "-p" not in result.final_command

    def test_claude_noninteractive_gets_flag(self):
        result = self.adapter.prepare_command(
            ["claude"], prompt="hello", interactive=False,
        )
        assert result.post_launch_prompt is None
        assert "-p" in result.final_command

    def test_codex_interactive_gets_post_launch_prompt(self):
        result = self.adapter.prepare_command(
            ["codex"], prompt="hello", interactive=True,
        )
        assert result.post_launch_prompt == "hello"
        assert "hello" not in result.final_command

    def test_codex_exec_remains_noninteractive(self):
        result = self.adapter.prepare_command(
            ["codex", "exec"], prompt="hello", interactive=True,
        )
        assert result.post_launch_prompt is None
        assert "hello" in result.final_command


class TestPiCommand:
    """pi-coding-agent specific command preparation."""

    adapter = NativeCliAdapter()

    def test_pi_interactive_gets_positional_prompt(self):
        result = self.adapter.prepare_command(
            ["pi"], prompt="list files", interactive=True,
        )
        # pi takes prompt as positional arg in interactive mode (stays in TUI)
        assert result.final_command == ["pi", "list files"]
        assert result.post_launch_prompt is None

    def test_pi_noninteractive_gets_flag(self):
        result = self.adapter.prepare_command(
            ["pi"], prompt="list files", interactive=False,
        )
        assert result.post_launch_prompt is None
        assert "-p" in result.final_command
        assert "list files" in result.final_command

    def test_pi_skip_permissions_no_special_flag(self):
        result = self.adapter.prepare_command(
            ["pi"], skip_permissions=True,
        )
        # pi is minimal by design, no skip_permissions flag needed
        assert result.final_command == ["pi"]

    def test_pi_without_prompt_unchanged(self):
        result = self.adapter.prepare_command(["pi"])
        assert result.final_command == ["pi"]
        assert result.post_launch_prompt is None
