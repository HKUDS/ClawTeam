"""Team-scoped context artifacts for large handoffs and derived notes."""

from __future__ import annotations

import uuid
from pathlib import Path

from clawteam.paths import ensure_within_root, validate_identifier
from clawteam.team.models import get_data_dir

DEFAULT_CONTEXT_SUMMARY_CHARS = 220


def team_context_artifacts_path(team_name: str) -> Path:
    """Return the team-scoped context artifact directory."""
    return ensure_within_root(
        get_data_dir() / "teams",
        validate_identifier(team_name, "team name"),
        "artifacts",
        "context",
    )


def stage_context_artifact(
    team_name: str,
    author: str,
    kind: str,
    content: str,
    *,
    extension: str = ".md",
) -> Path:
    """Persist a context artifact under the team directory and return its path."""
    validate_identifier(team_name, "team name")
    validate_identifier(author, "author")
    validate_identifier(kind, "artifact kind")

    artifact_dir = team_context_artifacts_path(team_name)
    artifact_dir.mkdir(parents=True, exist_ok=True)

    suffix = extension if extension.startswith(".") else f".{extension}"
    filename = f"{kind}-{author}-{uuid.uuid4().hex[:8]}{suffix}"
    path = ensure_within_root(artifact_dir, filename)
    path.write_text(content, encoding="utf-8")
    return path


def summarize_context_text(text: str, *, max_chars: int = DEFAULT_CONTEXT_SUMMARY_CHARS) -> str:
    """Build a small reusable summary for artifact-backed context text."""
    collapsed = " ".join(line.strip() for line in text.splitlines() if line.strip())
    if not collapsed:
        return "Context artifact available."
    if len(collapsed) <= max_chars:
        return collapsed
    return f"{collapsed[: max_chars - 3].rstrip()}..."
