<h1 align="center"><img src="assets/icon.png" alt="" width="64" style="vertical-align: middle;">&nbsp; ClawTeam: Agent Swarm Intelligence</h1>

<p align="center">
  <strong>The Evolution of AI Agents 🚀: Solo 🤖 → Swarm 🦞🤖🤖🤖<br>
  ClawTeam: Let AI Agents Form Swarms, Think & Work Together, and Ship Faster</strong>
</p>

<p align="center">
  <a href="#-quick-start"><img src="https://img.shields.io/badge/Quick_Start-3_min-blue?style=for-the-badge" alt="Quick Start"></a>
  <a href="#-use-cases"><img src="https://img.shields.io/badge/Use_Cases-3_Demos-green?style=for-the-badge" alt="Use Cases"></a>
  <a href="#-features"><img src="https://img.shields.io/badge/Features-12+-purple?style=for-the-badge" alt="Features"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-yellow?style=for-the-badge" alt="License"></a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-≥3.10-blue?logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/typer-CLI-green" alt="Typer">
  <img src="https://img.shields.io/badge/agents-Claude_Code_%7C_Codex_%7C_Any_CLI-blueviolet" alt="Agents">
  <img src="https://img.shields.io/badge/transport-File_%7C_ZeroMQ_P2P-orange" alt="Transport">
  <a href="https://github.com/HKUDS/.github/blob/main/profile/README.md"><img src="https://img.shields.io/badge/Feishu-Group-E9DBFC?style=flat&logo=feishu&logoColor=white" alt="Feishu"></a>
  <a href="https://github.com/HKUDS/.github/blob/main/profile/README.md"><img src="https://img.shields.io/badge/WeChat-Group-C5EAB4?style=flat&logo=wechat&logoColor=white" alt="WeChat"></a>
</p>

**One Command Line: Set Your Goal** — agents spawn swarms, delegate tasks, and deliver results automatically. 

