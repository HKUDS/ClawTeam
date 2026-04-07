<h1 align="center"><img src="assets/icon.png" alt="" width="64" style="vertical-align: middle;">&nbsp; ClawTeam：Agent 群体智能</h1>

<p align="center">
  <strong>今天的 Agent 各自为战 🤖，明天的 Agent 将协同作战 🦞🤖🤖🤖<br>
  ClawTeam：让 AI Agent 自主组建团队、分配任务、协同工作的 CLI 工具</strong>
</p>

<p align="center">
  <a href="#-快速开始"><img src="https://img.shields.io/badge/快速开始-3_分钟-blue?style=for-the-badge" alt="Quick Start"></a>
  <a href="#-使用场景"><img src="https://img.shields.io/badge/使用场景-3_个演示-green?style=for-the-badge" alt="Use Cases"></a>
  <a href="#-功能特性"><img src="https://img.shields.io/badge/功能-12+-purple?style=for-the-badge" alt="Features"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/开源协议-MIT-yellow?style=for-the-badge" alt="License"></a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-≥3.10-blue?logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/typer-CLI-green" alt="Typer">
  <img src="https://img.shields.io/badge/agents-Claude_Code_%7C_Codex_%7C_Any_CLI-blueviolet" alt="Agents">
  <img src="https://img.shields.io/badge/transport-File_%7C_ZeroMQ_P2P-orange" alt="Transport">
  <a href="https://github.com/HKUDS/.github/blob/main/profile/README.md"><img src="https://img.shields.io/badge/飞书-交流群-E9DBFC?style=flat&logo=feishu&logoColor=white" alt="Feishu"></a>
  <a href="https://github.com/HKUDS/.github/blob/main/profile/README.md"><img src="https://img.shields.io/badge/微信-交流群-C5EAB4?style=flat&logo=wechat&logoColor=white" alt="WeChat"></a>
</p>

