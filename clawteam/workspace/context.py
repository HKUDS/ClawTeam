"""Git context layer — provides cross-agent awareness of changes, file ownership, and overlap."""

from __future__ import annotations

import json
from pathlib import Path

from clawteam.paths import ensure_within_root, validate_identifier
from clawteam.team.models import get_data_dir
from clawteam.workspace import git
from clawteam.workspace.manager import WorkspaceManager, _load_registry


def _registry_repo_root(team_name: str) -> str | None:
    path = ensure_within_root(
        get_data_dir() / "workspaces",
        validate_identifier(team_name, "team name"),
        "workspace-registry.json",
    )
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    repo_root = data.get("repo_root")
    if not isinstance(repo_root, str) or not repo_root:
        return None
    return repo_root


def _resolve_repo_path(team_name: str, repo: str | None = None) -> str | None:
    return repo or _registry_repo_root(team_name)


def _ws_manager(team_name: str, repo: str | None = None) -> WorkspaceManager:
    resolved_repo = _resolve_repo_path(team_name, repo)
    path = Path(resolved_repo) if resolved_repo else None
    mgr = WorkspaceManager.try_create(path)
    if mgr is None:
        raise RuntimeError("Not inside a git repository")
    return mgr


def _agent_branch(team_name: str, agent_name: str) -> str:
    return f"clawteam/{team_name}/{agent_name}"


def _base_branch(team_name: str, agent_name: str, mgr: WorkspaceManager) -> str:
    ws = mgr.get_workspace(team_name, agent_name)
    return ws.base_branch if ws else mgr.base_branch


# ---------------------------------------------------------------------------
# agent_diff
# ---------------------------------------------------------------------------

def agent_diff(team_name: str, agent_name: str, repo: str | None = None) -> dict:
    """Return diff statistics for an agent's branch vs. its base.

    Keys: files_changed, insertions, deletions, diff_stat, commit_count, summary
    """
    mgr = _ws_manager(team_name, repo)
    branch = _agent_branch(team_name, agent_name)
    base = _base_branch(team_name, agent_name, mgr)
    root = mgr.repo_root

    # numstat gives machine-readable per-file stats
    try:
        numstat_raw = git._run(
            ["diff", "--numstat", f"{base}...{branch}"], cwd=root, check=False,
        )
    except Exception:
        numstat_raw = ""

    files_changed: list[str] = []
    insertions = 0
    deletions = 0
    for line in numstat_raw.splitlines():
        parts = line.split("\t")
        if len(parts) == 3:
            ins, dels, fname = parts
            files_changed.append(fname)
            if ins != "-":
                insertions += int(ins)
            if dels != "-":
                deletions += int(dels)

    # Stat for human display
    try:
        diff_stat = git._run(
            ["diff", "--stat", f"{base}...{branch}"], cwd=root, check=False,
        )
    except Exception:
        diff_stat = ""

    # Commit count
    try:
        count_raw = git._run(
            ["rev-list", "--count", f"{base}..{branch}"], cwd=root, check=False,
        )
        commit_count = int(count_raw) if count_raw.strip().isdigit() else 0
    except Exception:
        commit_count = 0

    summary = (
        f"{agent_name}: {len(files_changed)} file(s), "
        f"+{insertions}/-{deletions}, {commit_count} commit(s)"
    )
    return {
        "files_changed": files_changed,
        "insertions": insertions,
        "deletions": deletions,
        "diff_stat": diff_stat,
        "commit_count": commit_count,
        "summary": summary,
    }


# ---------------------------------------------------------------------------
# file_owners
# ---------------------------------------------------------------------------

def file_owners(team_name: str, repo: str | None = None) -> dict[str, list[str]]:
    """Map each modified file to the list of agents that touched it."""
    mgr = _ws_manager(team_name, repo)
    registry = _load_registry(team_name, str(mgr.repo_root))
    owners: dict[str, list[str]] = {}

    for ws in registry.workspaces:
        branch = ws.branch_name
        base = ws.base_branch
        try:
            numstat = git._run(
                ["diff", "--numstat", f"{base}...{branch}"],
                cwd=mgr.repo_root,
                check=False,
            )
        except Exception:
            continue
        for line in numstat.splitlines():
            parts = line.split("\t")
            if len(parts) == 3:
                fname = parts[2]
                owners.setdefault(fname, [])
                if ws.agent_name not in owners[fname]:
                    owners[fname].append(ws.agent_name)
    return owners


# ---------------------------------------------------------------------------
# cross_branch_log
# ---------------------------------------------------------------------------

