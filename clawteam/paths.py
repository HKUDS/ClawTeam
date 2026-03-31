"""Helpers for validating logical identifiers and constraining data paths."""

from __future__ import annotations

import re
from pathlib import Path

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def validate_identifier(value: str, kind: str = "identifier", allow_empty: bool = False) -> str:
    """Validate a logical identifier used in filesystem-backed state."""
    if value == "" and allow_empty:
        return value
    if not value:
        raise ValueError(f"Invalid {kind}: value must not be empty")
    if not _IDENTIFIER_RE.fullmatch(value):
        raise ValueError(
            f"Invalid {kind}: only letters, digits, '.', '_' and '-' are allowed"
        )
    return value


def ensure_within_root(root: Path, *parts: str) -> Path:
    """Join *parts* under *root* and reject escapes outside the root."""
    base = root.resolve()
    candidate = root.joinpath(*parts)
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(base)
    except ValueError as exc:
        raise ValueError("Resolved path escapes the configured data directory") from exc
    return candidate
