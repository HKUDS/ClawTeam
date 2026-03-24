# ClawTeam on Windows — Local Runbook

This repo has been patched locally to run natively on Windows without requiring WSL for the core coordination path.

## Current Status

Working on this machine:
- native Windows Python install
- team creation and status
- task create/list/update and dependency unblocking
- inbox send/peek/receive
- cost budget/report/show
- session save/show
- team snapshot + snapshot listing + dry-run restore
- git worktree workspace create/list/status/checkpoint/merge/cleanup
- agent spawning through the `windows` backend (Windows-friendly subprocess mode)

Notes:
- `windows` backend is an alias of the subprocess backend
- default backend is set locally to `windows`
- tmux is not required for the Windows path
- visual tmux pane orchestration is still a Unix/Linux-oriented feature

## Install / Reinstall

From this repo root:

```powershell
python -m pip install -e .
```

If the `clawteam` executable is not on PATH, use:

```powershell
python -m clawteam --help
```

## Config

Show current config:

```powershell
python -m clawteam config show
```

Set backend explicitly:

```powershell
python -m clawteam config set default_backend windows
```

## Quick Smoke Test

```powershell
python -m clawteam team spawn-team demo-win -d "Windows demo" -n leader
python -m clawteam task create demo-win "first task" -o leader
python -m clawteam inbox send demo-win leader "hello from windows"
python -m clawteam inbox receive demo-win --agent leader
python -m clawteam board show demo-win
```

## Spawn Agents on Windows

Recommended style:

```powershell
python -m clawteam spawn --team demo-win --agent-name worker1 --task "Do the task" windows python
```

Or rely on configured default backend:

```powershell
python -m clawteam spawn --team demo-win --agent-name worker1 --task "Do the task" python
```

## Workspace Flow

Create a spawned worker with git worktree isolation:

```powershell
python -m clawteam spawn --team demo-win --agent-name gitworker --task "Inspect repo" windows python
python -m clawteam workspace list demo-win
python -m clawteam workspace status demo-win gitworker
python -m clawteam workspace checkpoint demo-win gitworker -m "checkpoint"
python -m clawteam workspace merge demo-win gitworker --no-cleanup
python -m clawteam workspace cleanup demo-win --agent gitworker
```

## Validated Commands

These were manually validated on this machine:
- `team spawn-team`
- `team status`
- `team snapshot`
- `team snapshots`
- `team restore --dry-run`
- `task create`
- `task update`
- `task list`
- `inbox send`
- `inbox peek`
- `inbox receive`
- `cost budget`
- `cost report`
- `cost show`
- `session save`
- `session show`
- `workspace list`
- `workspace status`
- `workspace checkpoint`
- `workspace merge`
- `workspace cleanup`
- `spawn` using `windows` backend

## Known Caveats

1. This is a **local compatibility patch**, not upstreamed yet.
2. The Unix/tmux experience is still a separate path; Windows mode uses subprocess execution.
3. CLI argument parsing can be fussy when passing commands that start with dashes. If needed, place options before the backend/command, or use `--` carefully.
4. If you want a stable command experience, prefer invoking via `python -m clawteam`.

## Recommended Usage on This Machine

- Use OpenClaw/webchat as the control surface
- Run ClawTeam via the patched local repo
- Prefer subprocess/windows backend
- Use git worktree flows for isolated worker changes

## Convenience Scripts

Included in `scripts/`:

- `clawteam-win.ps1` — wrapper for `python -m clawteam`
- `smoke-test-win.ps1` — quick Windows smoke test
- `spawn-worker-win.ps1` — helper to spawn a Windows worker
- `board-serve-win.ps1` — start the web board on a chosen host/port
- `session-save-win.ps1` — save session metadata quickly
- `session-show-win.ps1` — show session metadata for a team
- `soak-test-win.ps1` — repeated task/inbox/session/cost loop for Windows soak testing

Examples:

```powershell
./scripts/clawteam-win.ps1 config show
./scripts/smoke-test-win.ps1
./scripts/spawn-worker-win.ps1 -Team demo-win -AgentName worker1 -Task "Do the task"
./scripts/board-serve-win.ps1 -Team demo-win -Port 8080
./scripts/session-save-win.ps1 -Team demo-win -Agent leader -SessionId sess-001
./scripts/session-show-win.ps1 -Team demo-win
./scripts/soak-test-win.ps1 -Team soak-win -Iterations 10
```

## Publishing Note

This runbook is intentionally generic and contains no user-specific remotes, usernames, or local secrets.

## Suggested Next Step

Run the smoke test, then start using the wrapper scripts for normal operation.
