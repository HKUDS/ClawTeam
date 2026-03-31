"""Tests for spawn backend environment propagation."""

from __future__ import annotations

import subprocess
import sys

from clawteam.spawn.cli_env import build_spawn_path, resolve_clawteam_executable
from clawteam.spawn.subprocess_backend import SubprocessBackend
from clawteam.spawn.tmux_backend import (
    TmuxBackend,
    _confirm_workspace_trust_if_prompted,
    _dismiss_codex_update_prompt_if_present,
    _inject_prompt_via_buffer,
    _wait_for_cli_ready,
)
from clawteam.team.routing_policy import RuntimeEnvelope


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


def test_subprocess_backend_discards_output_and_preserves_exit_hook_and_registry(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    clawteam_bin = tmp_path / "venv" / "bin" / "clawteam"
    clawteam_bin.parent.mkdir(parents=True)
    clawteam_bin.write_text("#!/bin/sh\n")
    monkeypatch.setattr(sys, "argv", [str(clawteam_bin)])

    captured: dict[str, object] = {}
    registered: dict[str, object] = {}

    def fake_popen(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["stdout"] = kwargs["stdout"]
        captured["stderr"] = kwargs["stderr"]
        captured["cwd"] = kwargs["cwd"]
        return DummyProcess(pid=9876)

    def fake_register_agent(**kwargs):
        registered.update(kwargs)

    monkeypatch.setattr(
        "clawteam.spawn.command_validation.shutil.which",
        lambda name, path=None: "/usr/bin/codex" if name == "codex" else None,
    )
    monkeypatch.setattr("clawteam.spawn.subprocess_backend.subprocess.Popen", fake_popen)
    monkeypatch.setattr("clawteam.spawn.registry.register_agent", fake_register_agent)

    backend = SubprocessBackend()
    result = backend.spawn(
        command=["codex"],
        agent_name="worker1",
        agent_id="agent-1",
        agent_type="general-purpose",
        team_name="demo-team",
        prompt="do work",
        cwd="/tmp/demo",
        skip_permissions=True,
    )

    assert result == "Agent 'worker1' spawned as subprocess (pid=9876)"
    assert captured["stdout"] is subprocess.DEVNULL
    assert captured["stderr"] is subprocess.DEVNULL
    assert captured["cwd"] == "/tmp/demo"
    assert (
        f"{clawteam_bin} lifecycle on-exit --team demo-team --agent worker1" in captured["cmd"]
    )
    assert registered == {
        "team_name": "demo-team",
        "agent_name": "worker1",
        "backend": "subprocess",
        "pid": 9876,
        "command": ["codex", "--dangerously-bypass-approvals-and-sandbox", "do work"],
    }


def test_tmux_backend_exports_spawn_path_for_agent_commands(monkeypatch, tmp_path):
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", "/tmp/clawteam-data")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "demo-project")
    monkeypatch.setenv("PROGRAMFILES(X86)", "should-not-be-exported")
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
        return original_which(name, path=path)

    monkeypatch.setattr("clawteam.spawn.tmux_backend.shutil.which", fake_which)
    monkeypatch.setattr("clawteam.spawn.command_validation.shutil.which", fake_which)
    monkeypatch.setattr("clawteam.spawn.tmux_backend.subprocess.run", fake_run)
    monkeypatch.setattr("clawteam.spawn.tmux_backend.time.sleep", lambda *_: None)
    monkeypatch.setattr(
        "clawteam.spawn.tmux_backend._confirm_workspace_trust_if_prompted",
        lambda *_, **__: False,
    )
    monkeypatch.setattr(
        "clawteam.spawn.tmux_backend._dismiss_codex_update_prompt_if_present",
        lambda *_, **__: False,
    )
    monkeypatch.setattr(
        "clawteam.spawn.tmux_backend._wait_for_cli_ready",
        lambda *_, **__: True,
    )
    monkeypatch.setattr("clawteam.spawn.tmux_backend._inject_prompt_via_buffer", lambda *_, **__: None)
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
    assert "export CLAWTEAM_DATA_DIR=/tmp/clawteam-data" in full_cmd
    assert "export GOOGLE_CLOUD_PROJECT=demo-project" in full_cmd
    assert "cd /tmp/demo &&" in full_cmd
    assert "PROGRAMFILES(X86)" not in full_cmd
    assert f"{clawteam_bin} lifecycle on-exit --team demo-team --agent worker1" in full_cmd


def test_tmux_backend_uses_configured_timeout_for_workspace_trust_prompt(monkeypatch, tmp_path):
    from clawteam.config import ClawTeamConfig

    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    clawteam_bin = tmp_path / "venv" / "bin" / "clawteam"
    clawteam_bin.parent.mkdir(parents=True)
    clawteam_bin.write_text("#!/bin/sh\n")
    monkeypatch.setattr(sys, "argv", [str(clawteam_bin)])

    class Result:
        def __init__(self, returncode: int = 0, stdout: str = ""):
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = ""

    def fake_run(args, **kwargs):
        if args[:3] == ["tmux", "has-session", "-t"]:
            return Result(returncode=1)
        if args[:3] == ["tmux", "list-panes", "-t"]:
            return Result(returncode=0, stdout="9876\n")
        return Result(returncode=0)

    captured: dict[str, object] = {}

    def fake_confirm(target, command, timeout_seconds=0.0, poll_interval_seconds=0.2):
        captured["target"] = target
        captured["command"] = command
        captured["timeout_seconds"] = timeout_seconds
        captured["poll_interval_seconds"] = poll_interval_seconds
        return False

    original_which = __import__("shutil").which

    def fake_which(name, path=None):
        if name == "tmux":
            return "/usr/bin/tmux"
        if name == "codex":
            return "/usr/bin/codex"
        return original_which(name, path=path)

    monkeypatch.setattr("clawteam.config.load_config", lambda: ClawTeamConfig(spawn_ready_timeout=42.0))
    monkeypatch.setattr("clawteam.spawn.tmux_backend.shutil.which", fake_which)
    monkeypatch.setattr("clawteam.spawn.command_validation.shutil.which", fake_which)
    monkeypatch.setattr("clawteam.spawn.tmux_backend.subprocess.run", fake_run)
    monkeypatch.setattr("clawteam.spawn.tmux_backend.time.sleep", lambda *_: None)
    monkeypatch.setattr(
        "clawteam.spawn.tmux_backend._confirm_workspace_trust_if_prompted",
        fake_confirm,
    )
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

    assert captured["target"] == "clawteam-demo-team:worker1"
    assert captured["command"] == ["codex"]
    assert captured["timeout_seconds"] == 42.0
    assert captured["poll_interval_seconds"] == 0.2


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


def test_tmux_backend_confirms_claude_skip_permissions_prompt(monkeypatch):
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
                    "Dangerous permission mode\n"
                    "Using --dangerously-skip-permissions\n"
                    "Yes, I accept\n"
                )
            )
        return Result()

    monkeypatch.setattr("clawteam.spawn.tmux_backend.subprocess.run", fake_run)
    monkeypatch.setattr("clawteam.spawn.tmux_backend.time.sleep", lambda *_: None)

    confirmed = _confirm_workspace_trust_if_prompted("demo:agent", ["claude"])

    assert confirmed is True
    assert ["tmux", "send-keys", "-t", "demo:agent", "-l", "\x1b[B"] in run_calls
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


