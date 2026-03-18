"""Conflict detection and overlap warnings for multi-agent git workspaces."""

from __future__ import annotations

from pathlib import Path

from clawteam.workspace import git
from clawteam.workspace.context import file_owners, _ws_manager, _agent_branch, _base_branch
from clawteam.workspace.manager import _load_registry


# ---------------------------------------------------------------------------
# detect_overlaps
# ---------------------------------------------------------------------------

def detect_overlaps(team_name: str, repo: str | None = None) -> list[dict]:
    """Detect files modified by multiple agents.

    Returns list of dicts with keys: file, agents, severity.
    Severity:
      - high: agents changed the same lines
      - medium: agents changed the same file (different lines)
      - low: agents changed files in the same directory
    """
    owners = file_owners(team_name, repo)
    mgr = _ws_manager(repo)
    registry = _load_registry(team_name, str(mgr.repo_root))

    overlaps: list[dict] = []
    for fname, agents in owners.items():
        if len(agents) < 2:
            continue

        # Determine severity by checking if changed lines overlap
        severity = _compute_severity(fname, agents, team_name, mgr)
        overlaps.append({
            "file": fname,
            "agents": agents,
            "severity": severity,
        })

    # Sort: high first
    order = {"high": 0, "medium": 1, "low": 2}
    overlaps.sort(key=lambda o: order.get(o["severity"], 3))
    return overlaps


def _changed_lines(
    fname: str, branch: str, base: str, repo_root: Path,
) -> set[int]:
    """Return set of line numbers changed by branch for a specific file."""
    try:
        diff_raw = git._run(
            ["diff", "-U0", f"{base}...{branch}", "--", fname],
            cwd=repo_root,
            check=False,
        )
    except Exception:
        return set()

    lines: set[int] = set()
    for line in diff_raw.splitlines():
        # Parse @@ -a,b +c,d @@ hunks
        if line.startswith("@@"):
            # Extract the +c,d portion (new-file lines)
            parts = line.split("+")
            if len(parts) >= 2:
                hunk = parts[1].split(" ")[0].split("@@")[0]
                if "," in hunk:
                    start, count = hunk.split(",", 1)
                    start = int(start)
                    count = int(count)
                else:
                    start = int(hunk)
                    count = 1
                lines.update(range(start, start + count))
    return lines


def _compute_severity(
    fname: str,
    agents: list[str],
    team_name: str,
    mgr,
) -> str:
    """Compute overlap severity for a file touched by multiple agents."""
    # Collect changed lines per agent
    agent_lines: dict[str, set[int]] = {}
    for agent_name in agents:
        ws = mgr.get_workspace(team_name, agent_name)
        if ws is None:
            continue
        branch = ws.branch_name
        base = ws.base_branch
        agent_lines[agent_name] = _changed_lines(
            fname, branch, base, mgr.repo_root,
        )

    # Check pairwise overlap
    agent_list = list(agent_lines.keys())
    for i in range(len(agent_list)):
        for j in range(i + 1, len(agent_list)):
            a_lines = agent_lines[agent_list[i]]
            b_lines = agent_lines[agent_list[j]]
            if a_lines & b_lines:
                return "high"

    return "medium"


# ---------------------------------------------------------------------------
# check_conflicts
# ---------------------------------------------------------------------------

