"""Spawn backends for launching team agents."""

from __future__ import annotations

from clawteam.spawn.base import SpawnBackend


def get_backend(name: str = "tmux") -> SpawnBackend:
    """Factory function to get a spawn backend by name."""
    if name == "subprocess":
        from clawteam.spawn.subprocess_backend import SubprocessBackend
        return SubprocessBackend()
    elif name == "tmux":
        from clawteam.spawn.tmux_backend import TmuxBackend
        return TmuxBackend()
    elif name == "windows":
        from clawteam.spawn.subprocess_backend import SubprocessBackend
        return SubprocessBackend()
    else:
        raise ValueError(f"Unknown spawn backend: {name}. Available: subprocess, tmux, windows")


__all__ = ["SpawnBackend", "get_backend"]