def test_tmux_backend_waits_for_pane_before_declaring_failure(monkeypatch, tmp_path):
    from clawteam.config import ClawTeamConfig

    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    clawteam_bin = tmp_path / "venv" / "bin" / "clawteam"
    clawteam_bin.parent.mkdir(parents=True)
    clawteam_bin.write_text("#!/bin/sh\n")
    monkeypatch.setattr(sys, "argv", [str(clawteam_bin)])

    run_calls: list[list[str]] = []
    pane_calls = 0

    class Result:
        def __init__(self, returncode: int = 0, stdout: str = ""):
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = ""

    def fake_run(args, **kwargs):
        nonlocal pane_calls
        run_calls.append(args)
        if args[:3] == ["tmux", "has-session", "-t"]:
            return Result(returncode=1)
        if args[:3] == ["tmux", "new-session", "-d"]:
            return Result(returncode=0)
        if args[:3] == ["tmux", "list-panes", "-t"]:
            pane_calls += 1
            if pane_calls < 3:
                return Result(returncode=0, stdout="")
            return Result(returncode=0, stdout="9876\n")
        return Result(returncode=0)

    def fake_which(name, path=None):
        if name == "tmux":
            return "/usr/bin/tmux"
        if name == "claude":
            return "/usr/bin/claude"
        return None

    monkeypatch.setattr("clawteam.config.load_config", lambda: ClawTeamConfig())
    monkeypatch.setattr("clawteam.spawn.tmux_backend.shutil.which", fake_which)
    monkeypatch.setattr("clawteam.spawn.command_validation.shutil.which", fake_which)
    monkeypatch.setattr("clawteam.spawn.tmux_backend.subprocess.run", fake_run)
    monkeypatch.setattr("clawteam.spawn.tmux_backend.time.sleep", lambda *_: None)
    monkeypatch.setattr("clawteam.spawn.tmux_backend.time.monotonic", iter(range(100)).__next__)
    monkeypatch.setattr(
        "clawteam.spawn.tmux_backend._confirm_workspace_trust_if_prompted",
        lambda *_, **__: False,
    )
    monkeypatch.setattr(
        "clawteam.spawn.tmux_backend._wait_for_cli_ready",
        lambda *_, **__: True,
    )
    monkeypatch.setattr("clawteam.spawn.tmux_backend._inject_prompt_via_buffer", lambda *_, **__: None)
    monkeypatch.setattr("clawteam.spawn.registry.register_agent", lambda **_: None)

    backend = TmuxBackend()
    result = backend.spawn(
        command=["claude"],
        agent_name="worker1",
        agent_id="agent-1",
        agent_type="general-purpose",
        team_name="demo-team",
        prompt="do work",
        cwd="/tmp/demo",
        skip_permissions=True,
    )

    assert "spawned" in result
    assert pane_calls >= 3
    assert any(call[:3] == ["tmux", "list-panes", "-t"] for call in run_calls)


