# ClawTeam CLI Complete Reference

## Global Options

```
clawteam [--version] [--json] [--data-dir PATH] <command>
```

- `--json` — Output JSON instead of human-readable text. Apply before subcommand: `clawteam --json team discover`
- `--data-dir PATH` — Override data directory (default: `~/.clawteam`)

## Environment Variables

ClawTeam agents use these environment variables for identity:

| Variable | Description | Example |
|----------|-------------|---------|
| `CLAWTEAM_AGENT_ID` | Unique agent identifier | `a1b2c3d4e5f6` |
| `CLAWTEAM_AGENT_NAME` | Human-readable agent name | `alice` |
| `CLAWTEAM_AGENT_TYPE` | Agent role type | `leader`, `general-purpose`, `researcher` |
| `CLAWTEAM_TEAM_NAME` | Team the agent belongs to | `dev-team` |
| `CLAWTEAM_DATA_DIR` | Override data directory | `/tmp/clawteam-data` |

When spawning agents via `clawteam spawn`, these are set automatically.

---

## Team Commands (`clawteam team`)

### `team spawn-team`

Create a new team and register the leader.

```bash
clawteam team spawn-team <name> [options]
```

| Option | Description | Default |
|--------|-------------|---------|
| `--description, -d` | Team description | `""` |
| `--agent-name, -n` | Leader agent name | `"leader"` |
| `--agent-type` | Leader agent type | `"leader"` |

Example:
```bash
clawteam team spawn-team dev-team -d "Backend development team" -n alice
```

### `team discover`

List all existing teams.

```bash
clawteam team discover
clawteam --json team discover
```

Returns: name, description, leadAgentId, memberCount for each team.

### `team status`

Show team configuration and member list.

```bash
clawteam team status <team>
```

### `team request-join`

Request to join a team. Blocks until leader approves/rejects or timeout.

```bash
clawteam team request-join <team> <proposed-name> [options]
```

| Option | Description | Default |
|--------|-------------|---------|
| `--capabilities, -c` | Agent capabilities description | `""` |
| `--timeout, -t` | Timeout in seconds | `60` |

### `team approve-join`

Approve a pending join request (leader only).

```bash
clawteam team approve-join <team> <request-id> [--assigned-name NAME]
```

### `team reject-join`

Reject a pending join request (leader only).

```bash
clawteam team reject-join <team> <request-id> [--reason TEXT]
```

### `team cleanup`

Delete a team and all its data (config, inboxes, tasks).

```bash
clawteam team cleanup <team> [--force]
```

---

## Inbox Commands (`clawteam inbox`)

### `inbox send`

Send a point-to-point message to an agent.

```bash
clawteam inbox send <team> <to> <content> [options]
```

| Option | Description | Default |
|--------|-------------|---------|
| `--key, -k` | Routing key | `None` |
| `--type` | Message type | `"message"` |

### `inbox broadcast`

Broadcast a message to all team members (except sender).

```bash
clawteam inbox broadcast <team> <content> [options]
```

### `inbox receive`

Receive and consume messages from inbox (destructive — messages are deleted).

```bash
clawteam inbox receive <team> [options]
```

| Option | Description | Default |
|--------|-------------|---------|
| `--agent, -a` | Agent name (default: from env) | env |
| `--limit, -l` | Max messages to receive | `10` |

### `inbox peek`

Peek at messages without consuming them (non-destructive).

```bash
clawteam inbox peek <team> [--agent NAME]
```

### `inbox watch`

Watch inbox for new messages in real-time (blocking, Ctrl+C to stop).

```bash
clawteam inbox watch <team> [--agent NAME] [--poll-interval 1.0]
```

---

## Task Commands (`clawteam task`)

### `task create`

Create a new task.

```bash
clawteam task create <team> <subject> [options]
```

| Option | Description | Default |
|--------|-------------|---------|
| `--description, -d` | Task description | `""` |
| `--owner, -o` | Owner agent name | `""` |
| `--priority, -p` | Task priority: `low`, `medium`, `high`, `urgent` | `"medium"` |
| `--blocks` | Comma-separated task IDs this blocks | `None` |
| `--blocked-by` | Comma-separated task IDs blocking this | `None` |

Example:
```bash
clawteam task create dev-team "Implement auth" -o alice -d "Add JWT authentication"
```

### `task get`

Get a single task by ID.

```bash
clawteam task get <team> <task-id>
```

### `task update`

Update a task's status, owner, or dependencies.

```bash
clawteam task update <team> <task-id> [options]
```

