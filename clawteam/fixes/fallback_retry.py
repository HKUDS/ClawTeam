"""P0 fix: llm.sub_agent.fallback.failed (~293 errors/day).

Root cause: Sub-agent fallback chain raises immediately without retry.
Solution: Exponential backoff retry + structured fallback chain.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine

from clawteam.fixes.exceptions import SubAgentFallbackExhaustedError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RetryConfig:
    """Value object for retry configuration."""

    max_retries: int = 3
    base_delay: float = 0.5
    max_delay: float = 30.0
    backoff_factor: float = 2.0
    retryable_exceptions: tuple[type[Exception], ...] = (Exception,)

    def __post_init__(self) -> None:
        if self.max_retries < 0:
            raise ValueError(f"max_retries must be >= 0, got {self.max_retries}")
        if self.base_delay < 0:
            raise ValueError(f"base_delay must be >= 0, got {self.base_delay}")
        if self.max_delay < 0:
            raise ValueError(f"max_delay must be >= 0, got {self.max_delay}")
        if self.backoff_factor < 1.0:
            raise ValueError(f"backoff_factor must be >= 1.0, got {self.backoff_factor}")
        if self.max_delay < self.base_delay:
            raise ValueError(
                f"max_delay ({self.max_delay}) must be >= base_delay ({self.base_delay})"
            )


async def retry_with_backoff(
    fn: Callable[..., Coroutine[Any, Any, Any]],
    config: RetryConfig,
    **kwargs: Any,
) -> Any:
    """Execute an async function with exponential backoff retry."""
    last_error: Exception | None = None

    for attempt in range(config.max_retries + 1):
        try:
            return await fn(**kwargs)
        except config.retryable_exceptions as exc:
            if attempt >= config.max_retries:
                raise
            last_error = exc
            delay = min(
                config.base_delay * (config.backoff_factor ** attempt),
                config.max_delay,
            )
            logger.warning(
                "Attempt %d/%d failed: %s. Retrying in %.1fs",
                attempt + 1,
                config.max_retries + 1,
                exc,
                delay,
            )
            await asyncio.sleep(delay)

    raise last_error  # type: ignore[misc]


ProviderFn = Callable[..., Coroutine[Any, Any, Any]]


@dataclass
class FallbackChain:
    """Executes providers in sequence with per-provider retry.

    Each provider is tried with exponential backoff. If all providers fail,
    SubAgentFallbackExhausted is raised with structured error details.
    """

    retry_config: RetryConfig = field(default_factory=RetryConfig)
    _providers: list[tuple[str, ProviderFn]] = field(default_factory=list, init=False)

    def add_provider(self, name: str, fn: ProviderFn) -> FallbackChain:
        """Register a provider function. Returns self for chaining."""
        self._providers.append((name, fn))
        return self

    async def execute(self, **kwargs: Any) -> Any:
        """Execute the fallback chain, trying each provider with retries."""
        if not self._providers:
            raise SubAgentFallbackExhaustedError(providers=[], errors={})

        errors: dict[str, Exception] = {}
        provider_names: list[str] = []

        for name, fn in list(self._providers):
            provider_names.append(name)
            try:
                result = await retry_with_backoff(fn, self.retry_config, **kwargs)
                logger.info("Provider '%s' succeeded", name)
                return result
            except self.retry_config.retryable_exceptions as exc:
                errors[name] = exc
                logger.error(
                    "Provider '%s' exhausted after %d attempts: %s",
                    name,
                    self.retry_config.max_retries + 1,
                    exc,
                )

        raise SubAgentFallbackExhaustedError(providers=provider_names, errors=errors)