def test_dismiss_codex_update_prompt_sends_enter(monkeypatch):
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
                        "✨ Update available! 0.113.0 -> 0.116.0\n"
                        "1 Update now\n"
                        "2 Skip\n"
                        "3 Skip until next version\n"
                        "Press enter to continue\n"
                    )
                )
            return Result(stdout=">_ OpenAI Codex (v0.113.0)\n")
        return Result()

    monkeypatch.setattr("clawteam.spawn.tmux_backend.subprocess.run", fake_run)
    monkeypatch.setattr("clawteam.spawn.tmux_backend.time.sleep", lambda *_: None)
    monkeypatch.setattr("clawteam.spawn.tmux_backend.time.monotonic", iter(range(100)).__next__)

    dismissed = _dismiss_codex_update_prompt_if_present(
        "demo:agent",
        ["codex"],
        timeout_seconds=2.0,
        poll_interval_seconds=0.1,
    )

    assert dismissed is True
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


def test_tmux_backend_gemini_skip_permissions_and_prompt(monkeypatch, tmp_path):
    """Gemini gets --yolo for permissions and -p for prompt."""
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
        if name == "gemini":
            return "/usr/bin/gemini"
        return None

    monkeypatch.setattr("clawteam.spawn.tmux_backend.shutil.which", fake_which)
    monkeypatch.setattr("clawteam.spawn.command_validation.shutil.which", fake_which)
    monkeypatch.setattr("clawteam.spawn.tmux_backend.subprocess.run", fake_run)
    monkeypatch.setattr("clawteam.spawn.tmux_backend.time.sleep", lambda *_: None)
    monkeypatch.setattr("clawteam.spawn.registry.register_agent", lambda **_: None)

    backend = TmuxBackend()
    backend.spawn(
        command=["gemini"],
        agent_name="researcher",
        agent_id="agent-2",
        agent_type="general-purpose",
        team_name="demo-team",
        prompt="analyze this repo",
        cwd="/tmp/demo",
        skip_permissions=True,
    )

    new_session = next(call for call in run_calls if call[:3] == ["tmux", "new-session", "-d"])
    full_cmd = new_session[-1]
    assert " gemini --yolo -p 'analyze this repo';" in full_cmd


def test_subprocess_backend_gemini_skip_permissions_and_prompt(monkeypatch, tmp_path):
    """Gemini subprocess uses --yolo and -p flags."""
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    clawteam_bin = tmp_path / "venv" / "bin" / "clawteam"
    clawteam_bin.parent.mkdir(parents=True)
    clawteam_bin.write_text("#!/bin/sh\n")
    monkeypatch.setattr(sys, "argv", [str(clawteam_bin)])

    captured: dict[str, object] = {}

    def fake_popen(cmd, **kwargs):
        captured["cmd"] = cmd
        return DummyProcess()

    monkeypatch.setattr(
        "clawteam.spawn.command_validation.shutil.which",
        lambda name, path=None: "/usr/bin/gemini" if name == "gemini" else None,
    )
    monkeypatch.setattr("clawteam.spawn.subprocess_backend.subprocess.Popen", fake_popen)
    monkeypatch.setattr("clawteam.spawn.registry.register_agent", lambda **_: None)

    backend = SubprocessBackend()
    backend.spawn(
        command=["gemini"],
        agent_name="researcher",
        agent_id="agent-2",
        agent_type="general-purpose",
        team_name="demo-team",
        prompt="analyze this repo",
        cwd="/tmp/demo",
        skip_permissions=True,
    )

    assert "gemini --yolo -p 'analyze this repo'" in captured["cmd"]