Full compatibility with [Claude Code](https://claude.ai/claude-code), [Codex](https://openai.com/codex), [OpenClaw](https://github.com/nicepkg/OpenClaw), [nanobot](https://github.com/AbanteAI/nanobot), [Cursor](https://cursor.com), and any CLI agent.&nbsp;&nbsp;[**中文文档**](README_CN.md)

<p align="center">
  <img src="assets/teaser.png" alt="ClawTeam - AI agents orchestrating themselves" width="800">
</p>

---

## ✨ ClawTeam's Key Features

<table align="center" width="100%">
<tr>
<td width="25%" align="center" style="vertical-align: top; padding: 15px;">

<h3>🔬 AI Research Automation</h3>

<div align="center">
  <img src="https://img.shields.io/badge/AutoResearch-FF6B6B?style=for-the-badge&logo=pytorch&logoColor=white" alt="AutoResearch" />
</div>

<img src="assets/scene-autoresearch.png" width="180">

<p align="center"><strong>Large-Scale Automated ML Experimentation</strong></p>

<p align="center"><strong>AI Model Training & Optimization</strong></p>

<p align="center"><strong>AI-Driven Hypothesis Generation & Validation</strong></p>

<p align="center"><strong>Self-Improving Model Architectures</strong></p>

</td>
<td width="25%" align="center" style="vertical-align: top; padding: 15px;">

<h3>🏗️ Agentic Engineering</h3>

<div align="center">
  <img src="https://img.shields.io/badge/Full--Stack_Dev-4ECDC4?style=for-the-badge&logo=git&logoColor=white" alt="Engineering" />
</div>

<img src="assets/scene-engineering.png" width="180">

<p align="center"><strong>Parallel Software Development</strong></p>

<p align="center">Agents split work into API, backend, frontend, tests — each on its own git branch, auto-merging on completion</p>

</td>
<td width="25%" align="center" style="vertical-align: top; padding: 15px;">

<h3>💰 AI Hedge Fund</h3>

<div align="center">
  <img src="https://img.shields.io/badge/Investment_Analysis-FFD93D?style=for-the-badge&logo=bitcoin&logoColor=black" alt="Hedge Fund" />
</div>

<img src="assets/scene-hedgefund.png" width="180">

<p align="center"><strong>Multi-Analyst Signal Fusion</strong></p>

<p align="center">7 analyst agents (value, growth, technical, fundamentals, sentiment) + risk manager converge on investment decisions</p>

</td>
<td width="25%" align="center" style="vertical-align: top; padding: 15px;">

<h3>🎪 Your Own Swarm</h3>

<div align="center">
  <img src="https://img.shields.io/badge/TOML_Templates-C77DFF?style=for-the-badge&logo=toml&logoColor=white" alt="Templates" />
</div>

<img src="assets/scene-template.png" width="180">

<p align="center"><strong>One-Command Team Launch</strong></p>

<p align="center">Define any team archetype as a TOML template — roles, tasks, prompts — and launch with <code>clawteam launch</code></p>

</td>
</tr>
</table>

---

https://github.com/user-attachments/assets/f6f0b220-9a5e-4d0a-a25d-f80753d3639b

*☝️ A leader Claude agent spawns 8 sub-agents across 8 H100 GPUs, assigns experiment directions, monitors progress, cross-pollinates findings, and redirects unproductive agents — fully autonomously.*

---

## 🤔 Why ClawTeam?

AI coding agents are powerful — but they work **alone**. When a task is too big for one agent, you're stuck manually splitting work, copy-pasting context, and merging results.

**What if agents could swarm?**

ClawTeam enables **Agent Swarm Intelligence** — agents that self-organize into teams, divide work, share discoveries, and converge on solutions. A leader agent can:

- 🚀 **Spawn sub-agents** — each in its own git worktree and tmux session
- 📋 **Assign tasks** — with dependency chains that auto-unblock
- 💬 **Send messages** — direct instructions to any sub-agent
- 📊 **Monitor progress** — check the kanban board, read results
- 🔄 **Redirect work** — kill unproductive agents, reassign with new directions

The human just provides the initial goal. **The swarm handles the rest.**

<p align="center">
  <img src="assets/comic-how-it-works.png" alt="How ClawTeam works - comic" width="700">
</p>

---

## 🎯 Swarm Intelligence in Action

<table>
<tr>
<td width="33%">

### 🦞 Agents Spawn Agents
The leader agent calls `clawteam spawn` to create workers. Each worker gets its own **git worktree**, **tmux window**, and **identity** — automatically.

```bash
# The leader agent runs:
clawteam spawn --team my-team \
  --agent-name worker1 \
  --task "Implement auth module"
```

</td>
<td width="33%">

### 🤖 Agents Talk to Agents
Workers check their inbox, update task status, and report results — all through CLI commands that are **auto-injected** into their prompt.

```bash
# A worker agent checks tasks:
clawteam task list my-team --owner me
# Then reports back:
clawteam inbox send my-team leader \
  "Auth done. All tests passing."
```

</td>
<td width="33%">

### 👀 You Just Watch
Monitor the swarm from a tiled tmux view or a Web UI. The leader handles coordination — you intervene only when you want to.

```bash
# Watch all agents simultaneously
clawteam board attach my-team
# Or open the web dashboard
clawteam board serve --port 8080
```

</td>
</tr>
</table>

| | ClawTeam | Other multi-agent frameworks |
|---|---------|----------------------------|
| 🎯 **Who uses it** | **The AI agents themselves** | Humans writing orchestration code |
| ⚡ **Setup** | `pip install` + one prompt to the leader | Docker, cloud APIs, YAML configs |
| 🏗️ **Infrastructure** | Just a filesystem and tmux | Redis, message queues, databases |
| 🤖 **Agent support** | Any CLI agent (Claude Code, Codex, OpenClaw, custom) | Framework-specific only |
| 🌳 **Isolation** | Git worktrees (real branches, real diffs) | Containers or virtual envs |
| 🧠 **Intelligence** | Swarm self-organizes via CLI commands | Hard-coded orchestration logic |

---

## 🎬 Use Cases

### 🔬 1. Autonomous ML Research — 8 Agents × 8 H100 GPUs

Based on [@karpathy's autoresearch](https://github.com/karpathy/autoresearch). The human tells a leader agent: *"Optimize this LLM training setup using 8 GPUs."* **The leader does everything else.**

<p align="center">
  <img src="assets/autoresearch-progress.png" alt="AutoResearch Progress" width="720">
  <br>
  <em>🏆 val_bpb: 1.044 → 0.977 (6.4% improvement) | 2430+ experiments | ~30 GPU-hours</em>
</p>

**What the leader agent did autonomously:**

```
Human prompt: "Use 8 GPUs to optimize train.py. Read program.md for instructions."

🦞 Leader agent's actions:
├── 📖 Read program.md, understand the experiment protocol
├── 🏗️ clawteam team spawn-team autoresearch
├── 🚀 Assigned each GPU a research direction:
│   ├── GPU 0: clawteam spawn --task "Explore model depth (DEPTH 10-16)"
│   ├── GPU 1: clawteam spawn --task "Explore model width (ASPECT_RATIO 80-128)"
│   ├── GPU 2: clawteam spawn --task "Tune learning rates and optimizer"
│   ├── GPU 3: clawteam spawn --task "Explore batch size and accumulation"
│   ├── GPU 4-7: clawteam spawn tmux codex --task "..."  (Codex agents)
│   └── 🌳 Each agent: own git worktree, own branch, isolated experiments
├── 🔄 Every 30 minutes, checked results:
│   ├── clawteam board show autoresearch
│   ├── Read each agent's results.tsv
│   ├── 🏆 Identified best findings (depth=12, batch=2^17, norm-before-RoPE)
│   └── 📡 Cross-pollinated: told new agents to start from the best config
├── 🔧 When agents finished, reassigned GPUs:
│   ├── Killed idle agents, cleaned worktrees
│   ├── Created new worktrees from the best commit
│   └── Spawned fresh agents with combined optimization directions
└── ✅ After 2430+ experiments: val_bpb 1.044 → 0.977
```

Full results: [novix-science/autoresearch](https://github.com/novix-science/autoresearch)

---

### 🏗️ 2. Agentic Software Engineering

You tell Claude Code: *"Build me a full-stack todo app."* Claude realizes this is a multi-module task and **self-organizes a team**:

```
Human prompt: "Build a full-stack todo app with auth, database, and React frontend."

🦞 Leader agent's actions:
├── 🏗️ clawteam team spawn-team webapp -d "Full-stack todo app"
├── 📋 Created tasks with dependency chains:
│   ├── T1: "Design REST API schema"          → architect
│   ├── T2: "Implement JWT auth" --blocked-by T1  → backend1
│   ├── T3: "Build database layer" --blocked-by T1 → backend2
│   ├── T4: "Build React frontend"             → frontend
│   └── T5: "Integration tests" --blocked-by T2,T3,T4 → tester
├── 🚀 Spawned 5 sub-agents (each in its own git worktree):
│   ├── clawteam spawn --agent-name architect --task "Design the API schema"
│   ├── clawteam spawn --agent-name backend1  --task "Implement JWT auth"
│   ├── clawteam spawn --agent-name backend2  --task "Build PostgreSQL models"
│   ├── clawteam spawn --agent-name frontend  --task "Build React UI"
│   └── clawteam spawn --agent-name tester    --task "Write pytest tests"
├── 🔗 Dependency auto-resolution:
│   ├── architect completes → backend1 and backend2 auto-unblock
│   ├── All backends complete → tester auto-unblocks
│   └── Each agent calls: clawteam task update <id> --status completed
├── 💬 Sub-agents coordinate via inbox:
│   ├── architect → backend1: "Here's the OpenAPI spec: ..."
│   ├── backend1 → tester: "Auth endpoints ready at /api/auth/*"
│   └── tester → leader: "All 47 tests passing ✅"
└── 🌳 Leader merges all worktrees into main branch
```

---

### 💰 3. AI Hedge Fund — One-Command Team Launch

A pre-built TOML template spawns a complete **7-agent** investment analysis team:

```bash
# One command launches everything:
clawteam launch hedge-fund --team fund1 --goal "Analyze AAPL, MSFT, NVDA for Q2 2026"
```

```
🦞 What happens automatically:
├── 📊 Portfolio Manager (leader) spawns and receives the goal
├── 🤖 5 Analyst agents spawn, each with a different strategy:
│   ├── 🎩 Buffett Analyst    → value investing (moat, ROE, DCF)
│   ├── 🚀 Growth Analyst     → disruption (TAM, network effects)
│   ├── 📈 Technical Analyst  → indicators (EMA, RSI, Bollinger)
│   ├── 📋 Fundamentals       → financial ratios (P/E, D/E, FCF)
│   └── 📰 Sentiment Analyst  → news + insider trading signals
├── 🛡️ Risk Manager spawns, waits for all analyst signals:
│   ├── clawteam inbox receive fund1 (collects all 5 signals)
│   ├── Consolidates + computes position limits
│   └── clawteam inbox send fund1 portfolio-manager "RISK REPORT: ..."
└── 💼 Portfolio Manager makes final buy/sell/hold decisions
```

Templates are TOML files — **create your own team archetypes** for any domain.

---

## 📦 Install

```bash
pip install clawteam

# Or from source
git clone https://github.com/HKUDS/ClawTeam.git
cd ClawTeam
pip install -e .

# Optional: P2P transport (ZeroMQ)
pip install -e ".[p2p]"
```

Requires **Python 3.10+**. Dependencies: `typer`, `pydantic`, `rich`.

---

## 🚀 Quick Start

### ⚡ Option 1: Let the Agent Drive (Recommended)

ClawTeam ships with a **Claude Code skill** that auto-activates. Just install and prompt:

```
"Build a web app. Use clawteam to split the work across multiple agents."
```

The agent will automatically create a team, spawn workers, assign tasks, and coordinate — using `clawteam` CLI commands under the hood.

### 🔧 Option 2: Drive It Manually

```bash
# 1. Create a team (you become the leader)
clawteam team spawn-team my-team -d "Build the auth module" -n leader

# 2. Spawn worker agents — each gets a git worktree, tmux window, and identity
clawteam spawn --team my-team --agent-name alice --task "Implement the OAuth2 flow"
clawteam spawn --team my-team --agent-name bob   --task "Write unit tests for auth"

# 3. Workers auto-receive a coordination prompt that teaches them to:
#    ✅ Check tasks:    clawteam task list my-team --owner alice
#    ✅ Update status:  clawteam task update my-team <id> --status completed
#    ✅ Message leader: clawteam inbox send my-team leader "Done!"
#    ✅ Report idle:    clawteam lifecycle idle my-team

# 4. Watch them work side-by-side
clawteam board attach my-team
```

### 🤖 Supported Agents

ClawTeam works with **any CLI agent** that can execute shell commands:

| Agent | Spawn Command | Status |
|-------|--------------|--------|
| [Claude Code](https://claude.ai/claude-code) | `clawteam spawn tmux claude --team ...` | ✅ Full support |
| [Codex](https://openai.com/codex) | `clawteam spawn tmux codex --team ...` | ✅ Full support |
| [OpenClaw](https://github.com/nicepkg/OpenClaw) | `clawteam spawn tmux openclaw --team ...` | ✅ Full support |
| [nanobot](https://github.com/AbanteAI/nanobot) | `clawteam spawn tmux nanobot --team ...` | ✅ Full support |
| [Cursor](https://cursor.com) | `clawteam spawn subprocess cursor --team ...` | 🔮 Experimental |
| Custom scripts | `clawteam spawn subprocess python --team ...` | ✅ Full support |

---

## ✨ Features

<table>
<tr>
<td width="50%">

### 🦞 Agent Self-Organization
- Leader agents spawn and manage worker agents
- **Auto-injected coordination prompt** — zero manual setup
- Workers self-report status, results, and idle state
- Works with any CLI agent: Claude Code, Codex, OpenClaw, custom

### 🌳 Workspace Isolation
- Each agent gets its own **git worktree** (separate branch)
- No merge conflicts between parallel agents
- Checkpoint, merge, and cleanup commands
- Branch naming: `clawteam/{team}/{agent}`

### 📋 Task Tracking with Dependencies
- Shared kanban: `pending` → `in_progress` → `completed` / `blocked`
- `--blocked-by` dependency chains — **auto-unblock on completion**
- `task wait` blocks until all tasks complete
- Filter by status, owner; JSON output for scripting

</td>
<td width="50%">

### 💬 Inter-Agent Messaging
- Point-to-point **inboxes** (send, receive, peek)
- **Broadcast** to all team members
- File-based (default) or ZeroMQ P2P transport with offline fallback
- Agents discover messages via `inbox receive`

### 📊 Monitoring & Dashboards
- `board show` — terminal kanban board
- `board live` — auto-refreshing dashboard
- `board attach` — **tiled tmux view** of all agents working
- `board serve` — **Web UI** with real-time updates

### 🎪 Team Templates
- **TOML files** define team archetypes (roles, tasks, prompts)
- One command launches a complete team: `clawteam launch <template>`
- Built-in: AI Hedge Fund (7 agents). Create your own.
- Variable substitution: `{goal}`, `{team_name}`, `{agent_name}`

</td>
</tr>
</table>

### 🔧 More

| Feature | Description |
|---------|-------------|
| 📝 **Plan Approval** | Agents submit plans for leader review before execution |
| 🔄 **Lifecycle Protocol** | Graceful shutdown request/approve/reject, idle notifications |
| 📊 **JSON Output** | `--json` flag on all commands — agents parse structured output |
| 🌐 **Cross-Machine** | Shared filesystem (NFS/SSHFS) or P2P transport for distributed teams |
| 👥 **Multi-User** | Namespace agents by user — multiple humans can share a team |
| ⚙️ **Configuration** | Persistent config: env var > config file > default priority |
| 🔌 **Claude Code Skill** | Auto-triggers when users ask about multi-agent coordination |

---

## 🤖 How Agents Use ClawTeam

When an agent is spawned via `clawteam spawn`, it receives an **auto-injected coordination prompt**:

```
## Coordination Protocol (auto-injected into every spawned agent)

- 📋 Check your tasks: clawteam task list <team> --owner <your-name>
- ▶️ Start a task:     clawteam task update <team> <id> --status in_progress
- ✅ Finish a task:    clawteam task update <team> <id> --status completed
- 💬 Message leader:   clawteam inbox send <team> leader "status update..."
- 💬 Message teammate: clawteam inbox send <team> <name> "info..."
- 📨 Check inbox:      clawteam inbox receive <team>
- 😴 Report idle:      clawteam lifecycle idle <team>
```

This means **any CLI agent** can participate in a ClawTeam team — it just needs to run shell commands. No custom SDK, no API integration, no framework lock-in.

---

## 📖 Command Reference

<details open>
<summary><h3>🔧 Core Commands</h3></summary>

```bash
# 🏗️ Team lifecycle
clawteam team spawn-team <team> -d "description" -n <leader>
clawteam team discover                    # List all teams
clawteam team status <team>               # Show members
clawteam team cleanup <team> --force      # Delete team

# 🚀 Spawn agents
clawteam spawn --team <team> --agent-name <name> --task "do this"
clawteam spawn tmux codex --team <team> --agent-name <name> --task "do this"

# 📋 Task management
clawteam task create <team> "subject" -o <owner> --blocked-by <id1>,<id2>
clawteam task update <team> <id> --status completed   # auto-unblocks dependents
clawteam task list <team> --status blocked --owner worker1
clawteam task wait <team> --timeout 300

# 💬 Messaging
clawteam inbox send <team> <to> "message"
clawteam inbox broadcast <team> "message"
clawteam inbox receive <team>             # consume messages
clawteam inbox peek <team>                # read without consuming

# 📊 Monitoring
clawteam board show <team>                # terminal kanban
clawteam board live <team> --interval 3   # auto-refresh
clawteam board attach <team>              # tiled tmux view
clawteam board serve --port 8080          # web UI
```

</details>

<details>
<summary><h3>🌳 Workspace, 📝 Plan, 🔄 Lifecycle, ⚙️ Config</h3></summary>

```bash
# 🌳 Workspace (git worktree management)
clawteam workspace list <team>
clawteam workspace checkpoint <team> <agent>    # auto-commit
clawteam workspace merge <team> <agent>         # merge back to main
clawteam workspace cleanup <team> <agent>       # remove worktree

# 📝 Plan approval
clawteam plan submit <team> <agent> "plan" --summary "TL;DR"
clawteam plan approve <team> <plan-id> <agent> --feedback "LGTM"
clawteam plan reject <team> <plan-id> <agent> --feedback "Revise X"

# 🔄 Lifecycle
clawteam lifecycle request-shutdown <team> <agent> --reason "done"
clawteam lifecycle approve-shutdown <team> <request-id> <agent>
clawteam lifecycle idle <team>

# 🎪 Templates
clawteam launch <template> --team <name> --goal "Build X"
clawteam template list

# ⚙️ Config
clawteam config show
clawteam config set transport p2p
clawteam config health
```

| Setting | Env Var | Default | Description |
|---------|---------|---------|-------------|
| `data_dir` | `CLAWTEAM_DATA_DIR` | `~/.clawteam` | Data directory |
| `transport` | `CLAWTEAM_TRANSPORT` | `file` | `file` or `p2p` |
| `workspace` | `CLAWTEAM_WORKSPACE` | `auto` | `auto` / `always` / `never` |
| `default_backend` | `CLAWTEAM_DEFAULT_BACKEND` | `tmux` | `tmux` or `subprocess` |
| `skip_permissions` | `CLAWTEAM_SKIP_PERMISSIONS` | `true` | Auto-approve agent tools |

</details>

---

## 🏗️ Architecture

```
  Human: "Optimize this LLM"
         │
         ▼
  ┌──────────────┐     clawteam spawn     ┌──────────────┐
  │ 🦞 Leader    │ ──────────────────────► │ 🤖 Worker    │
  │ (Claude Code)│ ──────┐                │ (Claude Code)│
  │              │       │                │ git worktree │
  │ Uses:        │       │                │ tmux window  │
  │ • spawn      │       │ clawteam spawn └──────────────┘
  │ • task create│       │
  │ • inbox send │       ▼                ┌──────────────┐
  │ • board show │ ──────────────────────► │ 🤖 Worker    │
  │ • task wait  │       │                │ (Codex)      │
  └──────────────┘       │                │ git worktree │
                         │                │ tmux window  │
                         │ clawteam spawn └──────────────┘
                         ▼
                   ┌──────────────┐
                   │ 🤖 Worker    │    Each worker uses:
                   │ (any CLI)    │    • task list (check work)
                   │ git worktree │    • task update (report done)
                   │ tmux window  │    • inbox send (message leader)
                   └──────────────┘    • inbox receive (get instructions)
                         │
                         ▼
              ┌─────────────────────┐
              │    ~/.clawteam/     │
              │ ├── teams/   (who) │
              │ ├── tasks/   (what)│
              │ ├── inboxes/ (talk)│
              │ └── workspaces/    │
              │     (isolated code)│
              └─────────────────────┘
```

All state lives in `~/.clawteam/` as JSON files. No database, no server, no cloud. Atomic `tmp + rename` writes ensure crash safety.

| Spawn Default | Value | Override |
|---------------|-------|----------|
| Backend | `tmux` | `clawteam spawn subprocess ...` |
| Command | `claude` | `clawteam spawn tmux codex ...` |
| Workspace | `auto` (git worktree) | `--no-workspace` |
| Permissions | skip | `--no-skip-permissions` |

| Transport | How it works | When to use |
|-----------|-------------|-------------|
| **file** (default) | JSON files in inbox dirs | Single machine, shared FS |
| **p2p** | ZeroMQ PUSH/PULL + file fallback | Low-latency, auto-fallback |

---

## 🗺️ Roadmap

| Phase | Version | What | Status |
|-------|---------|------|--------|
| **Current** | v0.3 | File + P2P (ZeroMQ) transport, Web UI, multi-user, team templates | ✅ Shipped |
| **Phase 1** | v0.4 | Redis Transport — cross-machine messaging | 🔜 Planned |
| **Phase 2** | v0.5 | Shared State Layer — team config and tasks across machines | 🔜 Planned |
| **Phase 3** | v0.6 | Agent Marketplace — discover and reuse community agent templates | 💡 Exploring |
| **Phase 4** | v0.7 | Adaptive Scheduling — dynamically reassign tasks based on agent performance | 💡 Exploring |
| **Phase 5** | v1.0 | Production-grade — auth, permissions, audit logs | 💡 Exploring |

---

## 🤝 Contributing

We welcome contributions! ClawTeam is designed to be extensible:

- 🤖 **New agent integrations** — Add support for more AI coding agents
- 🎪 **Team templates** — Create TOML templates for new domains (DevOps, data science, etc.)
- 🔌 **Transport backends** — Redis, NATS, or other message transports
- 📊 **Dashboard improvements** — Enhanced Web UI, Grafana integration
- 📖 **Documentation** — Tutorials, best practices, agent prompt engineering guides

---

## 📖 Acknowledgements

- [@karpathy/autoresearch](https://github.com/karpathy/autoresearch) — the autonomous ML research framework used in our 8-agent swarm demo
- [Claude Code](https://claude.ai/claude-code) and [Codex](https://openai.com/codex) — AI coding agents that work as ClawTeam team members
- [ai-hedge-fund](https://github.com/virattt/ai-hedge-fund) — inspiration for the multi-analyst hedge fund template
- [CLI-Anything](https://github.com/HKUDS/CLI-Anything) — sister project making all software agent-native

---

## ⭐ Star History

If ClawTeam helps your AI agents work in teams, give us a star! ⭐

<div align="center">
  <a href="https://star-history.com/#HKUDS/ClawTeam&Date">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=HKUDS/ClawTeam&type=Date&theme=dark" />
      <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/svg?repos=HKUDS/ClawTeam&type=Date" />
      <img alt="Star History Chart" src="https://api.star-history.com/svg?repos=HKUDS/ClawTeam&type=Date" />
    </picture>
  </a>
</div>

---

## 📄 License

MIT License — free to use, modify, and distribute.

---

<div align="center">

**ClawTeam** — *Agent Swarm Intelligence.* 🦞

<sub>8 agents × 8 H100s × 2430 experiments × one CLI × one swarm</sub>

<br>

<img src="assets/icon.png" alt="ClawTeam" width="80">

</div>

<p align="center">
  <em>Thanks for visiting ✨ ClawTeam!</em><br><br>
  <img src="https://visitor-badge.laobi.icu/badge?page_id=HKUDS.ClawTeam&style=for-the-badge&color=00d4ff" alt="Views">
</p>
