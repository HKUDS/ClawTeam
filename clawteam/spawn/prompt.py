"""Agent prompt builder — identity + task + context awareness.

Coordination knowledge (how to use clawteam CLI) is provided
by the ClawTeam Skill, not duplicated here.
"""

from __future__ import annotations

import re
from pathlib import Path


def _extract_path_references(text: str) -> list[str]:
    """Extract file path references from task text.

    Looks for absolute paths (starting with /) and common relative paths
    that look like file references (containing a dot extension or ending with /).
    """
    # Match paths like /foo/bar.py, src/main.rs, ./config.json, etc.
    # Excludes URLs (http://, https://) and common non-path patterns
    pattern = r'(?<!\w)(?:\.?/[\w./-]+|[\w][\w/-]*\.[\w]+)'
    candidates = re.findall(pattern, text)
    # Filter out things that look like URLs, URL path components, or version numbers
    # Also remove anything preceded by :// in the original text
    url_pattern = re.compile(r'https?://\S+')
    url_spans = [(m.start(), m.end()) for m in url_pattern.finditer(text)]
    result = []
    for p in candidates:
        if p.startswith("http") or ".." in p:
            continue
        # Check if this match falls within a URL span
        idx = text.find(p)
        in_url = any(start <= idx < end for start, end in url_spans)
        if in_url:
            continue
        result.append(p)
    return result


def _check_path_references(task: str, workspace_dir: str) -> list[str]:
    """Check task text for file path references that don't exist.

    Returns list of warning strings for missing paths.
    """
    if not workspace_dir:
        return []
    refs = _extract_path_references(task)
    warnings = []
    ws = Path(workspace_dir)
    for ref in refs:
        if ref.startswith("/"):
            full = Path(ref)
        else:
            full = ws / ref
        if not full.exists():
            warnings.append(f"Referenced path not found: {ref}")
    return warnings


def _build_context_block(team_name: str, agent_name: str, repo: str | None = None) -> str:
    """Build a context awareness block from the workspace context layer.

    Includes recent changes from teammates, file overlap warnings,
    and upstream dependency context. Returns empty string if context
    layer is unavailable or no relevant context exists.
    """
    try:
        from clawteam.workspace.context import inject_context
        ctx = inject_context(team_name, agent_name, repo)
        if ctx and "No cross-agent context" not in ctx:
            return ctx
    except Exception:
        pass
    return ""


def build_agent_prompt(
    agent_name: str,
    agent_id: str,
    agent_type: str,
    team_name: str,
    leader_name: str,
    task: str,
    user: str = "",
    workspace_dir: str = "",
    workspace_branch: str = "",
    isolated_workspace: bool = False,
    repo_path: str | None = None,
) -> str:
    """Build agent prompt: identity + task + context + coordination."""
    lines = [
        "## Identity\n",
        f"- Name: {agent_name}",
        f"- ID: {agent_id}",
    ]
    if user:
        lines.append(f"- User: {user}")
    lines.extend([
        f"- Type: {agent_type}",
        f"- Team: {team_name}",
        f"- Leader: {leader_name}",
    ])
    if workspace_dir:
        lines.extend([
            "",
            "## Workspace",
            f"- Working directory: {workspace_dir}",
        ])
        if isolated_workspace:
            lines.extend([
                f"- Branch: {workspace_branch}",
                "- This is an isolated git worktree. Your changes do not affect the main branch.",
            ])
        else:
            lines.append("- Work directly in this repository path unless told otherwise.")

    lines.extend([
        "",
        "## Task\n",
        task,
    ])

    # Check for referenced paths that don't exist
    path_warnings = _check_path_references(task, workspace_dir)
    if path_warnings:
        lines.extend([
            "",
            "## Path Warnings\n",
            "The following paths referenced in the task were not found:",
        ])
        for w in path_warnings:
            lines.append(f"- {w}")
        lines.append("- Verify these paths before starting work.")

    # Inject cross-agent context awareness
    context_block = _build_context_block(team_name, agent_name, repo_path)
    if context_block:
        lines.extend([
            "",
            "## Context\n",
            context_block,
        ])

    lines.extend([
        "",
        "## Coordination Protocol\n",
        f"- Use `clawteam task list {team_name} --owner {agent_name}` to see your tasks.",
        f"- Starting a task: `clawteam task update {team_name} <task-id> --status in_progress`",
        "- Before marking a task completed, commit your changes in this repository with git.",
        '- Use a clear commit message, e.g. `git add -A && git commit -m "Implement <task summary>"`.',
        f"- Finishing a task: `clawteam task update {team_name} <task-id> --status completed`",
        "- When you finish all tasks, send a summary to the leader:",
        f'  `clawteam inbox send {team_name} {leader_name} "All tasks completed. <brief summary>"`',
        "- If you are blocked or need help, message the leader:",
        f'  `clawteam inbox send {team_name} {leader_name} "Need help: <description>"`',
        f"- After finishing work, report your costs: `clawteam cost report {team_name} --input-tokens <N> --output-tokens <N> --cost-cents <N>`",
        f"- Before finishing, save your session: `clawteam session save {team_name} --session-id <id>`",
        "",
    ])
    return "\n".join(lines)
