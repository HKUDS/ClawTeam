"""Low-level git command wrappers — all subprocess calls centralized here."""

from __future__ import annotations

import subprocess
from pathlib import Path


class GitError(Exception):
    """Raised when a git command fails."""


def _run(args: list[str], cwd: Path | None = None, check: bool = True) -> str:
    """Run a git command and return stripped stdout."""
    result = subprocess.run(
        ["git"] + args,
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    if check and result.returncode != 0:
        raise GitError(f"git {' '.join(args)}: {result.stderr.strip()}")
    return result.stdout.strip()


def is_git_repo(path: Path) -> bool:
    """Check if *path* is inside a git repository."""
    try:
        _run(["rev-parse", "--git-dir"], cwd=path)
        return True
    except (GitError, FileNotFoundError):
        return False


def repo_root(path: Path) -> Path:
    """Return the repository root for *path*."""
    return Path(_run(["rev-parse", "--show-toplevel"], cwd=path))


def current_branch(repo: Path) -> str:
    """Return the current branch name (or HEAD for detached)."""
    try:
        return _run(["symbolic-ref", "--short", "HEAD"], cwd=repo)
    except GitError:
        return _run(["rev-parse", "--short", "HEAD"], cwd=repo)


def default_remote_branch(repo: Path) -> str:
    """Return the default remote branch (e.g. 'origin/master').

    Tries origin/HEAD first, then origin/master, then origin/main.
    Falls back to current_branch if no remote found.
    """
    for ref in ("origin/HEAD", "origin/master", "origin/main"):
        try:
            _run(["rev-parse", "--verify", ref], cwd=repo)
            return ref
        except GitError:
            continue
    return current_branch(repo)


def create_worktree(
    repo: Path,
    worktree_path: Path,
    branch: str,
    base_ref: str = "HEAD",
) -> None:
    """Create a new worktree with a new branch based on *base_ref*."""
    _run(
        ["worktree", "add", "-b", branch, str(worktree_path), base_ref],
        cwd=repo,
    )


def remove_worktree(repo: Path, worktree_path: Path) -> None:
    """Remove a worktree directory."""
    _run(["worktree", "remove", "--force", str(worktree_path)], cwd=repo)


def delete_branch(repo: Path, branch: str) -> None:
    """Force-delete a local branch."""
    _run(["branch", "-D", branch], cwd=repo)


def commit_all(worktree_path: Path, message: str) -> bool:
    """Stage everything and commit. Returns True if a commit was created."""
    _run(["add", "-A"], cwd=worktree_path)
    # Check if there is anything to commit
    result = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        cwd=worktree_path,
        capture_output=True,
    )
    if result.returncode == 0:
        return False  # nothing staged
    _run(["commit", "-m", message], cwd=worktree_path)
    return True


def merge_branch(
    repo: Path,
    branch: str,
    target: str,
    no_ff: bool = True,
) -> tuple[bool, str]:
    """Merge *branch* into *target*. Returns (success, output)."""
    _run(["checkout", target], cwd=repo)
    args = ["merge", "--no-verify"]
    if no_ff:
        args.append("--no-ff")
    args.append(branch)
    try:
        out = _run(args, cwd=repo)
        return True, out
    except GitError as e:
        # Abort on conflict
        subprocess.run(["git", "merge", "--abort"], cwd=repo, capture_output=True)
        return False, str(e)


def list_worktrees(repo: Path) -> list[dict[str, str]]:
    """Return list of worktrees as dicts with 'path' and 'branch' keys."""
    raw = _run(["worktree", "list", "--porcelain"], cwd=repo)
    worktrees: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for line in raw.splitlines():
        if line.startswith("worktree "):
            current = {"path": line.split(" ", 1)[1]}
        elif line.startswith("branch "):
            current["branch"] = line.split(" ", 1)[1].removeprefix("refs/heads/")
        elif line == "" and current:
            worktrees.append(current)
            current = {}
    if current:
        worktrees.append(current)
    return worktrees


def diff_stat(worktree_path: Path) -> str:
    """Return ``git diff --stat`` output for the worktree."""
    staged = _run(["diff", "--cached", "--stat"], cwd=worktree_path, check=False)
    unstaged = _run(["diff", "--stat"], cwd=worktree_path, check=False)
    parts = []
    if staged:
        parts.append(f"Staged:\n{staged}")
    if unstaged:
        parts.append(f"Unstaged:\n{unstaged}")
    return "\n".join(parts) if parts else "Clean — no changes."