def test_tmux_backend_confirms_gemini_workspace_trust_prompt(monkeypatch):
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
                    "Gemini CLI\n"
                    "Trust folder: /tmp/demo\n"
                )
            )
        return Result()

    monkeypatch.setattr("clawteam.spawn.tmux_backend.subprocess.run", fake_run)
    monkeypatch.setattr("clawteam.spawn.tmux_backend.time.sleep", lambda *_: None)

    confirmed = _confirm_workspace_trust_if_prompted("demo:agent", ["gemini"])

    assert confirmed is True
    assert ["tmux", "send-keys", "-t", "demo:agent", "Enter"] in run_calls


def test_tmux_backend_kimi_skip_permissions_workspace_and_prompt(monkeypatch, tmp_path):
    """Kimi gets --yolo, -w for workspace, and --print -p for prompt."""
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
        if name == "kimi":
            return "/usr/bin/kimi"
        return None

    monkeypatch.setattr("clawteam.spawn.tmux_backend.shutil.which", fake_which)
    monkeypatch.setattr("clawteam.spawn.command_validation.shutil.which", fake_which)
    monkeypatch.setattr("clawteam.spawn.tmux_backend.subprocess.run", fake_run)
    monkeypatch.setattr("clawteam.spawn.tmux_backend.time.sleep", lambda *_: None)
    monkeypatch.setattr("clawteam.spawn.registry.register_agent", lambda **_: None)

    backend = TmuxBackend()
    backend.spawn(
        command=["kimi"],
        agent_name="coder",
        agent_id="agent-3",
        agent_type="general-purpose",
        team_name="demo-team",
        prompt="fix the bug",
        cwd="/tmp/demo",
        skip_permissions=True,
    )

    new_session = next(call for call in run_calls if call[:3] == ["tmux", "new-session", "-d"])
    full_cmd = new_session[-1]
    assert " kimi --yolo -w /tmp/demo --print -p 'fix the bug';" in full_cmd


def test_subprocess_backend_kimi_skip_permissions_workspace_and_prompt(monkeypatch, tmp_path):
    """Kimi subprocess uses --yolo, -w, and --print -p flags."""
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    clawteam_bin = tmp_path / "venv" / "bin" / "clawteam"
    clawteam_bin.parent.mkdir(parents=True)
    clawteam_bin.write_text("#!/bin/sh\n")
    monkeypatch.setattr(sys, "argv", [str(clawteam_bin)])

    captured: dict[str, object] = {}

    def fake_popen(cmd, **kwargs):
        captured["cmd"] = cmd
        return DummyProcess()

    monkeypatch.setattr(
        "clawteam.spawn.command_validation.shutil.which",
        lambda name, path=None: "/usr/bin/kimi" if name == "kimi" else None,
    )
    monkeypatch.setattr("clawteam.spawn.subprocess_backend.subprocess.Popen", fake_popen)
    monkeypatch.setattr("clawteam.spawn.registry.register_agent", lambda **_: None)

    backend = SubprocessBackend()
    backend.spawn(
        command=["kimi"],
        agent_name="coder",
        agent_id="agent-3",
        agent_type="general-purpose",
        team_name="demo-team",
        prompt="fix the bug",
        cwd="/tmp/demo",
        skip_permissions=True,
    )

    assert "kimi --yolo -w /tmp/demo --print -p 'fix the bug'" in captured["cmd"]


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


def test_subprocess_backend_injects_system_prompt_for_claude(monkeypatch, tmp_path):
    clawteam_bin = tmp_path / "bin" / "clawteam"
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
        lambda name, path=None: "/usr/bin/claude" if name == "claude" else None,
    )
    monkeypatch.setattr("clawteam.spawn.subprocess_backend.subprocess.Popen", fake_popen)
    monkeypatch.setattr("clawteam.spawn.registry.register_agent", lambda **_: None)

    backend = SubprocessBackend()
    backend.spawn(
        command=["claude"],
        agent_name="worker1",
        agent_id="agent-1",
        agent_type="general-purpose",
        team_name="demo-team",
        prompt="do work",
        skip_permissions=True,
        system_prompt="You are an expert coder.",
    )

    cmd = captured["cmd"]
    assert "--append-system-prompt" in cmd
    assert "You are an expert coder." in cmd
    assert cmd.index("--append-system-prompt") < cmd.index(" -p ")


