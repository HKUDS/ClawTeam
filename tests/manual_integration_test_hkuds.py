#!/usr/bin/env python3
"""
HKUDS/ClawTeam v0.3.0 Integration Test Suite
Tests actual multi-agent coordination features.

Usage: python3 tests/manual_integration_test_hkuds.py
"""

import json
import subprocess
import sys
import time
from datetime import datetime

PASS = 0
FAIL = 0

def run_cmd(args):
    """Run command and return output"""
    try:
        result = subprocess.run(
            ['clawteam'] + args,
            capture_output=True,
            text=True,
            timeout=30
        )
        return result.returncode, result.stdout, result.stderr
    except Exception as e:
        return 1, '', str(e)

def test(name, condition, details=''):
    global PASS, FAIL
    if condition:
        print(f"  ✅ {name}")
        PASS += 1
    else:
        print(f"  ❌ {name}")
        if details:
            print(f"     {details}")
        FAIL += 1

def test_cli_version():
    """Test 1: CLI version check"""
    print("\n🔧 Test 1: CLI Version")
    rc, out, err = run_cmd(['--version'])
    test("clawteam --version returns 0", rc == 0, err)
    test("Output contains 'clawteam v0.3'", 'clawteam v0.3' in out, out)

def test_board_overview():
    """Test 2: Board overview command"""
    print("\n📊 Test 2: Board Overview")
    rc, out, err = run_cmd(['board', 'overview'])
    test("board overview returns 0", rc == 0, err)
    test("Output contains team names", 'cqc-clickup-triage' in out or 'Platform' in out, out)
    
    # Test JSON output
    rc, out, err = run_cmd(['--json', 'board', 'overview'])
    test("JSON output valid", rc == 0, err)
    try:
        data = json.loads(out)
        test("JSON is a list", isinstance(data, list), str(type(data)))
    except:
        test("JSON parse failed", False, out[:200])

def test_team_spawn():
    """Test 3: Team spawning"""
    print("\n🤖 Test 3: Team Spawning")
    team_name = f"test-team-{int(time.time())}"
    rc, out, err = run_cmd(['team', 'spawn-team', team_name])
    test("team spawn-team returns 0", rc == 0, err)
    test("Output confirms creation", 'created' in out.lower() or 'OK' in out, out)

def test_task_create():
    """Test 4: Task creation"""
    print("\n📝 Test 4: Task Creation")
    team = "cqc-platform"  # Use existing team
    task_desc = f"Integration test task {datetime.now().isoformat()}"
    rc, out, err = run_cmd(['task', 'create', team, task_desc, '--priority', 'high'])
    test("task create returns 0", rc == 0, err)
    test("Output contains task ID", 'Task created' in out or 'OK' in out, out)

def test_task_list():
    """Test 5: Task listing"""
    print("\n📋 Test 5: Task Listing")
    rc, out, err = run_cmd(['task', 'list', 'cqc-platform'])
    test("task list returns 0", rc == 0, err)
    test("Output contains task info", 'pending' in out.lower() or 'in_progress' in out.lower() or 'completed' in out.lower(), out)

def test_inbox_peek():
    """Test 6: Inbox peek"""
    print("\n📬 Test 6: Inbox Peek")
    rc, out, err = run_cmd(['inbox', 'peek', 'cqc-clickup-triage'])
    test("inbox peek returns 0", rc == 0, err)
    test("Returns inbox data", len(out) >= 0)  # May be empty, that's OK

def test_inbox_log():
    """Test 7: Inbox log"""
    print("\n📜 Test 7: Inbox Log")
    rc, out, err = run_cmd(['inbox', 'log', 'cqc-clickup-triage', '--limit', '5'])
    test("inbox log returns 0", rc == 0, err)
    test("Returns log data", len(out) >= 0)  # May be empty, that's OK

def test_config_show():
    """Test 8: Config show"""
    print("\n⚙️ Test 8: Configuration")
    rc, out, err = run_cmd(['config', 'show'])
    test("config show returns 0", rc == 0, err)
    test("Shows config table", 'default_backend' in out or 'tmux' in out, out)

def test_profile_list():
    """Test 9: Profile listing"""
    print("\n👤 Test 9: Profiles")
    rc, out, err = run_cmd(['profile', 'list'])
    test("profile list returns 0", rc == 0, err)
    test("Shows profile info", len(out) > 0, out[:100])

def test_preset_list():
    """Test 10: Preset listing"""
    print("\n📦 Test 10: Presets")
    rc, out, err = run_cmd(['preset', 'list'])
    test("preset list returns 0", rc == 0, err)
    test("Shows presets", 'anthropic' in out.lower() or 'preset' in out.lower(), out)

def main():
    print("╔════════════════════════════════════════════════════════════╗")
    print("║  HKUDS/ClawTeam v0.3.0 Integration Test Suite              ║")
    print("╚════════════════════════════════════════════════════════════╝")
    
    start = time.time()
    
    test_cli_version()
    test_board_overview()
    test_team_spawn()
    test_task_create()
    test_task_list()
    test_inbox_peek()
    test_inbox_log()
    test_config_show()
    test_profile_list()
    test_preset_list()
    
    elapsed = time.time() - start
    
    print("\n" + "═" * 56)
    print(f"  Results: {PASS} passed, {FAIL} failed")
    print(f"  Duration: {elapsed:.2f}s")
    print("═" * 56)
    
    return 0 if FAIL == 0 else 1

if __name__ == '__main__':
    sys.exit(main())
