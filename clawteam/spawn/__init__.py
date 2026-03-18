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
    elif name == "acpx":
        from clawteam.spawn.acpx_backend import AcpxBackend
        from clawteam.config import load_config
        cfg = load_config()
        acpx_path = getattr(cfg, "acpx_path", "") or "acpx"
        return AcpxBackend(acpx_path=acpx_path)
    else:
        raise ValueError(f"Unknown spawn backend: {name}. Available: subprocess, tmux, acpx")


__all__ = ["SpawnBackend", "get_backend"]
