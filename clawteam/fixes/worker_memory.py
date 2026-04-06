"""P2 fix: Worker SIGKILL OOM (~28 errors/day).

Root cause: Batch processing without memory usage control.
Solution: MemoryGuard with RSS monitoring + chunked processing.
"""

from __future__ import annotations

import gc
import os
import resource
from collections.abc import Callable, Iterator
from functools import wraps
from pathlib import Path
from typing import Any, TypeVar

from clawteam.fixes.exceptions import WorkerMemoryLimitExceededError

T = TypeVar("T")

_BYTES_PER_MB = 1024 * 1024
_KB_PER_MB = 1024
_PROC_STATUS = Path("/proc/self/status")


class MemoryGuard:
    """Guards against OOM by checking RSS before operations."""

    def __init__(self, limit_mb: float, check_interval_items: int = 100) -> None:
        if limit_mb <= 0:
            raise ValueError(f"limit_mb must be > 0, got {limit_mb}")
        if check_interval_items <= 0:
            raise ValueError(
                f"check_interval_items must be > 0, got {check_interval_items}"
            )
        self._limit_mb = limit_mb
        self._check_interval_items = check_interval_items

    @property
    def limit_mb(self) -> float:
        return self._limit_mb

    @property
    def check_interval_items(self) -> int:
        return self._check_interval_items

    @staticmethod
    def _get_rss_mb() -> float:
        """Get current process RSS in MB.

        On Linux, reads /proc/self/status for VmRSS (actual current RSS).
        On macOS, falls back to ru_maxrss (peak RSS — best available via stdlib).
        """
        if _PROC_STATUS.exists():
            text = _PROC_STATUS.read_text()
            for line in text.splitlines():
                if line.startswith("VmRSS:"):
                    # VmRSS is reported in kB
                    return int(line.split()[1]) / _KB_PER_MB
        # macOS fallback: ru_maxrss is in bytes on Darwin
        usage = resource.getrusage(resource.RUSAGE_SELF)
        if os.uname().sysname == "Darwin":
            return usage.ru_maxrss / _BYTES_PER_MB
        return usage.ru_maxrss / _KB_PER_MB

    def check(self) -> bool:
        """Check if current RSS is within the memory limit. Returns True if OK."""
        current = self._get_rss_mb()
        if current > self._limit_mb:
            raise WorkerMemoryLimitExceededError(
                limit_mb=self._limit_mb, current_mb=current
            )
        return True

    def guard(self, fn: Callable[..., T]) -> Callable[..., T]:
        """Decorator that checks memory before executing the function."""

        @wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            self.check()
            return fn(*args, **kwargs)

        return wrapper


def chunked_processor(
    items: list[T],
    chunk_size: int,
    processor_fn: Callable[[list[T]], Any],
    memory_guard: MemoryGuard | None = None,
) -> list[Any]:
    """Process items in chunks with optional memory guard and GC hints.

    Args:
        items: Full list of items to process.
        chunk_size: Number of items per chunk.
        processor_fn: Function to process each chunk.
        memory_guard: Optional MemoryGuard instance for per-chunk checks.

    Returns:
        List of results from each chunk.
    """
    if chunk_size <= 0:
        raise ValueError(f"chunk_size must be > 0, got {chunk_size}")

    results: list[Any] = []
    gc_interval = memory_guard.check_interval_items if memory_guard else chunk_size

    for idx, chunk in enumerate(_iter_chunks(items, chunk_size)):
        if memory_guard is not None:
            memory_guard.check()
        results.append(processor_fn(chunk))
        if (idx + 1) % max(1, gc_interval // chunk_size) == 0:
            gc.collect()

    return results


def _iter_chunks(items: list[T], size: int) -> Iterator[list[T]]:
    """Yield successive chunks from items."""
    for i in range(0, len(items), size):
        yield items[i : i + size]
