"""Tests for P1 fix: memory_context module.

Test ratio: Failure 64% (9/14) / Happy 36% (5/14)
"""

from __future__ import annotations

import pytest

from clawteam.fixes.exceptions import MemoryContextPreparationError
from clawteam.fixes.memory_context import ContextField, SafeContextBuilder

# ---------------------------------------------------------------------------
# ContextField value object
# ---------------------------------------------------------------------------


class TestContextField:
    """Tests for ContextField.is_empty()."""

    def test_none_is_empty(self):
        assert ContextField(name="x", value=None).is_empty() is True

    def test_empty_string_is_empty(self):
        assert ContextField(name="x", value="").is_empty() is True

    def test_whitespace_string_is_empty(self):
        assert ContextField(name="x", value="   ").is_empty() is True

    def test_empty_list_is_empty(self):
        assert ContextField(name="x", value=[]).is_empty() is True

    def test_empty_dict_is_empty(self):
        assert ContextField(name="x", value={}).is_empty() is True

    def test_nonempty_string_is_not_empty(self):
        assert ContextField(name="x", value="hello").is_empty() is False

    def test_zero_is_not_empty(self):
        assert ContextField(name="x", value=0).is_empty() is False


# ---------------------------------------------------------------------------
# SafeContextBuilder.build() - Failure cases
# ---------------------------------------------------------------------------


class TestSafeContextBuilderBuildFailures:
    """Failure cases for build()."""

    def test_required_field_none_raises(self):
        builder = SafeContextBuilder()
        builder.add_field("user_id", None, required=True)
        with pytest.raises(MemoryContextPreparationError) as exc_info:
            builder.build()
        assert "user_id" in exc_info.value.missing_fields

    def test_required_field_empty_string_raises(self):
        builder = SafeContextBuilder()
        builder.add_field("session", "", required=True)
        with pytest.raises(MemoryContextPreparationError) as exc_info:
            builder.build()
        assert "session" in exc_info.value.missing_fields

    def test_required_field_empty_list_raises(self):
        builder = SafeContextBuilder()
        builder.add_field("tags", [], required=True)
        with pytest.raises(MemoryContextPreparationError) as exc_info:
            builder.build()
        assert "tags" in exc_info.value.missing_fields

    def test_multiple_required_fields_missing(self):
        builder = SafeContextBuilder()
        builder.add_field("a", None, required=True)
        builder.add_field("b", "", required=True)
        builder.add_field("c", "ok", required=True)
        with pytest.raises(MemoryContextPreparationError) as exc_info:
            builder.build()
        assert sorted(exc_info.value.missing_fields) == ["a", "b"]

    def test_required_whitespace_only_raises(self):
        builder = SafeContextBuilder()
        builder.add_field("name", "   \t ", required=True)
        with pytest.raises(MemoryContextPreparationError):
            builder.build()


# ---------------------------------------------------------------------------
# SafeContextBuilder.build() - Success cases
# ---------------------------------------------------------------------------


class TestSafeContextBuilderBuildSuccess:
    """Happy path for build()."""

    def test_all_fields_present(self):
        builder = SafeContextBuilder()
        builder.add_field("user_id", "u123", required=True)
        builder.add_field("context", "some text", required=True)
        result = builder.build()
        assert result == {"user_id": "u123", "context": "some text"}

    def test_optional_empty_fields_filtered(self):
        builder = SafeContextBuilder()
        builder.add_field("user_id", "u1", required=True)
        builder.add_field("optional", None, required=False)
        result = builder.build()
        assert result == {"user_id": "u1"}

    def test_empty_builder_returns_empty_dict(self):
        builder = SafeContextBuilder()
        result = builder.build()
        assert result == {}


# ---------------------------------------------------------------------------
# SafeContextBuilder.build_partial() - graceful degradation
# ---------------------------------------------------------------------------


class TestSafeContextBuilderBuildPartial:
    """Tests for build_partial (ignores required constraint)."""

    def test_partial_ignores_missing_required(self):
        builder = SafeContextBuilder()
        builder.add_field("a", None, required=True)
        builder.add_field("b", "value", required=True)
        result = builder.build_partial()
        assert result == {"b": "value"}

    def test_all_none_returns_empty(self):
        builder = SafeContextBuilder()
        builder.add_field("x", None, required=True)
        builder.add_field("y", None, required=False)
        result = builder.build_partial()
        assert result == {}

    def test_duplicate_field_name_raises(self):
        builder = SafeContextBuilder()
        builder.add_field("key", "first")
        with pytest.raises(ValueError, match="Duplicate field name"):
            builder.add_field("key", "second")