def test_subprocess_backend_skips_system_prompt_for_non_claude(monkeypatch, tmp_path):
    clawteam_bin = tmp_path / "bin" / "clawteam"
    clawteam_bin.parent.mkdir(parents=True)
    clawteam_bin.write_text("#!/bin/sh\n")
    monkeypatch.setattr(sys, "argv", [str(clawteam_bin)])

    captured: dict[str, object] = {}

    def fake_popen(cmd, **kwargs):
        captured["cmd"] = cmd
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
        system_prompt="some system text",
    )

    assert "--append-system-prompt" not in captured["cmd"]


def test_subprocess_backend_sets_utf8_locale(monkeypatch, tmp_path):
    clawteam_bin = tmp_path / "bin" / "clawteam"
    clawteam_bin.parent.mkdir(parents=True)
    clawteam_bin.write_text("#!/bin/sh\n")
    monkeypatch.setattr(sys, "argv", [str(clawteam_bin)])
    monkeypatch.delenv("LANG", raising=False)
    monkeypatch.delenv("LC_CTYPE", raising=False)

    captured: dict[str, object] = {}

    def fake_popen(cmd, **kwargs):
        captured["env"] = kwargs["env"]
        return DummyProcess()

    monkeypatch.setattr(
        "clawteam.spawn.command_validation.shutil.which",
        lambda name, path=None: "/usr/bin/claude" if name == "claude" else None,
    )
    monkeypatch.setattr("clawteam.spawn.subprocess_backend.subprocess.Popen", fake_popen)
    monkeypatch.setattr("clawteam.spawn.registry.register_agent", lambda **_: None)

    backend = SubprocessBackend()
    backend.spawn(
        command=["claude"],
        agent_name="worker1",
        agent_id="agent-1",
        agent_type="general-purpose",
        team_name="demo-team",
        prompt="使用技能",
    )

    env = captured["env"]
    assert env.get("LANG") == "en_US.UTF-8"
    assert env.get("LC_CTYPE") == "UTF-8"


def test_tmux_backend_injects_system_prompt_for_claude(monkeypatch, tmp_path):
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
        if name == "claude":
            return "/usr/bin/claude"
        return None

    monkeypatch.setattr("clawteam.spawn.tmux_backend.shutil.which", fake_which)
    monkeypatch.setattr("clawteam.spawn.command_validation.shutil.which", fake_which)
    monkeypatch.setattr("clawteam.spawn.tmux_backend.subprocess.run", fake_run)
    monkeypatch.setattr("clawteam.spawn.tmux_backend.time.sleep", lambda *_: None)
    monkeypatch.setattr(
        "clawteam.spawn.tmux_backend._confirm_workspace_trust_if_prompted",
        lambda *_, **__: False,
    )
    monkeypatch.setattr(
        "clawteam.spawn.tmux_backend._wait_for_tui_ready",
        lambda *_, **__: True,
    )
    monkeypatch.setattr("clawteam.spawn.registry.register_agent", lambda **_: None)

    backend = TmuxBackend()
    backend.spawn(
        command=["claude"],
        agent_name="worker1",
        agent_id="agent-1",
        agent_type="general-purpose",
        team_name="demo-team",
        prompt="do work",
        cwd="/tmp/demo",
        system_prompt="You are an expert coder.",
    )

    new_session = next(call for call in run_calls if call[:3] == ["tmux", "new-session", "-d"])
    full_cmd = new_session[-1]
    assert "--append-system-prompt 'You are an expert coder.'" in full_cmd


# ---------------------------------------------------------------------------
# _wait_for_cli_ready tests
# ---------------------------------------------------------------------------