def check_conflicts(
    team_name: str, agent_a: str, agent_b: str, repo: str | None = None,
) -> list[dict]:
    """Check for conflicts between two specific agents.

    Returns list of dicts with: file, conflict_markers (bool), details.
    """
    mgr = _ws_manager(repo)
    branch_a = _agent_branch(team_name, agent_a)
    branch_b = _agent_branch(team_name, agent_b)
    base_a = _base_branch(team_name, agent_a, mgr)

    # Find files changed by both
    try:
        files_a_raw = git._run(
            ["diff", "--name-only", f"{base_a}...{branch_a}"],
            cwd=mgr.repo_root, check=False,
        )
        files_a = set(files_a_raw.splitlines()) if files_a_raw else set()
    except Exception:
        files_a = set()

    base_b = _base_branch(team_name, agent_b, mgr)
    try:
        files_b_raw = git._run(
            ["diff", "--name-only", f"{base_b}...{branch_b}"],
            cwd=mgr.repo_root, check=False,
        )
        files_b = set(files_b_raw.splitlines()) if files_b_raw else set()
    except Exception:
        files_b = set()

    common_files = files_a & files_b
    if not common_files:
        return []

    results: list[dict] = []
    for fname in sorted(common_files):
        lines_a = _changed_lines(fname, branch_a, base_a, mgr.repo_root)
        lines_b = _changed_lines(fname, branch_b, base_b, mgr.repo_root)
        overlap = lines_a & lines_b
        results.append({
            "file": fname,
            "conflict_markers": bool(overlap),
            "details": (
                f"Lines {sorted(overlap)[:10]}{'...' if len(overlap) > 10 else ''} "
                f"changed by both agents"
                if overlap
                else f"Different lines modified (A: {len(lines_a)}, B: {len(lines_b)})"
            ),
        })

    return results


# ---------------------------------------------------------------------------
# auto_notify
# ---------------------------------------------------------------------------

def auto_notify(team_name: str, mailbox_mgr, repo: str | None = None) -> int:
    """Scan for overlaps and send warning messages to affected agents.

    Returns number of warnings sent.
    """
    overlaps = detect_overlaps(team_name, repo)
    if not overlaps:
        return 0

    count = 0
    for overlap in overlaps:
        if overlap["severity"] == "low":
            continue  # Only warn on medium/high
        agents = overlap["agents"]
        fname = overlap["file"]
        severity = overlap["severity"]
        for agent in agents:
            others = [a for a in agents if a != agent]
            content = (
                f"[context-warning] File overlap ({severity}): `{fname}` "
                f"is also being modified by {', '.join(others)}. "
                f"Consider coordinating to avoid merge conflicts."
            )
            try:
                mailbox_mgr.send(
                    from_agent="context-agent",
                    to=agent,
                    content=content,
                )
                count += 1
            except Exception:
                pass
    return count


# ---------------------------------------------------------------------------
# suggest_rebase
# ---------------------------------------------------------------------------

def suggest_rebase(
    team_name: str, agent_name: str, repo: str | None = None,
) -> str | None:
    """Suggest whether an agent should rebase onto the base branch.

    Returns a suggestion string, or None if no rebase is needed.
    """
    mgr = _ws_manager(repo)
    branch = _agent_branch(team_name, agent_name)
    base = _base_branch(team_name, agent_name, mgr)

    # Count how many commits are on base that aren't on the agent's branch
    try:
        behind_raw = git._run(
            ["rev-list", "--count", f"{branch}..{base}"],
            cwd=mgr.repo_root, check=False,
        )
        behind = int(behind_raw) if behind_raw.strip().isdigit() else 0
    except Exception:
        behind = 0

    if behind == 0:
        return None

    # Check for overlapping files with merged changes
    try:
        base_files_raw = git._run(
            ["diff", "--name-only", f"{branch}..{base}"],
            cwd=mgr.repo_root, check=False,
        )
        base_files = set(base_files_raw.splitlines()) if base_files_raw else set()
    except Exception:
        base_files = set()

    try:
        agent_files_raw = git._run(
            ["diff", "--name-only", f"{base}..{branch}"],
            cwd=mgr.repo_root, check=False,
        )
        agent_files = set(agent_files_raw.splitlines()) if agent_files_raw else set()
    except Exception:
        agent_files = set()

    overlapping = base_files & agent_files
    if overlapping:
        return (
            f"Rebase recommended: {agent_name}'s branch is {behind} commit(s) behind "
            f"'{base}', and {len(overlapping)} file(s) overlap with upstream changes: "
            f"{', '.join(sorted(overlapping)[:5])}{'...' if len(overlapping) > 5 else ''}. "
            f"Run: git rebase {base}"
        )
    elif behind > 5:
        return (
            f"Rebase suggested: {agent_name}'s branch is {behind} commit(s) behind "
            f"'{base}'. No file overlaps detected, but rebasing will keep the branch current. "
            f"Run: git rebase {base}"
        )

    return None
