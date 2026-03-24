---
name: clawteam
description: "Multi-agent swarm coordination via the ClawTeam CLI. Use when the user wants to create agent teams, spawn multiple agents to work in parallel, coordinate tasks with dependencies, broadcast messages between agents, monitor progress via kanban board, or launch pre-built team templates (hedge-fund, code-review, research-paper). ClawTeam uses git worktree isolation + tmux + filesystem-based messaging. Trigger phrases: team, swarm, multi-agent, clawteam, spawn agents, parallel agents, agent team."
---

# ClawTeam — Multi-Agent Swarm Coordination

## Overview

ClawTeam is a CLI tool (`clawteam`) for orchestrating multiple AI agents as self-organizing swarms. It uses git worktree isolation, tmux windows, and filesystem-based messaging. OpenClaw is the default agent backend.

**CLI binary**: `clawteam` (installed via pip, available in PATH)

## Quick Start

### One-Command Template Launch (Recommended)

```bash
# Launch a pre-built team from a template
clawteam launch hedge-fund --team fund1
clawteam launch code-review --team review1
clawteam launch research-paper --team paper1
```

### Manual Team Setup

```bash
# 1. Create team with leader
clawteam team spawn-team my-team -d "Build a web app" -n leader

# 2. Create tasks with dependencies
clawteam task create my-team "Design API schema" -o architect
# Returns task ID, e.g., abc123

clawteam task create my-team "Implement auth" -o backend --blocked-by abc123
clawteam task create my-team "Build frontend" -o frontend --blocked-by abc123
clawteam task create my-team "Write tests" -o tester

# 3. Spawn agents (each gets its own tmux window + git worktree)
clawteam spawn -t my-team -n architect --task "Design the API schema for a web app"
clawteam spawn -t my-team -n backend --task "Implement OAuth2 authentication"
clawteam spawn -t my-team -n frontend --task "Build React dashboard"

# 4. Monitor
clawteam board show my-team        # Kanban view
clawteam board attach my-team      # Tmux tiled view (all agents side-by-side)
clawteam board serve --port 8080   # Web dashboard
```

## Command Reference

### Team Management

| Command | Description |
|---------|-------------|
| `clawteam team spawn-team <name> -d "<desc>" -n <leader>` | Create team |
| `clawteam team discover` | List all teams |
| `clawteam team status <team>` | Show team members and info |
| `clawteam team cleanup <team> --force` | Delete team and all data |

### Task Management

| Command | Description |
|---------|-------------|
| `clawteam task create <team> "<subject>" -o <owner> [-d "<desc>"] [--blocked-by <id>]` | Create task |
| `clawteam task list <team> [--owner <name>]` | List tasks (filterable) |
| `clawteam task update <team> <id> --status <status>` | Update status |
| `clawteam task get <team> <id>` | Get single task |
| `clawteam task stats <team>` | Timing statistics |
| `clawteam task wait <team>` | Block until all tasks complete |

**Task statuses**: `pending`, `in_progress`, `completed`, `blocked`

**Dependency auto-resolution**: When a blocking task completes, dependent tasks automatically change from `blocked` to `pending`.

### Agent Spawning

**IMPORTANT**: Always use the default command (`openclaw`) — do NOT override to `claude` or other agents. The default handles permissions, prompt injection, and nesting detection correctly. If you specify `claude` as the command, agents will get stuck on interactive permission prompts.

```bash
# Default (RECOMMENDED): spawns openclaw tui in tmux with prompt
clawteam spawn -t <team> -n <name> --task "<task description>"

# Explicit backend (still uses openclaw by default)
clawteam spawn tmux -t <team> -n <name> --task "<task>"
clawteam spawn subprocess -t <team> -n <name> --task "<task>"

# With git worktree isolation
clawteam spawn -t <team> -n <name> --task "<task>" --workspace --repo /path/to/repo
```

Each spawned agent gets:
- Its own tmux window (visible via `board attach`)
- Its own git worktree branch (`clawteam/{team}/{agent}`)
- An auto-injected coordination prompt (how to use clawteam CLI)
- Environment variables: `CLAWTEAM_AGENT_NAME`, `CLAWTEAM_TEAM_NAME`, etc.

### Messaging

| Command | Description |
|---------|-------------|
| `clawteam inbox send <team> <to> "<msg>" --from <sender>` | Point-to-point message |
| `clawteam inbox broadcast <team> "<msg>" --from <sender>` | Broadcast to all |
| `clawteam inbox peek <team> -a <agent>` | Peek without consuming |
| `clawteam inbox receive <team>` | Consume messages |
| `clawteam inbox log <team>` | View message history |

### Monitoring

| Command | Description |
|---------|-------------|
| `clawteam board show <team>` | Kanban board (rich terminal) |
| `clawteam board overview` | All teams overview |
| `clawteam board live <team>` | Live-refreshing board |
| `clawteam board attach <team>` | Tmux tiled view |
| `clawteam board serve --port 8080` | Web dashboard |

### Cost Tracking

| Command | Description |
|---------|-------------|
| `clawteam cost report <team> --input-tokens <N> --output-tokens <N> --cost-cents <N>` | Report usage |
| `clawteam cost show <team>` | Show summary |
| `clawteam cost budget <team> <dollars>` | Set budget |

### Templates

| Command | Description |
|---------|-------------|
| `clawteam template list` | List available templates |
| `clawteam template show <name>` | Show template details |
| `clawteam launch <template> [--team-name <name>] [--goal "<goal>"]` | Launch from template |

**Built-in templates**: `hedge-fund`, `code-review`, `research-paper`

### Configuration

```bash
clawteam config show                           # Show all settings
clawteam config set transport file             # Set transport backend
clawteam config set skip_permissions true      # Auto-skip permission prompts
clawteam config health                         # System health check
```

### Other Commands

| Command | Description |
|---------|-------------|
| `clawteam lifecycle idle <team> --agent <name>` | Report agent idle |
| `clawteam session save <team> --session-id <id>` | Save session for resume |
| `clawteam plan submit <team> "<plan>" --from <agent>` | Submit plan for approval |
| `clawteam workspace list <team>` | List git worktrees |
| `clawteam workspace merge <team> --agent <name>` | Merge agent branch |

## JSON Output

Add `--json` before any subcommand for machine-readable output:

```bash
clawteam --json task list my-team
clawteam --json team status my-team
```

## Typical Workflow

1. **User says**: "Create a team to build a web app"
2. **You do**: `clawteam team spawn-team webapp -d "Build web app" -n leader`
3. **Create tasks**: Use `clawteam task create` with `--blocked-by` for dependencies
4. **Spawn agents**: Use `clawteam spawn` for each worker
5. **Monitor**: Use `clawteam board show` to check progress
6. **Communicate**: Use `clawteam inbox broadcast` for team-wide updates
7. **Cleanup**: `clawteam team cleanup webapp --force` when done

## Data Location

All state stored in `~/.clawteam/`:
- Teams: `~/.clawteam/teams/<team>/config.json`
- Tasks: `~/.clawteam/tasks/<team>/task-<id>.json`
- Messages: `~/.clawteam/teams/<team>/inboxes/<agent>/msg-*.json`
- Costs: `~/.clawteam/costs/<team>/`
