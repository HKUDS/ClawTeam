"""Tests for spawn backend environment propagation."""

from __future__ import annotations

import sys

from clawteam.spawn.cli_env import build_spawn_path, resolve_clawteam_executable
from clawteam.spawn.subprocess_backend import SubprocessBackend
from clawteam.spawn.tmux_backend import (
    TmuxBackend,
    _confirm_workspace_trust_if_prompted,
    _inject_prompt_via_buffer,
    _wait_for_cli_ready,
)


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
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", "/tmp/clawteam-data")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "demo-project")
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


def test_tmux_backend_normalizes_bare_openclaw_and_uses_message_flag(monkeypatch, tmp_path):
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
        if name == "openclaw":
            return "/usr/bin/openclaw"
        return None

    monkeypatch.setattr("clawteam.spawn.tmux_backend.shutil.which", fake_which)
    monkeypatch.setattr("clawteam.spawn.command_validation.shutil.which", fake_which)
    monkeypatch.setattr("clawteam.spawn.tmux_backend.subprocess.run", fake_run)
    monkeypatch.setattr("clawteam.spawn.tmux_backend.time.sleep", lambda *_: None)
    monkeypatch.setattr("clawteam.spawn.registry.register_agent", lambda **_: None)

    backend = TmuxBackend()
    backend.spawn(
        command=["openclaw"],
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
    assert " openclaw agent --message 'do work';" in full_cmd
    assert " openclaw agent -p 'do work';" not in full_cmd


def test_subprocess_backend_normalizes_openclaw_and_uses_message_flag(monkeypatch, tmp_path):
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
        lambda name, path=None: "/usr/bin/openclaw" if name == "openclaw" else None,
    )
    monkeypatch.setattr("clawteam.spawn.subprocess_backend.subprocess.Popen", fake_popen)
    monkeypatch.setattr("clawteam.spawn.registry.register_agent", lambda **_: None)

    backend = SubprocessBackend()
    backend.spawn(
        command=["openclaw"],
        agent_name="worker1",
        agent_id="agent-1",
        agent_type="general-purpose",
        team_name="demo-team",
        prompt="do work",
        cwd="/tmp/demo",
        skip_permissions=True,
    )

    assert "openclaw agent --message 'do work'" in captured["cmd"]
    assert "openclaw agent -p 'do work'" not in captured["cmd"]


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
    assert " qwen --dangerously-skip-permissions -p 'refactor this';" in full_cmd


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

    assert "qwen --dangerously-skip-permissions -p 'refactor this'" in captured["cmd"]


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