**一行命令**：给 Agent 一个目标，它自动组建团队完成任务。支持 [Claude Code](https://claude.ai/claude-code)、[Codex](https://openai.com/codex)、[OpenClaw](https://github.com/openclaw/openclaw)、[nanobot](https://github.com/HKUDS/nanobot)、[Cursor](https://cursor.com) 及任意 CLI Agent。&nbsp;&nbsp;[**English**](README.md)

---

## 📰 News

**2026-03-18** ClawTeam 项目正式公开发布。

**2026-03-23** ClawTeam `v0.2.0` 今日发布。

**2026-03** 当前能力基线已包含配置管理、多用户协作、Web UI、P2P 传输与团队模板。

---

<table align="center" width="100%">
<tr>
<td width="50%" align="center" style="vertical-align: top; padding: 10px;">

<strong>v0.1.0</strong>

https://github.com/user-attachments/assets/7e2f0ecd-8fe3-4970-90ac-5c9669ff060c

</td>
<td width="50%" align="center" style="vertical-align: top; padding: 10px;">

<strong>v0.2.0</strong>

https://github.com/user-attachments/assets/fd23be91-5cf4-457c-a77e-bac24b76e58f

</td>
</tr>
</table>

☝️ 智能 Leader Agent 在 8 块 H100 GPU 上编排 8 个专职子 Agent，自主设计实验，并根据实时表现动态重分配资源。

🧠 系统会在团队之间汇总突破、持续调整策略，实现无需人工介入的研究自动化。

<p align="center">
  <img src="assets/teaser.png" alt="ClawTeam - Agent 群体智能" width="800">
</p>

---

## ✨ 核心场景

<table align="center" width="100%">
<tr>
<td width="25%" align="center" style="vertical-align: top; padding: 15px;">

<h3>🔬 自主 ML 研究</h3>

<div align="center">
  <img src="https://img.shields.io/badge/AutoResearch-FF6B6B?style=for-the-badge&logo=pytorch&logoColor=white" alt="AutoResearch" />
</div>

<img src="assets/scene-autoresearch.png" width="180">

<p align="center"><strong>多 GPU 实验群体</strong></p>

<p align="center">8 Agent × 8 H100 自主优化 LLM 训练：2430+ 实验，val_bpb 1.044→0.977</p>

</td>
<td width="25%" align="center" style="vertical-align: top; padding: 15px;">

<h3>🏗️ Agent 软件工程</h3>

<div align="center">
  <img src="https://img.shields.io/badge/全栈开发-4ECDC4?style=for-the-badge&logo=git&logoColor=white" alt="Engineering" />
</div>

<img src="assets/scene-engineering.png" width="180">

<p align="center"><strong>并行软件开发</strong></p>

<p align="center">Agent 自动拆分为 API、后端、前端、测试 —— 各自独立分支，完成后自动合并</p>

</td>
<td width="25%" align="center" style="vertical-align: top; padding: 15px;">

<h3>💰 AI 对冲基金</h3>

<div align="center">
  <img src="https://img.shields.io/badge/投资分析-FFD93D?style=for-the-badge&logo=bitcoin&logoColor=black" alt="Hedge Fund" />
</div>

<img src="assets/scene-hedgefund.png" width="180">

<p align="center"><strong>多分析师信号融合</strong></p>

<p align="center">7 个分析师 Agent（价值、成长、技术、基本面、情绪）+ 风控经理收敛投资决策</p>

</td>
<td width="25%" align="center" style="vertical-align: top; padding: 15px;">

<h3>🎪 自定义群体</h3>

<div align="center">
  <img src="https://img.shields.io/badge/TOML_模板-C77DFF?style=for-the-badge&logo=toml&logoColor=white" alt="Templates" />
</div>

<img src="assets/scene-template.png" width="180">

<p align="center"><strong>一键启动团队</strong></p>

<p align="center">用 TOML 模板定义任意团队原型 —— 角色、任务、提示词 —— 一条命令 <code>clawteam launch</code> 启动</p>

</td>
</tr>
</table>

---

## 🤔 为什么需要 ClawTeam？

AI 编程 Agent 很强大 —— 但它们**各自为战**。当任务太大时，你只能手动拆分工作、复制粘贴上下文、合并结果。

**如果 Agent 能自己组队呢？**

ClawTeam 实现了 **Agent 群体智能（Swarm Intelligence）**—— Agent 自主组建团队、分工协作、共享发现、收敛到最优方案。一个 Leader Agent 可以：

- 🚀 **创建子 Agent** —— 每个子 Agent 拥有独立的 Git Worktree 和 tmux 会话
- 📋 **分配任务** —— 支持依赖链，完成时自动解除下游阻塞
- 💬 **发送消息** —— 向任意子 Agent 发送指令
- 📊 **监控进度** —— 查看看板、读取实验结果
- 🔄 **调整方向** —— 终止低效 Agent，用新方向重新分配

人类只需提供初始目标，**群体智能完成剩下的一切。**

<p align="center">
  <img src="assets/comic-how-it-works.png" alt="ClawTeam 工作流程" width="700">
</p>

---

## 🎯 群体智能的优势

<table>
<tr>
<td width="33%" valign="top">

### 🦞 Agent 创建 Agent
Leader Agent 调用 `clawteam spawn` 创建 Worker。每个 Worker 自动获得独立的 **Git Worktree**、**tmux 窗口**和**身份标识**。

```bash
# Leader Agent 执行：
clawteam spawn --team my-team \
  --agent-name worker1 \
  --task "实现认证模块"
```

</td>
<td width="33%" valign="top">

### 🤖 Agent 之间对话
Worker 检查收件箱、更新任务状态、汇报结果 —— 全部通过 CLI 命令，启动时**自动注入**协作提示词。

```bash
# Worker Agent 检查任务：
clawteam task list my-team --owner me
# 汇报结果：
clawteam inbox send my-team leader \
  "认证模块完成，全部测试通过。"
```

</td>
<td width="33%" valign="top">

### 👀 你只需观看
通过 tmux 平铺视图或 Web UI 监控群体工作。Leader 负责协调 —— 你只在需要时介入。

```bash
# 同时观看所有 Agent
clawteam board attach my-team
# 或打开 Web 仪表板
clawteam board serve --port 8080
```

</td>
</tr>
</table>

| | ClawTeam | 其他多 Agent 框架 |
|---|---------|-----------------|
| 🎯 **使用者** | **AI Agent 自身** | 人类编写编排代码 |
| ⚡ **搭建** | `pip install` + 一句提示词 | Docker、云 API、YAML 配置 |
| 🏗️ **基础设施** | 文件系统 + tmux 即可 | Redis、消息队列、数据库 |
| 🤖 **Agent 支持** | 任意 CLI Agent（Claude Code、Codex、OpenClaw 等） | 仅限特定框架 |
| 🌳 **隔离机制** | Git Worktree（真实分支、真实 diff） | 容器或虚拟环境 |
| 🧠 **协调方式** | 群体自组织 CLI 命令 | 硬编码编排逻辑 |

---

## 🎬 使用场景

### 🔬 1. 自主 ML 研究 — 8 Agent × 8 块 H100 GPU

基于 [@karpathy 的 autoresearch](https://github.com/karpathy/autoresearch)。人类告诉 Leader Agent：*"用 8 块 GPU 优化这个 LLM 训练配置。"* **Leader 自主完成所有工作。**

<p align="center">
  <img src="assets/autoresearch-progress.png" alt="AutoResearch 实验进展" width="720">
  <br>
  <em>🏆 val_bpb: 1.044 → 0.977（提升 6.4%）| 2430+ 实验 | ~30 GPU 小时</em>
</p>

**Leader Agent 自主完成的操作：**

```
人类提示词："用 8 块 GPU 优化 train.py，阅读 program.md 了解规则。"

🦞 Leader Agent 的行动：
├── 📖 阅读 program.md，理解实验协议
├── 🏗️ clawteam team spawn-team autoresearch
├── 🚀 为每块 GPU 分配研究方向：
│   ├── GPU 0: clawteam spawn --task "探索模型深度（DEPTH 10-16）"
│   ├── GPU 1: clawteam spawn --task "探索模型宽度（ASPECT_RATIO 80-128）"
│   ├── GPU 2: clawteam spawn --task "调优学习率和优化器"
│   ├── GPU 3: clawteam spawn --task "探索批量大小"
│   ├── GPU 4-7: clawteam spawn tmux codex --task "..."（Codex Agent）
│   └── 🌳 每个 Agent 独立的 Git Worktree 和分支
├── 🔄 每 30 分钟检查进展：
│   ├── clawteam board show autoresearch
│   ├── 读取每个 Agent 的 results.tsv
│   ├── 🏆 识别最佳发现（depth=12、batch=2^17、norm-before-RoPE）
│   └── 📡 交叉融合：让新 Agent 从最佳配置开始
├── 🔧 Agent 完成后重新分配 GPU：
│   ├── 终止空闲 Agent，清理工作区
│   ├── 从最佳 commit 创建新的 Worktree
│   └── 用组合优化方向创建新 Agent
└── ✅ 2430+ 实验后：val_bpb 1.044 → 0.977
```

完整结果：[novix-science/autoresearch](https://github.com/novix-science/autoresearch)

---

### 🏗️ 2. 大规模 Agent 软件工程

你告诉 Claude Code：*"帮我做一个全栈 Todo 应用。"* Claude 判断这是多模块任务，**自主组建团队**：

```
人类提示词："做一个全栈 Todo 应用，包含认证、数据库和 React 前端。"

🦞 Leader Agent 的行动：
├── 🏗️ clawteam team spawn-team webapp -d "全栈 Todo 应用"
├── 📋 创建带依赖链的任务：
│   ├── T1: "设计 REST API 接口"          → architect
│   ├── T2: "实现 JWT 认证" --blocked-by T1  → backend1
│   ├── T3: "构建数据库层" --blocked-by T1   → backend2
│   ├── T4: "构建 React 前端"             → frontend
│   └── T5: "集成测试" --blocked-by T2,T3,T4 → tester
├── 🚀 创建 5 个子 Agent（各自独立 Git Worktree）
├── 🔗 依赖自动解除：
│   ├── architect 完成 → backend1 和 backend2 自动解除阻塞
│   └── 所有后端完成 → tester 自动开始
├── 💬 子 Agent 通过收件箱协调：
│   ├── architect → backend1: "API 接口规范在这..."
│   ├── backend1 → tester: "认证端点已就绪 /api/auth/*"
│   └── tester → leader: "全部 47 个测试通过 ✅"
└── 🌳 Leader 将所有 Worktree 合并回主分支
```

---

### 💰 3. AI 对冲基金 — 一键启动团队

预置的 TOML 模板一键创建 **7 Agent** 投资分析团队：

```bash
# 一条命令启动完整团队：
clawteam launch hedge-fund --team fund1 --goal "分析 AAPL、MSFT、NVDA 的 Q2 2026 投资价值"
```

```
🦞 自动发生的事情：
├── 📊 投资组合经理（Leader）启动并接收目标
├── 🤖 5 个分析师 Agent 启动，各有不同策略：
│   ├── 🎩 巴菲特分析师 → 价值投资（护城河、ROE、DCF）
│   ├── 🚀 成长分析师   → 颠覆潜力（TAM、网络效应）
│   ├── 📈 技术分析师   → 技术指标（EMA、RSI、布林带）
│   ├── 📋 基本面分析师 → 财务比率（P/E、D/E、FCF）
│   └── 📰 情绪分析师   → 新闻 + 内部交易信号
├── 🛡️ 风险经理汇总所有信号，计算仓位限制
└── 💼 投资组合经理做出最终买入/卖出/持有决策
```

---

## 📦 安装

```bash
pip install clawteam

# 或从源码安装
git clone https://github.com/HKUDS/ClawTeam.git
cd ClawTeam
pip install -e .

# 可选：P2P 传输（ZeroMQ）
pip install -e ".[p2p]"
```

需要 **Python 3.10+**。依赖：`typer`、`pydantic`、`rich`。

下面所有 `spawn` 示例都默认你填写的 agent CLI 已经安装好，并且在 `PATH` 里可以直接运行。

---

## 🚀 快速开始

如果你是第一次用 ClawTeam，建议按这个顺序：

1. 先确认 `tmux` 和你的 agent CLI 本机能单独跑起来。
2. 选一条路径：让 agent 驱动，或者你自己手动驱动。
3. 根据下面的支持表，选择正确的 `spawn` 命令。
4. 如果你接的是新 agent，先看兼容要求，再去排查问题。

### ✅ 开始前先确认

先跑这几个检查：

```bash
tmux -V
clawteam --help

# 把 claude 换成你实际要用的 agent：
claude --version
codex --version
nanobot --help
```

如果 agent CLI 自己都跑不起来，`clawteam spawn` 也不会帮你修好它。

### ⚡ 方式一：让 Agent 驱动（推荐）

ClawTeam 自带一个可复用的 skill，位于 `skills/clawteam/`。

**Claude Code**

把这个 skill 安装到 `~/.claude/skills/clawteam`，然后直接告诉你的 Agent：

```
"帮我做一个 Web 应用。用 clawteam 把工作拆分给多个 Agent。"
```

**Codex**

把同一个 skill 安装到 `$CODEX_HOME/skills/clawteam`（通常是 `~/.codex/skills/clawteam`），然后提示：

```
用 $clawteam 把这个任务拆成多 Agent 团队，协调执行直到完成。
```

Agent 会自动使用 `clawteam` 命令创建团队、启动 Worker、分配任务、协调工作。

### 🔧 方式二：手动操作

```bash
# 1. 创建团队
clawteam team spawn-team my-team -d "构建认证模块" -n leader

# 2. 启动 Worker Agent —— 每个自动获得 Git Worktree、tmux 窗口和身份
clawteam spawn --team my-team --agent-name alice --task "实现 OAuth2 流程"
clawteam spawn --team my-team --agent-name bob   --task "编写认证单元测试"

# 3. Worker 自动获得协作提示词，知道如何：
#    ✅ 查看任务：clawteam task list my-team --owner alice
#    ✅ 更新状态：clawteam task update my-team <id> --status completed
#    ✅ 汇报 Leader：clawteam inbox send my-team leader "完成！"

# 4. 观看 Agent 协同工作
clawteam board attach my-team
```

### 🧩 Profiles 和 Presets

如果你想使用非默认 provider、模型或 API 网关，推荐先配置 **profile**，
而不是每次手动导出一堆环境变量。

```bash
# 查看内置 provider 模板
clawteam preset list
clawteam preset show moonshot-cn

# 从 preset 生成可复用的 runtime profile
clawteam preset generate-profile moonshot-cn claude --name claude-kimi

# MiniMax（M2.7）— 国际或国内端点
clawteam preset generate-profile minimax-global claude --name claude-minimax
clawteam preset generate-profile minimax-cn claude --name claude-minimax-cn

# 或使用交互式 TUI
clawteam profile wizard

# Claude Code 在全新机器 / 全新 HOME 下通常只需要执行一次
clawteam profile doctor claude

# 在真正 spawn 之前先做 smoke test
MOONSHOT_API_KEY=... clawteam profile test claude-kimi
MINIMAX_API_KEY=... clawteam profile test claude-minimax
```

可以这样理解：

- `profile` 是最终给 `spawn` / `launch` 使用的运行时配置
- `preset` 是可复用的 provider 模板，用来生成一个或多个 profile
- `wizard` 适合第一次配置时用
- `doctor` 主要用于修复 Claude Code 首次 onboarding 状态

### 🧭 我到底该用哪条 spawn 命令？

通用格式是 `clawteam spawn [backend] [command] ...`。`command` 要填你机器上本来就能工作的 agent CLI：

```bash
# Claude Code
clawteam spawn tmux claude --team my-team --agent-name alice --task "实现 OAuth2"

# Codex
clawteam spawn tmux codex --team my-team --agent-name bob --task "编写前端测试"

# nanobot
clawteam spawn tmux nanobot --team my-team --agent-name carol --task "构建 API"

# 已配置好的 profile（推荐用于非默认 provider / 模型）
clawteam spawn tmux --profile claude-kimi --team my-team --agent-name dave --task "重构认证流程"
```

说明：

- `tmux` 是默认 backend，适合需要保留交互式 TUI、并且想直接观察 agent 工作过程的场景。
- `subprocess` 更适合一次性工具或非交互脚本。
- `nanobot` 在 ClawTeam 内部会自动规范化为 `nanobot agent`，上面的写法就是正确入口。
- Claude Code 和 Codex 在全新 worktree 里的 trust prompt，tmux backend 会自动确认。
- 如果你用的是非默认 provider / 模型，优先使用 `--profile <name>`，不要每次手工拼环境变量。

### 🔌 接入别的 Agent 要满足什么？

除了 Claude Code、Codex、nanobot 之外，ClawTeam 也能接别的 CLI agent，但至少要满足这几个条件：

1. 命令在 `PATH` 里能找到，并且脱离 ClawTeam 也能正常启动。
2. 能在指定工作目录或 git worktree 里运行。
3. 能接收初始任务，方式可以是命令行参数，也可以是交互输入。
4. 如果是交互式 agent，启动后不能立刻退出，得能留在 `tmux` 里。

如果你不确定一个 agent 是否兼容，先这样测：

```bash
clawteam spawn subprocess <your-agent> --team my-team --agent-name test --task "Say OK"
```

这条能跑通，再切到 `tmux` 做交互式监控。

### 🤖 支持的 Agent

下表中的命令都默认对应 CLI 已经能在你的机器上独立运行。

| Agent | 启动命令 | 状态 |
|-------|---------|------|
| [Claude Code](https://claude.ai/claude-code) | `clawteam spawn tmux claude --team ...` | ✅ 完全支持 |
| [Codex](https://openai.com/codex) | `clawteam spawn tmux codex --team ...` | ✅ 完全支持 |
| [OpenClaw](https://github.com/openclaw/openclaw) | `clawteam spawn tmux openclaw --team ...` | ✅ 完全支持 |
| [nanobot](https://github.com/HKUDS/nanobot) | `clawteam spawn tmux nanobot --team ...` | ✅ 完全支持 |
| [Kimi CLI](https://github.com/MoonshotAI/kimi-cli) | `clawteam spawn tmux kimi --team ...` | ✅ 完全支持 |
| [Cursor](https://cursor.com) | `clawteam spawn subprocess cursor --team ...` | 🔮 实验性 |
| 自定义脚本 | `clawteam spawn subprocess python --team ...` | ✅ 完全支持 |

像 “Claude Code 走 Moonshot Kimi”、”Claude Code 走 MiniMax” 或 “Gemini 走 Vertex” 这类 provider-aware 场景，
推荐先用 `profile` + `preset` 配好，再通过 `--profile` 启动。

---

## ✨ 功能特性

<table>
<tr>
<td width="50%" valign="top">

### 🦞 Agent 自组织
- Leader Agent 创建和管理 Worker Agent
- **自动注入协作提示词** —— 零配置
- Worker 自主汇报状态、结果和空闲状态
- 支持任意 CLI Agent

### 🌳 工作区隔离
- 每个 Agent 独立 **Git Worktree**（独立分支）
- 并行 Agent 之间零冲突
- 检查点、合并、清理命令

### 📋 带依赖的任务跟踪
- 共享看板：`pending` → `in_progress` → `completed` / `blocked`
- `--blocked-by` 依赖链 —— **完成时自动解除阻塞**
- `task wait` 阻塞直到全部完成

</td>
<td width="50%" valign="top">

### 💬 Agent 间通信
- 点对点**收件箱**（发送、接收、预览）
- **广播**给所有团队成员
- 文件传输（默认）或 ZeroMQ P2P 传输（含离线回退）

### 📊 监控面板
- `board show` — 终端看板
- `board live` — 自动刷新
- `board attach` — **tmux 平铺视图**
- `board serve` — **Web UI 实时仪表板**

### 🎪 团队模板
- **TOML 文件**定义团队原型（角色、任务、提示词）
- 一条命令启动完整团队：`clawteam launch <template>`
- 内置：AI 对冲基金（7 Agent），可自定义

</td>
</tr>
</table>

---

## 🗺️ 发展路线

| 阶段 | 版本 | 内容 | 状态 |
|------|------|------|------|
| **当前** | v0.3 | 文件传输 + P2P (ZeroMQ) + Web UI + 多用户 + 团队模板 | ✅ 已完成 |
| **Phase 1** | v0.4 | Redis Transport —— 跨机器消息通信 | 🔜 计划中 |
| **Phase 2** | v0.5 | 共享状态层 —— 团队配置和任务也跨机器 | 🔜 计划中 |
| **Phase 3** | v0.6 | Agent 市场 —— 发现和复用社区 Agent 模板 | 💡 规划中 |
| **Phase 4** | v0.7 | 自适应调度 —— 根据 Agent 性能动态调整任务分配 | 💡 规划中 |
| **Phase 5** | v1.0 | 生产级稳定版 —— 认证、权限、审计日志 | 💡 规划中 |

### Milestones

| 里程碑 | 状态 | 说明 |
|---|---|---|
| v0.1.x | ✅ 已发布 | 核心 CLI、团队/任务/消息流、看板、模板、打包发布。 |
| v0.2.0 | ✅ 已发布 | 稳定性修复、文档升级、spawn/workspace 修复与 release 打包。 |
| v0.3 | 📍 路线基线 | 文件传输 + P2P、Web UI、多用户工作流、团队模板。 |

---

## 📖 致谢

- [@karpathy/autoresearch](https://github.com/karpathy/autoresearch) — 8 Agent 群体实验的基础框架
- [Claude Code](https://claude.ai/claude-code) 和 [Codex](https://openai.com/codex) — 作为 ClawTeam 团队成员的 AI 编程 Agent
- [ai-hedge-fund](https://github.com/virattt/ai-hedge-fund) — AI 对冲基金模板的灵感来源
- [CLI-Anything](https://github.com/HKUDS/CLI-Anything) — 姊妹项目，让所有软件都能被 Agent 使用

## ⭐ Star History

如果 ClawTeam 帮助你的 AI Agent 协同工作，给我们一个 star ⭐

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

## 📄 开源协议

MIT

---

<div align="center">

**ClawTeam** — *Agent 群体智能* 🦞

<sub>8 Agent × 8 H100 × 2430 实验 × 一个 CLI × 一个群体</sub>

<br>

<img src="assets/icon.png" alt="ClawTeam" width="80">

</div>

<p align="center">
  <em>感谢访问 ✨ ClawTeam！</em><br><br>
  <img src="https://visitor-badge.laobi.icu/badge?page_id=HKUDS.ClawTeam&style=for-the-badge&color=00d4ff" alt="Views">
</p>