class TestWaitForCliReady:
    """Tests for the generic readiness poller."""

    @staticmethod
    def _fake_run_factory(outputs):
        """Return a fake subprocess.run that yields successive pane contents."""
        idx = {"n": 0}

        class Result:
            def __init__(self, stdout):
                self.returncode = 0
                self.stdout = stdout

        def fake_run(args, **kwargs):
            if args[:4] == ["tmux", "capture-pane", "-p", "-t"]:
                text = outputs[min(idx["n"], len(outputs) - 1)]
                idx["n"] += 1
                return Result(stdout=text)
            return Result(stdout="")

        return fake_run

    def test_detects_prompt_indicator(self, monkeypatch):
        fake = self._fake_run_factory(["Loading...\n", "❯ \n"])
        monkeypatch.setattr("clawteam.spawn.tmux_backend.subprocess.run", fake)
        monkeypatch.setattr("clawteam.spawn.tmux_backend.time.sleep", lambda _: None)
        monkeypatch.setattr("clawteam.spawn.tmux_backend.time.monotonic", iter(range(100)).__next__)

        assert _wait_for_cli_ready("t:a", timeout_seconds=10) is True

    def test_detects_content_stabilisation(self, monkeypatch):
        stable = "Welcome to MyAgent v1\nReady.\n"
        fake = self._fake_run_factory(["Booting...\n", stable, stable, stable])
        monkeypatch.setattr("clawteam.spawn.tmux_backend.subprocess.run", fake)
        monkeypatch.setattr("clawteam.spawn.tmux_backend.time.sleep", lambda _: None)
        monkeypatch.setattr("clawteam.spawn.tmux_backend.time.monotonic", iter(range(100)).__next__)

        assert _wait_for_cli_ready("t:a", timeout_seconds=10) is True

    def test_times_out_on_empty_pane(self, monkeypatch):
        fake = self._fake_run_factory(["", "", ""])
        monkeypatch.setattr("clawteam.spawn.tmux_backend.subprocess.run", fake)
        monkeypatch.setattr("clawteam.spawn.tmux_backend.time.sleep", lambda _: None)
        counter = iter([0, 0.5, 1.0, 1.5, 2.0, 999])
        monkeypatch.setattr("clawteam.spawn.tmux_backend.time.monotonic", lambda: next(counter))

        assert _wait_for_cli_ready("t:a", timeout_seconds=2) is False


# ---------------------------------------------------------------------------
# _inject_prompt_via_buffer tests
# ---------------------------------------------------------------------------


def test_inject_prompt_via_buffer_uses_load_and_paste(monkeypatch, tmp_path):
    run_calls: list[list[str]] = []

    class Result:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(args, **kwargs):
        run_calls.append(args)
        return Result()

    monkeypatch.setattr("clawteam.spawn.tmux_backend.subprocess.run", fake_run)
    monkeypatch.setattr("clawteam.spawn.tmux_backend.time.sleep", lambda _: None)
    monkeypatch.setattr("clawteam.spawn.tmux_backend.tempfile.NamedTemporaryFile",
                        lambda **kw: open(tmp_path / "prompt.txt", kw.get("mode", "w")))
    # NamedTemporaryFile mock won't have .name → use real tempfile
    monkeypatch.undo()  # just use real functions
    monkeypatch.setattr("clawteam.spawn.tmux_backend.subprocess.run", fake_run)
    monkeypatch.setattr("clawteam.spawn.tmux_backend.time.sleep", lambda _: None)

    _inject_prompt_via_buffer("sess:win", "worker1", "hello world")

    cmds = [c[:3] for c in run_calls]
    assert ["tmux", "load-buffer", "-b"] in cmds
    assert ["tmux", "paste-buffer", "-b"] in cmds
    assert ["tmux", "send-keys", "-t"] in cmds
    assert ["tmux", "delete-buffer", "-b"] in cmds


def test_tmux_backend_runtime_injection_returns_false_when_target_missing(monkeypatch):
    class Result:
        def __init__(self, returncode=0, stdout="", stderr=""):
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    def fake_run(args, **kwargs):
        if args[:3] == ["tmux", "list-panes", "-t"]:
            return Result(returncode=1, stderr="can't find session")
        return Result()

    monkeypatch.setattr("clawteam.spawn.tmux_backend.shutil.which", lambda *_args, **_kwargs: "/usr/bin/tmux")
    monkeypatch.setattr("clawteam.spawn.tmux_backend.subprocess.run", fake_run)

    ok, reason = TmuxBackend().inject_runtime_message(
        team="demo",
        agent_name="worker",
        envelope=RuntimeEnvelope(source="leader", target="worker", summary="hello"),
    )

    assert ok is False
    assert "clawteam-demo:worker" in reason


# ---------------------------------------------------------------------------
# End-to-end: qwen & opencode spawn via tmux backend
# ---------------------------------------------------------------------------