def cross_branch_log(
    team_name: str, limit: int = 50, repo: str | None = None,
) -> list[dict]:
    """Unified commit log across all agent branches, newest first."""
    mgr = _ws_manager(team_name, repo)
    registry = _load_registry(team_name, str(mgr.repo_root))
    entries: list[dict] = []

    for ws in registry.workspaces:
        branch = ws.branch_name
        base = ws.base_branch
        try:
            log_raw = git._run(
                [
                    "log",
                    "--format=%H|%s|%aI",
                    "--name-only",
                    f"{base}..{branch}",
                ],
                cwd=mgr.repo_root,
                check=False,
            )
        except Exception:
            continue

        current: dict | None = None
        for line in log_raw.splitlines():
            if "|" in line and len(line.split("|")) >= 3:
                if current is not None:
                    entries.append(current)
                parts = line.split("|", 2)
                current = {
                    "agent": ws.agent_name,
                    "hash": parts[0],
                    "message": parts[1],
                    "timestamp": parts[2],
                    "files": [],
                }
            elif line.strip() and current is not None:
                current["files"].append(line.strip())
        if current is not None:
            entries.append(current)

    # Sort by timestamp descending, take limit
    entries.sort(key=lambda e: e["timestamp"], reverse=True)
    return entries[:limit]


# ---------------------------------------------------------------------------
# agent_summary
# ---------------------------------------------------------------------------

def agent_summary(team_name: str, agent_name: str, repo: str | None = None) -> str:
    """Human-readable summary of an agent's git activity."""
    diff = agent_diff(team_name, agent_name, repo)
    lines = [
        f"Agent: {agent_name}",
        f"Branch: {_agent_branch(team_name, agent_name)}",
        f"Commits: {diff['commit_count']}",
        f"Files changed: {len(diff['files_changed'])}",
        f"Insertions: +{diff['insertions']}  Deletions: -{diff['deletions']}",
    ]
    if diff["files_changed"]:
        lines.append("Modified files:")
        for f in diff["files_changed"]:
            lines.append(f"  - {f}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# inject_context
# ---------------------------------------------------------------------------

def inject_context(
    team_name: str, target_agent: str, repo: str | None = None,
) -> str:
    """Build a context block for injection into an agent's prompt.

    Includes:
    - Other agents' recent changes on files the target agent also touches
    - File overlap warnings
    - Upstream dependency diffs (if task has blocked_by)
    """
    # Files the target agent is modifying
    target_diff = agent_diff(team_name, target_agent, repo)
    target_files = set(target_diff["files_changed"])

    sections: list[str] = []

    # --- Section 1: Other agents' changes on overlapping files ---
    owners = file_owners(team_name, repo)
    overlaps: dict[str, list[str]] = {}
    for fname, agents in owners.items():
        if fname in target_files and len(agents) > 1:
            others = [a for a in agents if a != target_agent]
            if others:
                overlaps[fname] = others

    if overlaps:
        overlap_lines = ["## File Overlap Warnings"]
        for fname, agents in overlaps.items():
            overlap_lines.append(f"- `{fname}` also modified by: {', '.join(agents)}")
        sections.append("\n".join(overlap_lines))

    # --- Section 2: Recent changes from other agents on related files ---
    log = cross_branch_log(team_name, limit=20, repo=repo)
    related: list[str] = []
    for entry in log:
        if entry["agent"] == target_agent:
            continue
        common = target_files & set(entry["files"])
        if common:
            related.append(
                f"- [{entry['agent']}] {entry['hash'][:8]} {entry['message']} "
                f"(files: {', '.join(common)})"
            )
    if related:
        sections.append("## Recent Related Changes\n" + "\n".join(related))

    # --- Section 3: Upstream dependency diffs ---
    try:
        from clawteam.team.tasks import TaskStore

        store = TaskStore(team_name)
        tasks = store.list_tasks(owner=target_agent)
        dep_ids: set[str] = set()
        for t in tasks:
            dep_ids.update(t.blocked_by)

        if dep_ids:
            # Find which agents own those upstream tasks
            all_tasks = store.list_tasks()
            dep_agents: set[str] = set()
            for t in all_tasks:
                if t.id in dep_ids and t.owner and t.owner != target_agent:
                    dep_agents.add(t.owner)

            if dep_agents:
                dep_lines = ["## Upstream Dependency Changes"]
                for dep_agent in sorted(dep_agents):
                    dep_diff = agent_diff(team_name, dep_agent, repo)
                    dep_lines.append(
                        f"- {dep_agent}: {dep_diff['summary']}"
                    )
                sections.append("\n".join(dep_lines))
    except Exception:
        pass  # Tasks may not exist yet

    if not sections:
        return "No cross-agent context to inject — working in isolation."

    header = f"# Git Context for {target_agent}\n"
    return header + "\n\n".join(sections)
