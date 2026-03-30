"""WorkspaceManager — creates / checkpoints / merges / cleans up git worktrees."""

from __future__ import annotations

import json
import logging
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

if sys.platform == "win32":
    import msvcrt
else:
    import fcntl

from clawteam.paths import ensure_within_root, validate_identifier
from clawteam.workspace import git
from clawteam.workspace.models import WorkspaceInfo, WorkspaceRegistry

logger = logging.getLogger(__name__)


def _workspaces_root() -> Path:
    from clawteam.team.models import get_data_dir
    p = get_data_dir() / "workspaces"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _registry_path(team_name: str) -> Path:
    return ensure_within_root(
        _workspaces_root(),
        validate_identifier(team_name, "team name"),
        "workspace-registry.json",
    )


def _registry_lock_path(team_name: str) -> Path:
    p = ensure_within_root(
        _workspaces_root(),
        validate_identifier(team_name, "team name"),
    )
    p.mkdir(parents=True, exist_ok=True)
    return p / ".registry.lock"


@contextmanager
def _registry_lock(team_name: str):
    """Acquire exclusive file lock on the workspace registry."""
    lock_path = _registry_lock_path(team_name)
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        if sys.platform == "win32":
            pos = lock_file.tell()
            lock_file.seek(0)
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
            lock_file.seek(pos)
        else:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if sys.platform == "win32":
                pos = lock_file.tell()
                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
                lock_file.seek(pos)
            else:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _load_registry(team_name: str, repo_root: str) -> WorkspaceRegistry:
    path = _registry_path(team_name)
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return WorkspaceRegistry.model_validate(data)
        except Exception:
            pass
    return WorkspaceRegistry(team_name=team_name, repo_root=repo_root)


def _save_registry(registry: WorkspaceRegistry) -> None:
    path = _registry_path(registry.team_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(registry.model_dump_json(indent=2), encoding="utf-8")
    tmp.replace(path)


class WorkspaceManager:
    """Manages git worktree-based isolated workspaces for agents."""

    def __init__(self, repo_path: Path | None = None):
        cwd = repo_path or Path.cwd()
        self.repo_root = git.repo_root(cwd)
        self.base_branch = git.default_remote_branch(self.repo_root)

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    def create_workspace(
        self,
        team_name: str,
        agent_name: str,
        agent_id: str,
    ) -> WorkspaceInfo:
        validate_identifier(team_name, "team name")
        validate_identifier(agent_name, "agent name")
        branch = f"clawteam/{team_name}/{agent_name}"
        wt_path = ensure_within_root(_workspaces_root(), team_name, agent_name)

        # Crash recovery: stale branch metadata can survive after the physical
        # worktree directory is deleted, so clear both path and branch state.
        if wt_path.exists():
            try:
                git.remove_worktree(self.repo_root, wt_path)
            except git.GitError:
                pass
        try:
            git.delete_branch(self.repo_root, branch)
        except git.GitError:
            pass

        git.create_worktree(
            self.repo_root, wt_path, branch, base_ref=self.base_branch,
        )

        info = WorkspaceInfo(
            agent_name=agent_name,
            agent_id=agent_id,
            team_name=team_name,
            branch_name=branch,
            worktree_path=str(wt_path),
            repo_root=str(self.repo_root),
            base_branch=self.base_branch,
            created_at=datetime.now(timezone.utc).isoformat(),
        )

        with _registry_lock(team_name):
            registry = _load_registry(team_name, str(self.repo_root))
            # Remove stale entry for the same agent, if any
            registry.workspaces = [
                w for w in registry.workspaces if w.agent_name != agent_name
            ]
            registry.workspaces.append(info)
            _save_registry(registry)

        return info

    # ------------------------------------------------------------------
    # Checkpoint
    # ------------------------------------------------------------------

    def checkpoint(
        self,
        team_name: str,
        agent_name: str,
        message: str | None = None,
    ) -> bool:
        info = self._find(team_name, agent_name)
        if info is None:
            return False
        ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        msg = message or f"[clawteam] checkpoint: {agent_name} @ {ts}"
        return git.commit_all(Path(info.worktree_path), msg)

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def cleanup_workspace(
        self,
        team_name: str,
        agent_name: str,
        auto_checkpoint: bool = True,
    ) -> bool:
        info = self._find(team_name, agent_name)
        if info is None:
            return False

        if auto_checkpoint:
            try:
                self.checkpoint(team_name, agent_name, f"[clawteam] final checkpoint: {agent_name}")
            except Exception:
                pass

        try:
            git.remove_worktree(self.repo_root, Path(info.worktree_path))
        except git.GitError as e:
            logger.warning("worktree remove failed: %s", e)
        try:
            git.delete_branch(self.repo_root, info.branch_name)
        except git.GitError as e:
            logger.warning("branch delete failed: %s", e)

        with _registry_lock(team_name):
            registry = _load_registry(team_name, str(self.repo_root))
            registry.workspaces = [
                w for w in registry.workspaces if w.agent_name != agent_name
            ]
            _save_registry(registry)
        return True

    def cleanup_team(self, team_name: str) -> int:
        """Clean up all workspaces for a team. Returns number cleaned."""
        registry = _load_registry(team_name, str(self.repo_root))
        count = 0
        for ws in list(registry.workspaces):
            if self.cleanup_workspace(team_name, ws.agent_name):
                count += 1
        return count

    # ------------------------------------------------------------------
    # Merge
    # ------------------------------------------------------------------

    def merge_workspace(
        self,
        team_name: str,
        agent_name: str,
        target_branch: str | None = None,
        cleanup_after: bool = True,
    ) -> tuple[bool, str]:
        info = self._find(team_name, agent_name)
        if info is None:
            return False, f"No workspace found for {agent_name}"

        # Checkpoint before merge
        self.checkpoint(team_name, agent_name, f"[clawteam] pre-merge checkpoint: {agent_name}")

        target = target_branch or info.base_branch
        success, output = git.merge_branch(
            self.repo_root, info.branch_name, target,
        )

        if success and cleanup_after:
            self.cleanup_workspace(team_name, agent_name, auto_checkpoint=False)

        return success, output

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def list_workspaces(self, team_name: str) -> list[WorkspaceInfo]:
        registry = _load_registry(team_name, str(self.repo_root))
        return registry.workspaces

    def get_workspace(self, team_name: str, agent_name: str) -> WorkspaceInfo | None:
        return self._find(team_name, agent_name)

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @staticmethod
    def try_create(repo_path: Path | None = None) -> WorkspaceManager | None:
        """Return a WorkspaceManager if inside a git repo, else None."""
        try:
            return WorkspaceManager(repo_path)
        except git.GitError:
            return None

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _find(self, team_name: str, agent_name: str) -> WorkspaceInfo | None:
        registry = _load_registry(team_name, str(self.repo_root))
        for ws in registry.workspaces:
            if ws.agent_name == agent_name:
                return ws
        return None