def _make_tmux_spawn_harness(monkeypatch, tmp_path, cli_name):
    """Shared harness for tmux spawn tests of new CLIs."""
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    clawteam_bin = tmp_path / "venv" / "bin" / "clawteam"
    clawteam_bin.parent.mkdir(parents=True)
    clawteam_bin.write_text("#!/bin/sh\n")
    monkeypatch.setattr(sys, "argv", [str(clawteam_bin)])

    run_calls: list[list[str]] = []

    class Result:
        def __init__(self, returncode=0, stdout=""):
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
        if name == cli_name:
            return f"/usr/bin/{cli_name}"
        return None

    monkeypatch.setattr("clawteam.spawn.tmux_backend.shutil.which", fake_which)
    monkeypatch.setattr("clawteam.spawn.command_validation.shutil.which", fake_which)
    monkeypatch.setattr("clawteam.spawn.tmux_backend.subprocess.run", fake_run)
    monkeypatch.setattr("clawteam.spawn.tmux_backend.time.sleep", lambda *_: None)
    monkeypatch.setattr("clawteam.spawn.tmux_backend.time.monotonic", lambda: 0)
    monkeypatch.setattr("clawteam.spawn.registry.register_agent", lambda **_: None)

    return run_calls


def test_tmux_backend_qwen_skip_permissions_and_prompt(monkeypatch, tmp_path):
    run_calls = _make_tmux_spawn_harness(monkeypatch, tmp_path, "qwen")

    backend = TmuxBackend()
    result = backend.spawn(
        command=["qwen"],
        agent_name="coder",
        agent_id="agent-q",
        agent_type="general-purpose",
        team_name="demo-team",
        prompt="refactor this",
        cwd="/tmp/demo",
        skip_permissions=True,
    )

    assert "spawned" in result
    new_session = next(c for c in run_calls if c[:3] == ["tmux", "new-session", "-d"])
    full_cmd = new_session[-1]
    assert " qwen --yolo -p 'refactor this';" in full_cmd


def test_tmux_backend_opencode_skip_permissions_and_prompt(monkeypatch, tmp_path):
    run_calls = _make_tmux_spawn_harness(monkeypatch, tmp_path, "opencode")

    backend = TmuxBackend()
    result = backend.spawn(
        command=["opencode"],
        agent_name="coder",
        agent_id="agent-o",
        agent_type="general-purpose",
        team_name="demo-team",
        prompt="fix the bug",
        cwd="/tmp/demo",
        skip_permissions=True,
    )

    assert "spawned" in result
    new_session = next(c for c in run_calls if c[:3] == ["tmux", "new-session", "-d"])
    full_cmd = new_session[-1]
    assert " opencode --yolo -p 'fix the bug';" in full_cmd


def test_subprocess_backend_qwen_skip_permissions_and_prompt(monkeypatch, tmp_path):
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    clawteam_bin = tmp_path / "venv" / "bin" / "clawteam"
    clawteam_bin.parent.mkdir(parents=True)
    clawteam_bin.write_text("#!/bin/sh\n")
    monkeypatch.setattr(sys, "argv", [str(clawteam_bin)])

    captured: dict[str, object] = {}

    def fake_popen(cmd, **kwargs):
        captured["cmd"] = cmd
        return DummyProcess()

    monkeypatch.setattr(
        "clawteam.spawn.command_validation.shutil.which",
        lambda name, path=None: "/usr/bin/qwen" if name == "qwen" else None,
    )
    monkeypatch.setattr("clawteam.spawn.subprocess_backend.subprocess.Popen", fake_popen)
    monkeypatch.setattr("clawteam.spawn.registry.register_agent", lambda **_: None)

    backend = SubprocessBackend()
    backend.spawn(
        command=["qwen"],
        agent_name="coder",
        agent_id="agent-q",
        agent_type="general-purpose",
        team_name="demo-team",
        prompt="refactor this",
        cwd="/tmp/demo",
        skip_permissions=True,
    )

    assert "qwen --yolo -p 'refactor this'" in captured["cmd"]


def test_subprocess_backend_opencode_skip_permissions_and_prompt(monkeypatch, tmp_path):
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    clawteam_bin = tmp_path / "venv" / "bin" / "clawteam"
    clawteam_bin.parent.mkdir(parents=True)
    clawteam_bin.write_text("#!/bin/sh\n")
    monkeypatch.setattr(sys, "argv", [str(clawteam_bin)])

    captured: dict[str, object] = {}

    def fake_popen(cmd, **kwargs):
        captured["cmd"] = cmd
        return DummyProcess()

    monkeypatch.setattr(
        "clawteam.spawn.command_validation.shutil.which",
        lambda name, path=None: "/usr/bin/opencode" if name == "opencode" else None,
    )
    monkeypatch.setattr("clawteam.spawn.subprocess_backend.subprocess.Popen", fake_popen)
    monkeypatch.setattr("clawteam.spawn.registry.register_agent", lambda **_: None)

    backend = SubprocessBackend()
    backend.spawn(
        command=["opencode"],
        agent_name="coder",
        agent_id="agent-o",
        agent_type="general-purpose",
        team_name="demo-team",
        prompt="fix the bug",
        cwd="/tmp/demo",
        skip_permissions=True,
    )

    assert "opencode --yolo -p 'fix the bug'" in captured["cmd"]


