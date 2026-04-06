"""Datadog service:core error pattern fixes.

Addresses top-3 error patterns (466 errors/24h):
- P0: llm.sub_agent.fallback.failed (63%) - fallback_retry
- P1: memory_context_preparation_failed (18%) - memory_context
- P2: Worker SIGKILL OOM (6%) - worker_memory
"""

from __future__ import annotations

from clawteam.fixes.exceptions import (
    CoreServiceError,
    MemoryContextPreparationError,
    SubAgentFallbackExhaustedError,
    WorkerMemoryLimitExceededError,
)

__all__ = [
    "CoreServiceError",
    "MemoryContextPreparationError",
    "SubAgentFallbackExhaustedError",
    "WorkerMemoryLimitExceededError",
]
