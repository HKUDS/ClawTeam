# ClawTeam for Windows

This repository has been locally hardened to support native Windows use without relying on WSL for the core coordination path.

## What works

- Native Windows Python install
- Team creation, board display, inbox flow, task flow
- Cost/session persistence
- Team snapshots and dry-run restores
- Git worktree workspace flows
- Background agent spawning through the `windows` backend
- Web dashboard via `clawteam board serve`

## What is different from Linux

The original project is tmux-first. On Windows:

- `tmux` pane tiling/attach is not available natively
- the recommended runtime is the `windows` backend, which maps to subprocess spawning
- the Web board is the preferred live monitoring view

## Recommended commands

```powershell
python -m pip install -e .
python -m clawteam config set default_backend windows
python -m clawteam team spawn-team demo-win -d "Windows demo" -n leader
python -m clawteam board serve demo-win --port 8080
python -m clawteam spawn --team demo-win --agent-name worker1 --task "Do work" windows python
```

## Helper scripts

See `scripts/`:

- `clawteam-win.ps1`
- `smoke-test-win.ps1`
- `spawn-worker-win.ps1`

## Validation status

Validated locally on Windows across config, mailbox, snapshots, spawn CLI, registry, workspace, session, cost, and web board flows.

## Notes

This is a Windows-compatibility path, not yet official upstream Windows support. For your system, this is the intended production path.
