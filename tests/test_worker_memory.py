"""Tests for P2 fix: worker_memory module.

Test ratio: Failure 62% (8/13) / Happy 38% (5/13)
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from clawteam.fixes.exceptions import WorkerMemoryLimitExceededError
from clawteam.fixes.worker_memory import MemoryGuard, chunked_processor

# ---------------------------------------------------------------------------
# MemoryGuard validation - Failure cases
# ---------------------------------------------------------------------------


class TestMemoryGuardValidation:
    """Failure cases for MemoryGuard construction."""

    def test_zero_limit_mb_raises(self):
        with pytest.raises(ValueError, match="limit_mb must be > 0"):
            MemoryGuard(limit_mb=0)

    def test_negative_limit_mb_raises(self):
        with pytest.raises(ValueError, match="limit_mb must be > 0"):
            MemoryGuard(limit_mb=-100)

    def test_zero_check_interval_raises(self):
        with pytest.raises(ValueError, match="check_interval_items must be > 0"):
            MemoryGuard(limit_mb=512, check_interval_items=0)

    def test_negative_check_interval_raises(self):
        with pytest.raises(ValueError, match="check_interval_items must be > 0"):
            MemoryGuard(limit_mb=512, check_interval_items=-1)


# ---------------------------------------------------------------------------
# MemoryGuard.check() - Failure cases
# ---------------------------------------------------------------------------


class TestMemoryGuardCheck:
    """Tests for memory check enforcement."""

    @patch("clawteam.fixes.worker_memory.MemoryGuard._get_rss_mb", return_value=600.0)
    def test_over_limit_raises(self, _mock_rss):
        guard = MemoryGuard(limit_mb=512)
        with pytest.raises(WorkerMemoryLimitExceededError) as exc_info:
            guard.check()
        assert exc_info.value.limit_mb == 512
        assert exc_info.value.current_mb == 600.0

    @patch("clawteam.fixes.worker_memory.MemoryGuard._get_rss_mb", return_value=100.0)
    def test_under_limit_ok(self, _mock_rss):
        guard = MemoryGuard(limit_mb=512)
        assert guard.check() is True


# ---------------------------------------------------------------------------
# MemoryGuard.guard() decorator
# ---------------------------------------------------------------------------


class TestMemoryGuardDecorator:
    """Tests for the guard decorator."""

    @patch("clawteam.fixes.worker_memory.MemoryGuard._get_rss_mb", return_value=100.0)
    def test_decorated_fn_runs_normally(self, _mock_rss):
        guard = MemoryGuard(limit_mb=512)

        @guard.guard
        def add(a, b):
            return a + b

        assert add(1, 2) == 3

    @patch("clawteam.fixes.worker_memory.MemoryGuard._get_rss_mb", return_value=600.0)
    def test_decorated_fn_blocked_on_oom(self, _mock_rss):
        guard = MemoryGuard(limit_mb=512)

        @guard.guard
        def do_work():
            return "should not reach"

        with pytest.raises(WorkerMemoryLimitExceededError):
            do_work()


# ---------------------------------------------------------------------------
# chunked_processor - Failure cases
# ---------------------------------------------------------------------------


class TestChunkedProcessorFailures:
    """Failure cases for chunked_processor."""

    def test_zero_chunk_size_raises(self):
        with pytest.raises(ValueError, match="chunk_size must be > 0"):
            chunked_processor(items=[1, 2, 3], chunk_size=0, processor_fn=lambda x: x)

    def test_negative_chunk_size_raises(self):
        with pytest.raises(ValueError, match="chunk_size must be > 0"):
            chunked_processor(items=[1, 2, 3], chunk_size=-1, processor_fn=lambda x: x)

    def test_processor_exception_propagated(self):
        def bad_processor(chunk):
            raise RuntimeError("processing failed")

        with pytest.raises(RuntimeError, match="processing failed"):
            chunked_processor(items=[1, 2], chunk_size=1, processor_fn=bad_processor)


# ---------------------------------------------------------------------------
# chunked_processor - Success cases
# ---------------------------------------------------------------------------


class TestChunkedProcessorSuccess:
    """Happy path for chunked_processor."""

    def test_processes_all_chunks(self):
        results = chunked_processor(
            items=[1, 2, 3, 4, 5],
            chunk_size=2,
            processor_fn=lambda chunk: sum(chunk),
        )
        assert results == [3, 7, 5]  # [1+2, 3+4, 5]

    def test_empty_items_returns_empty(self):
        results = chunked_processor(items=[], chunk_size=10, processor_fn=lambda x: x)
        assert results == []

    @patch("clawteam.fixes.worker_memory.MemoryGuard._get_rss_mb", return_value=100.0)
    def test_with_memory_guard(self, _mock_rss):
        guard = MemoryGuard(limit_mb=512)
        results = chunked_processor(
            items=[1, 2, 3],
            chunk_size=1,
            processor_fn=lambda chunk: chunk[0] * 2,
            memory_guard=guard,
        )
        assert results == [2, 4, 6]
