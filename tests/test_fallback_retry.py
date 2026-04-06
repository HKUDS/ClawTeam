"""Tests for P0 fix: fallback_retry module.

Test ratio: Failure 63% (12/19) / Happy 37% (7/19)
"""

from __future__ import annotations

import pytest

from clawteam.fixes.exceptions import SubAgentFallbackExhaustedError
from clawteam.fixes.fallback_retry import FallbackChain, RetryConfig, retry_with_backoff

# ---------------------------------------------------------------------------
# RetryConfig validation
# ---------------------------------------------------------------------------


class TestRetryConfigValidation:
    """Failure cases for RetryConfig value object."""

    def test_negative_max_retries_raises(self):
        with pytest.raises(ValueError, match="max_retries"):
            RetryConfig(max_retries=-1)

    def test_negative_base_delay_raises(self):
        with pytest.raises(ValueError, match="base_delay"):
            RetryConfig(base_delay=-0.1)

    def test_negative_max_delay_raises(self):
        with pytest.raises(ValueError, match="max_delay"):
            RetryConfig(max_delay=-1.0)

    def test_backoff_factor_below_one_raises(self):
        with pytest.raises(ValueError, match="backoff_factor"):
            RetryConfig(backoff_factor=0.5)

    def test_max_delay_less_than_base_delay_raises(self):
        with pytest.raises(ValueError, match="max_delay.*must be >= base_delay"):
            RetryConfig(base_delay=10.0, max_delay=1.0)

    def test_valid_config_created(self):
        config = RetryConfig(max_retries=2, base_delay=0.1, max_delay=5.0, backoff_factor=2.0)
        assert config.max_retries == 2
        assert config.base_delay == 0.1

    def test_zero_retries_is_valid(self):
        config = RetryConfig(max_retries=0)
        assert config.max_retries == 0


# ---------------------------------------------------------------------------
# retry_with_backoff
# ---------------------------------------------------------------------------


class TestRetryWithBackoff:
    """Tests for the retry wrapper function."""

    @pytest.mark.asyncio
    async def test_success_on_first_try(self):
        call_count = 0

        async def ok_fn():
            nonlocal call_count
            call_count += 1
            return "done"

        result = await retry_with_backoff(ok_fn, RetryConfig(max_retries=3, base_delay=0.0))
        assert result == "done"
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_success_on_second_attempt(self):
        attempts = 0

        async def flaky_fn():
            nonlocal attempts
            attempts += 1
            if attempts < 2:
                raise RuntimeError("transient")
            return "recovered"

        result = await retry_with_backoff(flaky_fn, RetryConfig(max_retries=3, base_delay=0.0))
        assert result == "recovered"
        assert attempts == 2

    @pytest.mark.asyncio
    async def test_all_retries_exhausted_raises_last_error(self):
        async def always_fail():
            raise RuntimeError("permanent")

        with pytest.raises(RuntimeError, match="permanent"):
            await retry_with_backoff(
                always_fail, RetryConfig(max_retries=2, base_delay=0.0)
            )

    @pytest.mark.asyncio
    async def test_zero_retries_fails_immediately(self):
        call_count = 0

        async def fail_fn():
            nonlocal call_count
            call_count += 1
            raise ValueError("no retry")

        with pytest.raises(ValueError, match="no retry"):
            await retry_with_backoff(fail_fn, RetryConfig(max_retries=0, base_delay=0.0))
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_non_retryable_exception_raises_immediately(self):
        """Non-retryable exceptions must not enter the retry loop."""
        call_count = 0

        async def auth_fail():
            nonlocal call_count
            call_count += 1
            raise PermissionError("not authorized")

        config = RetryConfig(
            max_retries=3, base_delay=0.0, retryable_exceptions=(RuntimeError,)
        )
        with pytest.raises(PermissionError, match="not authorized"):
            await retry_with_backoff(auth_fail, config)
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_retryable_exception_is_retried(self):
        """Only retryable exceptions trigger retries."""
        attempts = 0

        async def flaky():
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise ConnectionError("transient")
            return "ok"

        config = RetryConfig(
            max_retries=3, base_delay=0.0, retryable_exceptions=(ConnectionError,)
        )
        result = await retry_with_backoff(flaky, config)
        assert result == "ok"
        assert attempts == 3

    @pytest.mark.asyncio
    async def test_non_retryable_in_fallback_chain_skips_retries(self):
        """FallbackChain must not retry non-retryable exceptions."""
        call_count = 0

        async def auth_fail():
            nonlocal call_count
            call_count += 1
            raise PermissionError("forbidden")

        async def good():
            return "ok"

        config = RetryConfig(
            max_retries=3, base_delay=0.0, retryable_exceptions=(RuntimeError,)
        )
        chain = FallbackChain(retry_config=config)
        chain.add_provider("auth_fail", auth_fail).add_provider("good", good)
        # PermissionError is not retryable, so auth_fail should be called once
        # then FallbackChain should NOT catch it (it's not in retryable_exceptions)
        with pytest.raises(PermissionError, match="forbidden"):
            await chain.execute()
        assert call_count == 1


