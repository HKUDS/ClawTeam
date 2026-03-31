"""Atomic file writes and advisory file locking.

Provides two primitives used throughout the codebase to guarantee safe
concurrent access to shared JSON state files (config, cost summaries,
spawn registries, etc.).

* ``atomic_write_text`` — mkstemp in the target directory, write, then
  ``os.replace`` so readers never see a partially-written file.
* ``file_locked`` — context manager that holds an exclusive advisory lock
  on a sidecar ``.lock`` file, serialising read-modify-write sequences.
"""

from __future__ import annotations

import os
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

if sys.platform == "win32":
    import msvcrt
else:
    import fcntl


def atomic_write_text(
    path: Path,
    content: str,
    *,
    encoding: str = "utf-8",
) -> None:
    """Write *content* to *path* atomically.

    A unique temporary file is created via ``mkstemp`` in the same directory
    as *path*, written to, then moved into place with ``os.replace``.  If
    anything goes wrong the temp file is cleaned up and the original *path*
    is left untouched.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding=encoding) as f:
            f.write(content)
        os.replace(tmp, str(path))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


@contextmanager
def file_locked(path: Path) -> Iterator[None]:
    """Exclusive advisory lock scoped to *path*.

    Creates (or opens) a sidecar ``<path>.lock`` file and holds
    an exclusive advisory lock for the duration of the ``with`` block. This
    serialises concurrent read-modify-write sequences on the same
    logical file across processes.
    """
    lock_path = Path(str(path) + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+") as fh:
        if sys.platform == "win32":
            pos = fh.tell()
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_LOCK, 1)
            fh.seek(pos)
        else:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if sys.platform == "win32":
                pos = fh.tell()
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
                fh.seek(pos)
            else:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
