"""Unit tests for wsh spawn backend."""

from __future__ import annotations

import pytest

from clawteam.spawn.wsh_backend import WshBackend


def test_wsh_not_available(monkeypatch):
    """Test spawn fails gracefully without wsh."""
    monkeypatch.setattr("clawteam.spawn.wsh_backend._find_wsh", lambda: None)
    backend = WshBackend()
    result = backend.spawn(
        command=["echo", "test"],
        agent_name="test-agent",
        agent_id="test-id",
        agent_type="general-purpose",
        team_name="test-team",
    )
    assert "not installed" in result.lower()


def test_list_running():
    """Test list_running returns agent info."""
    backend = WshBackend()
    backend._blocks["alice"] = "block-123"
    backend._blocks["bob"] = "block-456"

    running = backend.list_running()

    assert len(running) == 2
    assert running[0]["name"] == "alice"
    assert running[0]["target"] == "block-123"
    assert running[1]["name"] == "bob"
    assert running[1]["target"] == "block-456"


def test_backend_selection():
    """Test get_backend factory selects correct backend."""
    from clawteam.spawn import get_backend
    from clawteam.spawn.tmux_backend import TmuxBackend

    backend = get_backend("wsh")
    assert isinstance(backend, WshBackend)

    backend = get_backend("tmux")
    assert isinstance(backend, TmuxBackend)

    backend = get_backend("subprocess")
    assert backend.__class__.__name__ == "SubprocessBackend"

    with pytest.raises(ValueError):
        get_backend("invalid")
