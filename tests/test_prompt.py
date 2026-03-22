"""Tests for clawteam.spawn.prompt — build_agent_prompt."""

import os

from clawteam.spawn.prompt import (
    _check_path_references,
    _extract_path_references,
    build_agent_prompt,
)


class TestBuildAgentPrompt:
    def test_basic_prompt_contains_identity(self):
        prompt = build_agent_prompt(
            agent_name="worker-1",
            agent_id="abc123",
            agent_type="coder",
            team_name="alpha",
            leader_name="leader",
            task="Implement feature X",
        )
        assert "worker-1" in prompt
        assert "abc123" in prompt
        assert "coder" in prompt
        assert "alpha" in prompt
        assert "leader" in prompt
        assert "Implement feature X" in prompt

    def test_prompt_contains_coordination_protocol(self):
        prompt = build_agent_prompt(
            agent_name="w", agent_id="id", agent_type="t",
            team_name="team", leader_name="lead", task="do stuff",
        )
        assert "clawteam task list" in prompt
        assert "clawteam task update" in prompt
        assert "commit your changes" in prompt
        assert "git add -A && git commit" in prompt
        assert "clawteam inbox send" in prompt
        assert "clawteam cost report" in prompt
        assert "clawteam session save" in prompt

    def test_prompt_includes_user_when_provided(self):
        prompt = build_agent_prompt(
            agent_name="w", agent_id="id", agent_type="t",
            team_name="team", leader_name="lead", task="task",
            user="alice",
        )
        assert "alice" in prompt

    def test_prompt_excludes_user_when_empty(self):
        prompt = build_agent_prompt(
            agent_name="w", agent_id="id", agent_type="t",
            team_name="team", leader_name="lead", task="task",
            user="",
        )
        assert "User:" not in prompt

    def test_prompt_includes_workspace_when_provided(self):
        prompt = build_agent_prompt(
            agent_name="w", agent_id="id", agent_type="t",
            team_name="team", leader_name="lead", task="task",
            workspace_dir="/tmp/ws", workspace_branch="feature-x",
            isolated_workspace=True,
        )
        assert "/tmp/ws" in prompt
        assert "feature-x" in prompt
        assert "Workspace" in prompt
        assert "isolated git worktree" in prompt

    def test_prompt_for_plain_repo_path_is_not_described_as_worktree(self):
        prompt = build_agent_prompt(
            agent_name="w", agent_id="id", agent_type="t",
            team_name="team", leader_name="lead", task="task",
            workspace_dir="/tmp/repo",
            isolated_workspace=False,
        )
        assert "/tmp/repo" in prompt
        assert "Work directly in this repository path" in prompt
        assert "isolated git worktree" not in prompt
        assert "Branch:" not in prompt

    def test_prompt_excludes_workspace_when_empty(self):
        prompt = build_agent_prompt(
            agent_name="w", agent_id="id", agent_type="t",
            team_name="team", leader_name="lead", task="task",
            workspace_dir="",
        )
        assert "Workspace" not in prompt

    def test_prompt_uses_team_and_leader_in_commands(self):
        prompt = build_agent_prompt(
            agent_name="dev", agent_id="id", agent_type="t",
            team_name="my-team", leader_name="boss", task="task",
        )
        assert "clawteam task list my-team --owner dev" in prompt
        assert "clawteam inbox send my-team boss" in prompt
        assert "clawteam cost report my-team" in prompt
        assert "commit your changes in this repository with git" in prompt


class TestExtractPathReferences:
    def test_extracts_absolute_paths(self):
        refs = _extract_path_references("Fix the bug in /src/main.py and /lib/utils.js")
        assert "/src/main.py" in refs
        assert "/lib/utils.js" in refs

    def test_extracts_relative_paths_with_extension(self):
        refs = _extract_path_references("Look at src/config.json for settings")
        assert "src/config.json" in refs

    def test_ignores_urls(self):
        refs = _extract_path_references("See https://example.com/path.html")
        assert not any("example.com" in r for r in refs)

    def test_extracts_dotslash_paths(self):
        refs = _extract_path_references("Run ./scripts/build.sh")
        assert "./scripts/build.sh" in refs

    def test_empty_string(self):
        assert _extract_path_references("") == []

    def test_no_paths(self):
        assert _extract_path_references("Just do the thing") == []


class TestCheckPathReferences:
    def test_returns_empty_without_workspace(self):
        assert _check_path_references("Fix /nonexistent/file.py", "") == []

    def test_warns_on_missing_absolute_path(self, tmp_path):
        warnings = _check_path_references(
            "Fix /definitely/nonexistent/file.py", str(tmp_path)
        )
        assert len(warnings) == 1
        assert "/definitely/nonexistent/file.py" in warnings[0]

    def test_no_warning_for_existing_relative_path(self, tmp_path):
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").write_text("print('hi')")
        warnings = _check_path_references("Fix src/main.py", str(tmp_path))
        assert len(warnings) == 0

    def test_warns_on_missing_relative_path(self, tmp_path):
        warnings = _check_path_references("Fix src/missing.py", str(tmp_path))
        assert len(warnings) == 1
        assert "src/missing.py" in warnings[0]


class TestPromptPathWarnings:
    def test_prompt_includes_path_warnings_for_missing_files(self, tmp_path):
        prompt = build_agent_prompt(
            agent_name="w", agent_id="id", agent_type="t",
            team_name="team", leader_name="lead",
            task="Fix the bug in src/nonexistent.py",
            workspace_dir=str(tmp_path),
        )
        assert "Path Warnings" in prompt
        assert "src/nonexistent.py" in prompt

    def test_prompt_no_warnings_when_paths_exist(self, tmp_path):
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").write_text("x = 1")
        prompt = build_agent_prompt(
            agent_name="w", agent_id="id", agent_type="t",
            team_name="team", leader_name="lead",
            task="Fix the bug in src/main.py",
            workspace_dir=str(tmp_path),
        )
        assert "Path Warnings" not in prompt

    def test_prompt_no_warnings_without_workspace(self):
        prompt = build_agent_prompt(
            agent_name="w", agent_id="id", agent_type="t",
            team_name="team", leader_name="lead",
            task="Fix the bug in /nonexistent/file.py",
        )
        assert "Path Warnings" not in prompt

