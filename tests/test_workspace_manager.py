from __future__ import annotations

from pathlib import Path

from clawteam.workspace.manager import WorkspaceManager


def test_create_workspace_deletes_stale_branch_even_when_worktree_missing(monkeypatch, tmp_path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    worktree_root = tmp_path / "data"
    worktree_root.mkdir()

    deleted: list[str] = []
    created: list[tuple[Path, str, str]] = []

    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(worktree_root))
    monkeypatch.setattr("clawteam.workspace.git.repo_root", lambda path: repo_root)
    monkeypatch.setattr("clawteam.workspace.git.current_branch", lambda repo: "main")
    monkeypatch.setattr("clawteam.workspace.git.remove_worktree", lambda repo, path: None)
    monkeypatch.setattr(
        "clawteam.workspace.git.delete_branch",
        lambda repo, branch: deleted.append(branch),
    )
    monkeypatch.setattr(
        "clawteam.workspace.git.create_worktree",
        lambda repo, wt_path, branch, base_ref="HEAD": created.append((wt_path, branch, base_ref)),
    )

    manager = WorkspaceManager(repo_root)
    info = manager.create_workspace(team_name="demo", agent_name="alice", agent_id="agent-1")

    assert deleted == ["clawteam/demo/alice"]
    assert created == [(Path(info.worktree_path), "clawteam/demo/alice", "main")]


def test_cleanup_workspace_preserves_workspace_when_checkpoint_fails(monkeypatch, tmp_path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    data_root = tmp_path / "data"
    data_root.mkdir()

    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(data_root))
    monkeypatch.setattr("clawteam.workspace.git.repo_root", lambda path: repo_root)
    monkeypatch.setattr("clawteam.workspace.git.current_branch", lambda repo: "main")
    monkeypatch.setattr("clawteam.workspace.git.delete_branch", lambda repo, branch: None)
    monkeypatch.setattr(
        "clawteam.workspace.git.create_worktree",
        lambda repo, worktree_path, branch, base_ref="HEAD": None,
    )

    manager = WorkspaceManager(repo_root)
    manager.create_workspace(team_name="demo", agent_name="alice", agent_id="agent-1")

    def fail_checkpoint(*args, **kwargs):
        raise RuntimeError("simulated commit hook rejection")

    removed_worktrees = []
    deleted_branches = []
    monkeypatch.setattr(manager, "checkpoint", fail_checkpoint)
    monkeypatch.setattr(
        "clawteam.workspace.git.remove_worktree",
        lambda repo, worktree_path: removed_worktrees.append(worktree_path),
    )
    monkeypatch.setattr(
        "clawteam.workspace.git.delete_branch",
        lambda repo, branch: deleted_branches.append(branch),
    )

    cleaned = manager.cleanup_workspace("demo", "alice")

    assert cleaned is False
    assert removed_worktrees == []
    assert deleted_branches == []
    assert manager.get_workspace("demo", "alice") is not None
