
import pytest
from unittest.mock import MagicMock, patch
from clawteam.workspace.conflicts import detect_overlaps, _changed_lines, _compute_severity

@pytest.fixture
def mock_git():
    with patch("clawteam.workspace.git._run") as mock:
        yield mock

def test_changed_lines_parsing(mock_git):
    # Mock diff output with hunk headers
    mock_git.return_value = """@@ -10,2 +10,3 @@
 line1
+line2
+line3
+line4
@@ -20,1 +23,1 @@
-old
+new
"""
    from pathlib import Path
    lines = _changed_lines("file.txt", "branch", "base", Path("/tmp/repo"))
    
    # +10,3 -> lines 10, 11, 12
    # +23,1 -> line 23
    assert lines == {10, 11, 12, 23}

def test_changed_lines_single_line_hunk(mock_git):
    mock_git.return_value = "@@ -5 +5 @@\n+added"
    from pathlib import Path
    lines = _changed_lines("file.txt", "branch", "base", Path("/tmp/repo"))
    assert lines == {5}

@patch("clawteam.workspace.conflicts.file_owners")
@patch("clawteam.workspace.conflicts._ws_manager")
@patch("clawteam.workspace.conflicts._compute_severity")
def test_detect_overlaps_basic(mock_severity, mock_mgr, mock_owners):
    mock_owners.return_value = {
        "file1.txt": ["alice", "bob"],
        "file2.txt": ["alice"],
    }
    mock_severity.return_value = "high"
    
    overlaps = detect_overlaps("test-team")
    
    assert len(overlaps) == 1
    assert overlaps[0]["file"] == "file1.txt"
    assert overlaps[0]["agents"] == ["alice", "bob"]
    assert overlaps[0]["severity"] == "high"

@patch("clawteam.workspace.conflicts._changed_lines")
def test_compute_severity_high(mock_changed_lines):
    # Overlapping lines
    mock_changed_lines.side_effect = [
        {10, 11, 12}, # alice
        {12, 13, 14}, # bob
    ]
    
    mgr = MagicMock()
    mgr.repo_root = "/tmp/repo"
    ws_alice = MagicMock(branch_name="br-alice", base_branch="main")
    ws_bob = MagicMock(branch_name="br-bob", base_branch="main")
    mgr.get_workspace.side_effect = [ws_alice, ws_bob]
    
    severity = _compute_severity("file.txt", ["alice", "bob"], "team", mgr)
    assert severity == "high"

@patch("clawteam.workspace.conflicts._changed_lines")
def test_compute_severity_medium(mock_changed_lines):
    # No overlapping lines
    mock_changed_lines.side_effect = [
        {10, 11, 12}, # alice
        {20, 21, 22}, # bob
    ]
    
    mgr = MagicMock()
    mgr.repo_root = "/tmp/repo"
    ws_alice = MagicMock(branch_name="br-alice", base_branch="main")
    ws_bob = MagicMock(branch_name="br-bob", base_branch="main")
    mgr.get_workspace.side_effect = [ws_alice, ws_bob]
    
    severity = _compute_severity("file.txt", ["alice", "bob"], "team", mgr)
    assert severity == "medium"
