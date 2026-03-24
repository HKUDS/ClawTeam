"""Filesystem helpers with Windows-safe atomic replacement."""

from __future__ import annotations

from pathlib import Path


def replace_file(src: Path, dst: Path) -> None:
    """Atomically replace dst with src where supported.

    Path.replace() uses os.replace under the hood and works on Windows when
    the destination exists, unlike rename semantics used elsewhere.
    """
    src.replace(dst)