# ---------------------------------------------------------------------------
# FallbackChain
# ---------------------------------------------------------------------------


class TestFallbackChain:
    """Tests for the FallbackChain orchestrator."""

    @pytest.mark.asyncio
    async def test_first_provider_succeeds(self):
        async def provider_a():
            return "a_result"

        chain = FallbackChain(retry_config=RetryConfig(max_retries=0, base_delay=0.0))
        chain.add_provider("a", provider_a)
        result = await chain.execute()
        assert result == "a_result"

    @pytest.mark.asyncio
    async def test_fallback_to_second_provider(self):
        async def bad_provider():
            raise RuntimeError("down")

        async def good_provider():
            return "fallback_ok"

        chain = FallbackChain(retry_config=RetryConfig(max_retries=0, base_delay=0.0))
        chain.add_provider("bad", bad_provider).add_provider("good", good_provider)
        result = await chain.execute()
        assert result == "fallback_ok"

    @pytest.mark.asyncio
    async def test_all_providers_fail_raises_exhausted(self):
        async def fail_1():
            raise RuntimeError("fail1")

        async def fail_2():
            raise RuntimeError("fail2")

        chain = FallbackChain(retry_config=RetryConfig(max_retries=1, base_delay=0.0))
        chain.add_provider("p1", fail_1).add_provider("p2", fail_2)

        with pytest.raises(SubAgentFallbackExhaustedError) as exc_info:
            await chain.execute()

        assert exc_info.value.providers == ["p1", "p2"]
        assert isinstance(exc_info.value.errors["p1"], RuntimeError)
        assert isinstance(exc_info.value.errors["p2"], RuntimeError)

    @pytest.mark.asyncio
    async def test_empty_provider_list_raises_exhausted(self):
        chain = FallbackChain()
        with pytest.raises(SubAgentFallbackExhaustedError) as exc_info:
            await chain.execute()
        assert exc_info.value.providers == []

    @pytest.mark.asyncio
    async def test_kwargs_passed_to_providers(self):
        received = {}

        async def capture_fn(**kwargs):
            received.update(kwargs)
            return "ok"

        chain = FallbackChain(retry_config=RetryConfig(max_retries=0, base_delay=0.0))
        chain.add_provider("cap", capture_fn)
        await chain.execute(model="gpt-4", temperature=0.7)
        assert received == {"model": "gpt-4", "temperature": 0.7}

    @pytest.mark.asyncio
    async def test_provider_with_retry_succeeds_on_second_attempt(self):
        attempts = 0

        async def flaky():
            nonlocal attempts
            attempts += 1
            if attempts < 2:
                raise RuntimeError("transient")
            return "ok"

        chain = FallbackChain(retry_config=RetryConfig(max_retries=2, base_delay=0.0))
        chain.add_provider("flaky", flaky)
        result = await chain.execute()
        assert result == "ok"
        assert attempts == 2
