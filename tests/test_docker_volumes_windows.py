from __future__ import annotations

from clawteam.spawn.command_validation import (
    _split_volume_spec,
    _normalize_path,
    _volume_targets,
    ensure_docker_workspace,
    ensure_docker_mount,
)

def test_split_volume_spec():
    # Unix style
    assert _split_volume_spec("/tmp/demo:/tmp/demo") == ("/tmp/demo", "/tmp/demo")
    assert _split_volume_spec("/tmp/demo:/tmp/demo:ro") == ("/tmp/demo", "/tmp/demo")
    
    # Windows style
    assert _split_volume_spec("C:\\Users\\alice\\proj:C:\\Users\\alice\\proj") == ("C:\\Users\\alice\\proj", "C:\\Users\\alice\\proj")
    assert _split_volume_spec("C:\\Users\\alice\\proj:/workspace:ro") == ("C:\\Users\\alice\\proj", "/workspace")
    assert _split_volume_spec("c:/users/alice/proj:/workspace") == ("c:/users/alice/proj", "/workspace")


def test_normalize_path():
    assert _normalize_path("C:\\Users\\Alice\\Proj") == "/c/users/alice/proj"
    assert _normalize_path("c:/users/alice/proj/") == "/c/users/alice/proj"
    assert _normalize_path("/c/users/alice/proj") == "/c/users/alice/proj"
    assert _normalize_path("/tmp/demo") == "/tmp/demo"


def test_volume_targets():
    # Windows host and container paths
    spec1 = "C:\\Users\\alice\\proj:C:\\Users\\alice\\proj"
    assert _volume_targets(spec1, "C:\\Users\\alice\\proj", "C:\\Users\\alice\\proj") is True
    assert _volume_targets(spec1, "C:/Users/alice/proj", "C:/Users/alice/proj") is True
    assert _volume_targets(spec1, "/c/users/alice/proj", "/c/users/alice/proj") is True
    
    # Mixed Windows host, Unix container paths
    spec2 = "C:\\Users\\alice\\proj:/workspace:ro"
    assert _volume_targets(spec2, "C:\\Users\\alice\\proj", "/workspace") is True
    assert _volume_targets(spec2, "C:/Users/alice/proj", "/workspace") is True


def test_ensure_docker_workspace_idempotence():
    # Calling it twice with the same path should not duplicate the volume mounting
    cwd = "C:\\Users\\alice\\proj"
    cmd = ["docker", "run", "--rm", "hkuds/nanobot"]
    
    cmd_with_mounts = ensure_docker_workspace(cmd, cwd)
    # Check that volume mount is present with forward slashes
    assert "-v" in cmd_with_mounts
    assert "C:/Users/alice/proj:C:/Users/alice/proj" in cmd_with_mounts
    
    # Run ensure_docker_workspace again
    cmd_double_mount = ensure_docker_workspace(cmd_with_mounts, cwd)
    
    # Ensure there's only one "-v C:/Users/alice/proj:C:/Users/alice/proj"
    v_indices = [i for i, x in enumerate(cmd_double_mount) if x == "-v"]
    assert len(v_indices) == 1
