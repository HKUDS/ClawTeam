"""Cross-platform compatibility helpers for ClawTeam."""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path

if os.name == "nt":
    import msvcrt
else:  # pragma: no cover
    import fcntl  # type: ignore


@contextmanager
def exclusive_lock(file_obj):
    """Cross-platform exclusive file lock.

    Uses advisory flock on Unix and msvcrt.locking on Windows.
    Locks the first byte of the file, which is sufficient because all callers
    coordinate through the same lock file handle.
    """
    if os.name == "nt":
        file_obj.seek(0)
        file_obj.write("0")
        file_obj.flush()
        file_obj.seek(0)
        msvcrt.locking(file_obj.fileno(), msvcrt.LK_LOCK, 1)
        try:
            yield
        finally:
            file_obj.seek(0)
            msvcrt.locking(file_obj.fileno(), msvcrt.LK_UNLCK, 1)
    else:  # pragma: no cover
        fcntl.flock(file_obj.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(file_obj.fileno(), fcntl.LOCK_UN)


def is_path_locked(path: Path) -> bool:
    """Best-effort lock probe.

    On Windows this attempts a 1-byte non-blocking lock via msvcrt.
    """
    try:
        handle = path.open("a+b")
    except Exception:
        return True
    try:
        if os.name == "nt":
            try:
                if handle.tell() == 0:
                    handle.write(b"0")
                    handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                return False
            except OSError:
                return True
        else:  # pragma: no cover
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                return True
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            return False
    finally:
        handle.close()
