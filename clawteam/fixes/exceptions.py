"""Custom exceptions for service:core error patterns."""

from __future__ import annotations


class CoreServiceError(Exception):
    """Base exception for all service:core errors."""


class SubAgentFallbackExhaustedError(CoreServiceError):
    """All fallback providers have been exhausted after retries."""

    def __init__(
        self, providers: list[str], errors: dict[str, Exception | str]
    ) -> None:
        self.providers = providers
        self.errors = errors
        detail = ", ".join(f"{name}: {err}" for name, err in errors.items())
        super().__init__(f"All {len(providers)} providers exhausted. Details: {detail}")


class MemoryContextPreparationError(CoreServiceError):
    """Failed to prepare memory context due to missing required fields."""

    def __init__(self, missing_fields: list[str]) -> None:
        self.missing_fields = missing_fields
        super().__init__(
            f"Required context fields missing or empty: {', '.join(missing_fields)}"
        )


class WorkerMemoryLimitExceededError(CoreServiceError):
    """Worker process exceeded memory limit."""

    def __init__(self, limit_mb: float, current_mb: float) -> None:
        self.limit_mb = limit_mb
        self.current_mb = current_mb
        super().__init__(
            f"Memory limit exceeded: {current_mb:.1f}MB used, {limit_mb:.1f}MB limit"
        )