def test_load_skill_content_directory_format(tmp_path, monkeypatch):
    from clawteam.cli.commands import _load_skill_content

    skills_root = tmp_path / ".claude" / "skills"
    skill_dir = skills_root / "my-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("skill content here", encoding="utf-8")

    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)

    result = _load_skill_content("my-skill")
    assert result == "skill content here"


def test_load_skill_content_single_file_format(tmp_path, monkeypatch):
    from clawteam.cli.commands import _load_skill_content

    skills_root = tmp_path / ".claude" / "skills"
    skills_root.mkdir(parents=True)
    (skills_root / "gsd-health.md").write_text("# GSD Health\ncheck it", encoding="utf-8")

    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)

    result = _load_skill_content("gsd-health")
    assert result == "# GSD Health\ncheck it"


def test_load_skill_content_returns_none_for_missing(tmp_path, monkeypatch):
    from clawteam.cli.commands import _load_skill_content

    (tmp_path / ".claude" / "skills").mkdir(parents=True)
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)

    assert _load_skill_content("nonexistent") is None


# ---------------------------------------------------------------------------
# pi system_prompt tests
# ---------------------------------------------------------------------------


def test_subprocess_backend_pi_injects_system_prompt(monkeypatch, tmp_path):
    """pi gets --append-system-prompt when system_prompt is provided."""
    clawteam_bin = tmp_path / "bin" / "clawteam"
    clawteam_bin.parent.mkdir(parents=True)
    clawteam_bin.write_text("#!/bin/sh\n")
    monkeypatch.setattr(sys, "argv", [str(clawteam_bin)])

    captured: dict[str, object] = {}

    def fake_popen(cmd, **kwargs):
        captured["cmd"] = cmd
        return DummyProcess()

    monkeypatch.setattr(
        "clawteam.spawn.command_validation.shutil.which",
        lambda name, path=None: "/usr/bin/pi" if name == "pi" else None,
    )
    monkeypatch.setattr("clawteam.spawn.subprocess_backend.subprocess.Popen", fake_popen)
    monkeypatch.setattr("clawteam.spawn.registry.register_agent", lambda **_: None)

    backend = SubprocessBackend()
    backend.spawn(
        command=["pi"],
        agent_name="worker1",
        agent_id="agent-1",
        agent_type="general-purpose",
        team_name="demo-team",
        prompt="do work",
        system_prompt="You are a team worker.",
    )

    cmd = captured["cmd"]
    assert "--append-system-prompt" in cmd
    assert "You are a team worker." in cmd


def test_tmux_backend_pi_injects_system_prompt(monkeypatch, tmp_path):
    """pi in tmux gets --append-system-prompt when system_prompt is provided."""
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
        if name == "pi":
            return "/usr/bin/pi"
        return None

    monkeypatch.setattr("clawteam.spawn.tmux_backend.shutil.which", fake_which)
    monkeypatch.setattr("clawteam.spawn.command_validation.shutil.which", fake_which)
    monkeypatch.setattr("clawteam.spawn.tmux_backend.subprocess.run", fake_run)
    monkeypatch.setattr("clawteam.spawn.tmux_backend.time.sleep", lambda *_: None)
    monkeypatch.setattr("clawteam.spawn.tmux_backend.time.monotonic", lambda: 0)
    monkeypatch.setattr("clawteam.spawn.registry.register_agent", lambda **_: None)

    backend = TmuxBackend()
    backend.spawn(
        command=["pi"],
        agent_name="worker1",
        agent_id="agent-1",
        agent_type="general-purpose",
        team_name="demo-team",
        prompt="do work",
        cwd="/tmp/demo",
        system_prompt="You are a team worker.",
    )

    new_session = next(c for c in run_calls if c[:3] == ["tmux", "new-session", "-d"])
    full_cmd = new_session[-1]
    assert "--append-system-prompt" in full_cmd
    assert "You are a team worker." in full_cmd