| Option | Description |
|--------|-------------|
| `--status, -s` | New status: `pending`, `in_progress`, `review`, `completed`, `blocked` |
| `--owner, -o` | New owner |
| `--subject` | New subject |
| `--description, -d` | New description |
| `--priority, -p` | New priority: `low`, `medium`, `high`, `urgent` |
| `--add-blocks` | Comma-separated task IDs to add to blocks |
| `--add-blocked-by` | Comma-separated task IDs to add to blocked-by |
| `--force, -f` | Force override task lock |

When a task is marked `completed`, any tasks blocked by it are automatically unblocked (moved from `blocked` to `pending` if no other blockers remain).

### `task list`

List all tasks for a team, with optional filters.

```bash
clawteam task list <team> [--status STATUS] [--owner NAME] [--priority LEVEL] [--sort-priority]
```

---

## Board Commands (`clawteam board`)

### `board show`

Show detailed team board data. Human output renders the kanban board; JSON output also includes
members with inbox identity fields plus persistent message history from the event log.

```bash
clawteam board show <team>
clawteam --json board show <team>
```

Recent board payloads include member-aware message aliases such as `memberKey`, `inboxName`,
`fromLabel`, and `toLabel`, which are used by the browser board to filter inbox history.

### `board overview`

Show summary of all teams in a table.

```bash
clawteam board overview
clawteam --json board overview
```

### `board live`

Live-refreshing kanban board. Auto-refreshes at interval. Ctrl+C to stop.

```bash
clawteam board live <team> [--interval 2.0]
```

---

## Plan Commands (`clawteam plan`)

### `plan submit`

Submit a plan for leader approval. Content can be inline text or a file path.

```bash
clawteam plan submit <team> <agent> <plan-content-or-file> [--summary TEXT]
```

### `plan approve`

Approve a submitted plan.

```bash
clawteam plan approve <team> <plan-id> <agent> [--feedback TEXT]
```

### `plan reject`

Reject a submitted plan.

```bash
clawteam plan reject <team> <plan-id> <agent> [--feedback TEXT]
```

---

## Lifecycle Commands (`clawteam lifecycle`)

### `lifecycle request-shutdown`

Request an agent to shut down.

```bash
clawteam lifecycle request-shutdown <team> <from-agent> <to-agent> [--reason TEXT]
```

### `lifecycle approve-shutdown`

Agent agrees to shut down.

```bash
clawteam lifecycle approve-shutdown <team> <request-id> <agent>
```

### `lifecycle reject-shutdown`

Agent rejects shutdown request.

```bash
clawteam lifecycle reject-shutdown <team> <request-id> <agent> [--reason TEXT]
```

### `lifecycle idle`

Send idle notification to leader (agent has no more work).

```bash
clawteam lifecycle idle <team> [--last-task ID] [--task-status STATUS]
```

---

## Spawn Command

Spawn a new agent process with team environment variables.

```bash
clawteam spawn <backend> <command...> [options]
```

| Option | Description | Default |
|--------|-------------|---------|
| `--team, -t` | Team name | `"default"` |
| `--agent-name, -n` | Agent name | auto-generated |
| `--agent-type` | Agent type | `"general-purpose"` |

Backends: `subprocess`, `tmux`

Example:
```bash
clawteam spawn subprocess claude --team dev-team --agent-name bob --agent-type researcher
```

---

## Identity Commands (`clawteam identity`)

### `identity show`

Show current agent identity from environment variables.

```bash
clawteam identity show
```

### `identity set`

Print shell export commands to set identity environment variables.

```bash
eval $(clawteam identity set --agent-name alice --team dev-team)
```

---

## Data Model

### Task Statuses

| Status | Description |
|--------|-------------|
| `pending` | Not yet started |
| `in_progress` | Currently being worked on |
| `review` | Submitted for review |
| `completed` | Done (auto-unblocks dependents) |
| `blocked` | Waiting on other tasks |

### Message Types

| Type | Description |
|------|-------------|
| `message` | General point-to-point message |
| `broadcast` | Broadcast to all members |
| `join_request` | Request to join team |
| `join_approved` / `join_rejected` | Join response |
| `plan_approval_request` | Plan submitted for review |
| `plan_approved` / `plan_rejected` | Plan response |
| `shutdown_request` | Shutdown request |
| `shutdown_approved` / `shutdown_rejected` | Shutdown response |
| `idle` | Agent idle notification |

### File Storage Layout

```
~/.clawteam/
├── teams/{team}/
│   ├── config.json          # TeamConfig (name, members, leader)
│   └── inboxes/{agent}/     # msg-{timestamp}-{uuid}.json files
├── tasks/{team}/
│   └── task-{id}.json       # Individual task files
└── plans/
    └── {agent}-{id}.md      # Plan documents
```
