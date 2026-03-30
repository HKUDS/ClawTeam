"""Shared skill-loading helpers for room and agent launches."""

from __future__ import annotations

import os
from pathlib import Path

from clawteam.spawn.adapters import is_claude_command, is_pi_command
from clawteam.spawn.command_validation import normalize_spawn_command


def _skill_roots() -> list[Path]:
    roots: list[Path] = []
    codex_home = os.environ.get("CODEX_HOME", "").strip()
    if codex_home:
        roots.append(Path(codex_home).expanduser() / "skills")
    roots.extend([
        Path.home() / ".codex" / "skills",
        Path.home() / ".claude" / "skills",
    ])

    deduped: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        key = str(root)
        if key not in seen:
            seen.add(key)
            deduped.append(root)
    return deduped


def load_skill_content(name: str) -> str | None:
    """Load skill content from Codex/Claude skill directories."""
    for skills_root in _skill_roots():
        skill_dir = skills_root / name
        if skill_dir.is_dir():
            skill_file = skill_dir / "SKILL.md"
            if not skill_file.exists():
                markdown_files = sorted(skill_dir.glob("*.md"))
                skill_file = markdown_files[0] if markdown_files else None
            if skill_file and skill_file.exists():
                return skill_file.read_text(encoding="utf-8")

        single_file = skills_root / f"{name}.md"
        if single_file.exists():
            return single_file.read_text(encoding="utf-8")
    return None


def load_skill_bundle(skill_names: list[str] | None) -> tuple[str | None, list[str]]:
    """Return combined skill guidance plus any missing skill names."""
    if not skill_names:
        return None, []

    parts: list[str] = []
    missing: list[str] = []
    for skill_name in skill_names:
        content = load_skill_content(skill_name)
        if content is None:
            missing.append(skill_name)
            continue
        parts.append(content)
    return ("\n\n".join(parts) if parts else None), missing


def split_guidance_for_command(command: list[str], guidance: str | None) -> tuple[str | None, str | None]:
    """Route shared guidance to system_prompt when supported, else prompt text."""
    if not guidance:
        return None, None
    normalized_command = normalize_spawn_command(command)
    if is_claude_command(normalized_command) or is_pi_command(normalized_command):
        return guidance, None
    return None, guidance


def append_guidance_to_prompt(prompt: str, guidance: str | None) -> str:
    """Append shared room guidance to the normal prompt when needed."""
    if not guidance:
        return prompt
    return "\n\n".join([prompt, "## Room Guidance\n", guidance])
