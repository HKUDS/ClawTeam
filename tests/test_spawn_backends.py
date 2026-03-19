"""Tests for spawn backend environment propagation."""

from __future__ import annotations

import sys

from clawteam.spawn.cli_env import build_spawn_path, resolve_clawteam_executable
from clawteam.spawn.subprocess_backend import SubprocessBackend
from clawteam.spawn.tmux_backend import TmuxBackend, _confirm_workspace_trust_if_prompted


class DummyProcess:
    def __init__(self, pid: int = 4321):
        self.pid = pid

    def poll(self):
        return None


def test_subprocess_backend_prepends_current_clawteam_bin_to_path(monkeypatch, tmp_path):
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    clawteam_bin = tmp_path / "venv" / "bin" / "clawteam"
    clawteam_bin.parent.mkdir(parents=True)
    clawteam_bin.write_text("#!/bin/sh\n")
    monkeypatch.setattr(sys, "argv", [str(clawteam_bin)])

    captured: dict[str, object] = {}

    def fake_popen(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["env"] = kwargs["env"]
        return DummyProcess()

    monkeypatch.setattr(
        "clawteam.spawn.command_validation.shutil.which",
        lambda name, path=None: "/usr/bin/codex" if name == "codex" else None,
    )
    monkeypatch.setattr("clawteam.spawn.subprocess_backend.subprocess.Popen", fake_popen)
    monkeypatch.setattr("clawteam.spawn.registry.register_agent", lambda **_: None)

    backend = SubprocessBackend()
    backend.spawn(
        command=["codex"],
        agent_name="worker1",
        agent_id="agent-1",
        agent_type="general-purpose",
        team_name="demo-team",
        prompt="do work",
        cwd="/tmp/demo",
        skip_permissions=True,
    )

    env = captured["env"]
    assert env["PATH"].startswith(f"{clawteam_bin.parent}:")
    assert env["CLAWTEAM_BIN"] == str(clawteam_bin)


def test_tmux_backend_exports_spawn_path_for_agent_commands(monkeypatch, tmp_path):
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    clawteam_bin = tmp_path / "venv" / "bin" / "clawteam"
    clawteam_bin.parent.mkdir(parents=True)
    clawteam_bin.write_text("#!/bin/sh\n")
    monkeypatch.setattr(sys, "argv", [str(clawteam_bin)])

    run_calls: list[list[str]] = []

    class Result:
        def __init__(self, returncode: int = 0, stdout: str = ""):
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = ""

    def fake_run(args, **kwargs):
        run_calls.append(args)
        if args[:3] == ["tmux", "has-session", "-t"]:
            return Result(returncode=1)
        if args[:3] == ["tmux", "list-panes", "-t"]:
            return Result(returncode=0, stdout="9876\n")
        return Result(returncode=0)

    original_which = __import__("shutil").which

    def fake_which(name, path=None):
        if name == "tmux":
            return "/opt/homebrew/bin/tmux"
        if name == "codex":
            return "/usr/bin/codex"
        return original_which(name)

    # Both modules share the same shutil object, so a single setattr
    # covers tmux_backend.shutil.which AND command_validation.shutil.which.
    monkeypatch.setattr("clawteam.spawn.tmux_backend.shutil.which", fake_which)
    monkeypatch.setattr("clawteam.spawn.tmux_backend.subprocess.run", fake_run)
    monkeypatch.setattr("clawteam.spawn.tmux_backend.time.sleep", lambda *_: None)
    monkeypatch.setattr("clawteam.spawn.registry.register_agent", lambda **_: None)

    backend = TmuxBackend()
    backend.spawn(
        command=["codex"],
        agent_name="worker1",
        agent_id="agent-1",
        agent_type="general-purpose",
        team_name="demo-team",
        prompt="do work",
        cwd="/tmp/demo",
        skip_permissions=True,
    )

    new_session = next(call for call in run_calls if call[:3] == ["tmux", "new-session", "-d"])
    full_cmd = new_session[-1]
    assert f"export PATH={clawteam_bin.parent}:/usr/bin:/bin" in full_cmd
    assert f"export CLAWTEAM_BIN={clawteam_bin}" in full_cmd
    assert f"{clawteam_bin} lifecycle on-exit --team demo-team --agent worker1" in full_cmd


def test_tmux_backend_returns_error_when_command_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    clawteam_bin = tmp_path / "venv" / "bin" / "clawteam"
    clawteam_bin.parent.mkdir(parents=True)
    clawteam_bin.write_text("#!/bin/sh\n")
    monkeypatch.setattr(sys, "argv", [str(clawteam_bin)])

    run_calls: list[list[str]] = []

    def fake_which(name, path=None):
        if name == "tmux":
            return "/usr/bin/tmux"
        return None

    def fake_run(args, **kwargs):
        run_calls.append(args)
        raise AssertionError("tmux should not be invoked when the command is missing")

    monkeypatch.setattr("clawteam.spawn.tmux_backend.shutil.which", fake_which)
    monkeypatch.setattr("clawteam.spawn.tmux_backend.subprocess.run", fake_run)

    backend = TmuxBackend()
    result = backend.spawn(
        command=["nanobot"],
        agent_name="worker1",
        agent_id="agent-1",
        agent_type="general-purpose",
        team_name="demo-team",
        prompt="do work",
        cwd="/tmp/demo",
        skip_permissions=True,
    )

    assert result == (
        "Error: command 'nanobot' not found in PATH. "
        "Install the agent CLI first or pass an executable path."
    )
    assert run_calls == []


def test_subprocess_backend_returns_error_when_command_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    clawteam_bin = tmp_path / "venv" / "bin" / "clawteam"
    clawteam_bin.parent.mkdir(parents=True)
    clawteam_bin.write_text("#!/bin/sh\n")
    monkeypatch.setattr(sys, "argv", [str(clawteam_bin)])

    popen_called = False

    def fake_popen(*args, **kwargs):
        nonlocal popen_called
        popen_called = True
        raise AssertionError("Popen should not be called when the command is missing")

    monkeypatch.setattr("clawteam.spawn.subprocess_backend.subprocess.Popen", fake_popen)

    backend = SubprocessBackend()
    result = backend.spawn(
        command=["nanobot"],
        agent_name="worker1",
        agent_id="agent-1",
        agent_type="general-purpose",
        team_name="demo-team",
        prompt="do work",
        cwd="/tmp/demo",
        skip_permissions=True,
    )

    assert result == (
        "Error: command 'nanobot' not found in PATH. "
        "Install the agent CLI first or pass an executable path."
    )
    assert popen_called is False


def test_tmux_backend_normalizes_bare_nanobot_to_agent(monkeypatch, tmp_path):
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    clawteam_bin = tmp_path / "venv" / "bin" / "clawteam"
    clawteam_bin.parent.mkdir(parents=True)
    clawteam_bin.write_text("#!/bin/sh\n")
    monkeypatch.setattr(sys, "argv", [str(clawteam_bin)])

    run_calls: list[list[str]] = []

    class Result:
        def __init__(self, returncode: int = 0, stdout: str = ""):
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = ""

    def fake_run(args, **kwargs):
        run_calls.append(args)
        if args[:3] == ["tmux", "has-session", "-t"]:
            return Result(returncode=1)
        if args[:3] == ["tmux", "list-panes", "-t"]:
            return Result(returncode=0, stdout="9876\n")
        return Result(returncode=0)

    def fake_which(name, path=None):
        if name == "tmux":
            return "/usr/bin/tmux"
        if name == "nanobot":
            return "/usr/bin/nanobot"
        return None

    monkeypatch.setattr("clawteam.spawn.tmux_backend.shutil.which", fake_which)
    monkeypatch.setattr("clawteam.spawn.command_validation.shutil.which", fake_which)
    monkeypatch.setattr("clawteam.spawn.tmux_backend.subprocess.run", fake_run)
    monkeypatch.setattr("clawteam.spawn.tmux_backend.time.sleep", lambda *_: None)
    monkeypatch.setattr("clawteam.spawn.registry.register_agent", lambda **_: None)

    backend = TmuxBackend()
    backend.spawn(
        command=["nanobot"],
        agent_name="worker1",
        agent_id="agent-1",
        agent_type="general-purpose",
        team_name="demo-team",
        prompt="do work",
        cwd="/tmp/demo",
        skip_permissions=True,
    )

    new_session = next(call for call in run_calls if call[:3] == ["tmux", "new-session", "-d"])
    full_cmd = new_session[-1]
    assert " nanobot agent -w /tmp/demo -m 'do work';" in full_cmd


def test_tmux_backend_confirms_claude_workspace_trust_prompt(monkeypatch):
    run_calls: list[list[str]] = []
    capture_count = 0

    class Result:
        def __init__(self, returncode: int = 0, stdout: str = ""):
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = ""

    def fake_run(args, **kwargs):
        nonlocal capture_count
        run_calls.append(args)
        if args[:4] == ["tmux", "capture-pane", "-p", "-t"]:
            capture_count += 1
            if capture_count == 1:
                return Result(
                    stdout=(
                        "Quick safety check\n"
                        "Yes, I trust this folder\n"
                        "Enter to confirm\n"
                    )
                )
            return Result(stdout="")
        return Result()

    monkeypatch.setattr("clawteam.spawn.tmux_backend.subprocess.run", fake_run)
    monkeypatch.setattr("clawteam.spawn.tmux_backend.time.sleep", lambda *_: None)

    confirmed = _confirm_workspace_trust_if_prompted("demo:agent", ["claude"])

    assert confirmed is True
    assert ["tmux", "send-keys", "-t", "demo:agent", "Enter"] in run_calls


def test_tmux_backend_confirms_codex_workspace_trust_prompt(monkeypatch):
    run_calls: list[list[str]] = []

    class Result:
        def __init__(self, returncode: int = 0, stdout: str = ""):
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = ""

    def fake_run(args, **kwargs):
        run_calls.append(args)
        if args[:4] == ["tmux", "capture-pane", "-p", "-t"]:
            return Result(
                stdout=(
                    "Do you trust the contents of this directory?\n"
                    "Press enter to continue\n"
                )
            )
        return Result()

    monkeypatch.setattr("clawteam.spawn.tmux_backend.subprocess.run", fake_run)
    monkeypatch.setattr("clawteam.spawn.tmux_backend.time.sleep", lambda *_: None)

    confirmed = _confirm_workspace_trust_if_prompted("demo:agent", ["codex"])

    assert confirmed is True
    assert ["tmux", "send-keys", "-t", "demo:agent", "Enter"] in run_calls


def test_subprocess_backend_normalizes_nanobot_and_uses_message_flag(monkeypatch, tmp_path):
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    clawteam_bin = tmp_path / "venv" / "bin" / "clawteam"
    clawteam_bin.parent.mkdir(parents=True)
    clawteam_bin.write_text("#!/bin/sh\n")
    monkeypatch.setattr(sys, "argv", [str(clawteam_bin)])

    captured: dict[str, object] = {}

    def fake_popen(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["env"] = kwargs["env"]
        return DummyProcess()

    monkeypatch.setattr(
        "clawteam.spawn.command_validation.shutil.which",
        lambda name, path=None: "/usr/bin/nanobot" if name == "nanobot" else None,
    )
    monkeypatch.setattr("clawteam.spawn.subprocess_backend.subprocess.Popen", fake_popen)
    monkeypatch.setattr("clawteam.spawn.registry.register_agent", lambda **_: None)

    backend = SubprocessBackend()
    backend.spawn(
        command=["nanobot"],
        agent_name="worker1",
        agent_id="agent-1",
        agent_type="general-purpose",
        team_name="demo-team",
        prompt="do work",
        cwd="/tmp/demo",
        skip_permissions=True,
    )

    assert "nanobot agent -w /tmp/demo -m 'do work'" in captured["cmd"]


def test_resolve_clawteam_executable_ignores_unrelated_argv0(monkeypatch, tmp_path):
    unrelated = tmp_path / "not-clawteam-review"
    unrelated.write_text("#!/bin/sh\n")
    resolved_bin = tmp_path / "bin" / "clawteam"
    resolved_bin.parent.mkdir(parents=True)
    resolved_bin.write_text("#!/bin/sh\n")

    monkeypatch.setattr(sys, "argv", [str(unrelated)])
    monkeypatch.setattr("clawteam.spawn.cli_env.shutil.which", lambda name: str(resolved_bin))

    assert resolve_clawteam_executable() == str(resolved_bin)
    assert build_spawn_path("/usr/bin:/bin").startswith(f"{resolved_bin.parent}:")


def test_resolve_clawteam_executable_ignores_relative_argv0_even_if_local_file_exists(
    monkeypatch, tmp_path
):
    local_shadow = tmp_path / "clawteam"
    local_shadow.write_text("#!/bin/sh\n")
    resolved_bin = tmp_path / "venv" / "bin" / "clawteam"
    resolved_bin.parent.mkdir(parents=True)
    resolved_bin.write_text("#!/bin/sh\n")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["clawteam"])
    monkeypatch.setattr("clawteam.spawn.cli_env.shutil.which", lambda name: str(resolved_bin))

    assert resolve_clawteam_executable() == str(resolved_bin)
    assert build_spawn_path("/usr/bin:/bin").startswith(f"{resolved_bin.parent}:")


def test_resolve_clawteam_executable_accepts_relative_path_with_explicit_directory(
    monkeypatch, tmp_path
):
    relative_bin = tmp_path / ".venv" / "bin" / "clawteam"
    relative_bin.parent.mkdir(parents=True)
    relative_bin.write_text("#!/bin/sh\n")
    fallback_bin = tmp_path / "fallback" / "clawteam"
    fallback_bin.parent.mkdir(parents=True)
    fallback_bin.write_text("#!/bin/sh\n")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["./.venv/bin/clawteam"])
    monkeypatch.setattr("clawteam.spawn.cli_env.shutil.which", lambda name: str(fallback_bin))

    assert resolve_clawteam_executable() == str(relative_bin.resolve())
    assert build_spawn_path("/usr/bin:/bin").startswith(f"{relative_bin.parent.resolve()}:")
