"""P1 fix: memory_context_preparation_failed (~84 errors/day).

Root cause: Context assembly lacks None/empty field validation.
Solution: SafeContextBuilder with required field enforcement.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from clawteam.fixes.exceptions import MemoryContextPreparationError


@dataclass(frozen=True)
class ContextField:
    """Value object representing a single context field."""

    name: str
    value: Any
    required: bool = False

    def is_empty(self) -> bool:
        """Check if the value is considered empty (None, empty string, empty list)."""
        if self.value is None:
            return True
        if isinstance(self.value, str) and self.value.strip() == "":
            return True
        if isinstance(self.value, (list, tuple, set, dict)) and len(self.value) == 0:
            return True
        return False


@dataclass
class SafeContextBuilder:
    """Factory that builds context dicts with validation.

    Filters empty fields and enforces required field presence.
    """

    _fields: list[ContextField] = field(default_factory=list, init=False)

    def add_field(self, name: str, value: Any, required: bool = False) -> SafeContextBuilder:
        """Add a field to the context. Returns self for chaining.

        Raises ValueError if a field with the same name already exists.
        """
        existing = {f.name for f in self._fields}
        if name in existing:
            raise ValueError(f"Duplicate field name: '{name}'")
        self._fields.append(ContextField(name=name, value=value, required=required))
        return self

    def build(self) -> dict[str, Any]:
        """Build context dict. Raises MemoryContextPreparationError if required fields are empty."""
        missing = [f.name for f in self._fields if f.required and f.is_empty()]
        if missing:
            raise MemoryContextPreparationError(missing_fields=missing)

        return {f.name: f.value for f in self._fields if not f.is_empty()}

    def build_partial(self) -> dict[str, Any]:
        """Build context dict ignoring required constraints (graceful degradation)."""
        return {f.name: f.value for f in self._fields if not f.is_empty()}
