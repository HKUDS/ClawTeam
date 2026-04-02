# ClawTeam Evolution Roadmap

## 现状 (v0.2)

```
单用户 → 单机 → 文件系统 → CLI 驱动
```

- 所有数据在 `~/.clawteam/`（团队配置、任务、消息）
- 所有 agent 必须在同一台机器
- 纯文件 I/O，零依赖

---

## Phase 1: Transport 抽象层 (v0.3)

**目标**: 让消息通信层可插拔，不改上层接口。

**架构变化**:
```
现在:
  MailboxManager → 直接读写文件

Phase 1:
  MailboxManager → Transport(接口)
                   ├── FileTransport (默认，当前行为)
                   └── (未来: RedisTransport, ...)
```

**具体任务**:

| 任务 | 描述 | 建议 |
|------|------|------|
| 定义 Transport 接口 | `send()`, `receive()`, `peek()`, `peek_count()`, `broadcast()` | 人员 A |
| 重构 FileTransport | 把 `mailbox.py` 当前的文件操作抽成 `FileTransport` 类 | 人员 A |
| 重构 MailboxManager | 通过 `OH_TRANSPORT=file` 选择 backend | 人员 A |
| TaskStore 抽象 | 同样抽出 `FileTaskStore`，预留接口 | 人员 B |
| 测试 | 确保重构后行为不变 | 人员 B |

**交付物**:
```
clawteam/transport/
├── __init__.py
├── base.py           # Transport 抽象基类
└── file.py           # FileTransport (当前行为)

clawteam/store/
├── __init__.py
├── base.py           # TaskStore 抽象基类
└── file.py           # FileTaskStore (当前行为)
```

**验收**: 所有现有命令行为不变，`OH_TRANSPORT=file` 为默认值。

---

## Phase 2: Redis Transport (v0.4)

**目标**: 支持跨机器消息通信。

**架构变化**:
```
机器A (leader) ─── RedisTransport ──┐
                                    ├── Redis Server
机器B (worker) ─── RedisTransport ──┘

团队配置 / 任务 → 仍然用文件（或共享文件系统）
消息通信 → Redis (高频，实时)
```

**具体任务**:

| 任务 | 描述 | 建议 |
|------|------|------|
| RedisTransport 实现 | `LPUSH`/`RPOP` 实现 send/receive | 人员 A |
| 连接管理 | URL 配置、连接池、断线重连 | 人员 A |
| 配置方式 | `OH_TRANSPORT=redis` + `OH_REDIS_URL=redis://...` | 人员 B |
| broadcast 实现 | 需要知道团队成员列表 → 依赖 TeamManager | 人员 B |
| 混合模式 | 消息走 Redis，配置/任务走文件 | 人员 B |
| 集成测试 | 两台机器（或两个 container）实际跑通 | 一起 |

**新增依赖**: `redis` (pypi)，可选安装 `pip install clawteam[redis]`

**验收**:
```bash
# 机器 A
export OH_TRANSPORT=redis
export OH_REDIS_URL=redis://192.168.1.100:6379
oh team spawn-team dev-team -n leader
oh spawn tmux claude --team dev-team -n worker1 --task "..."

# 机器 B
export OH_TRANSPORT=redis
export OH_REDIS_URL=redis://192.168.1.100:6379
oh inbox receive dev-team --agent worker1
# => 收到消息 ✅
```

---

## Phase 3: 共享状态层 (v0.5)

**目标**: 团队配置和任务也能跨机器共享。

Phase 2 只解决了消息跨机器，但团队配置（`config.json`）和任务（`task-*.json`）还在本地文件。

**两种路线（选一个）**:

### 路线 A: NFS / 共享文件系统

```bash
# 所有机器挂载同一个 NFS
export CLAWTEAM_DATA_DIR=/mnt/shared/clawteam
# 零代码改动，直接可用
```

最简单，但依赖网络文件系统基础设施。

### 路线 B: Redis 统一存储

```
消息 → Redis (Phase 2 已做)
配置 → Redis Hash
任务 → Redis Hash

所有状态都在 Redis，文件系统只做本地缓存
```

**具体任务 (路线 B)**:

| 任务 | 描述 | 建议 |
|------|------|------|
| RedisTeamStore | 团队配置存 Redis Hash | 人员 A |
| RedisTaskStore | 任务存 Redis Hash | 人员 B |
| 数据迁移工具 | `oh migrate file-to-redis` | 一起 |
| 统一配置 | `OH_BACKEND=redis` 一个变量搞定所有 | 一起 |

**验收**: 两台机器共享同一个团队、同一个任务板、同一个消息队列。

---

## Phase 4: 多用户协作 (v0.6)

**目标**: 不同人的 agent 组成一个团队。

**新增能力**:

| 能力 | 描述 |
|------|------|
| 用户身份 | 区分"谁的 agent"（不只是 agent name） |
| 权限模型 | 谁能创建团队、谁能加入、谁能看任务 |
| 命名空间 | `user1/worker1` vs `user2/worker1` |
| Token 认证 | 连接 Redis 时验证身份 |

```
用户 A 的 Claude Code ──┐
                        ├── Redis ── Team: project-x
用户 B 的 Claude Code ──┘

用户 A 的 agent 和用户 B 的 agent 在同一个团队里协作
```

---

## Phase 5: Web UI (v1.0)

**目标**: 浏览器看板，替代终端 Rich 渲染。

```
oh board serve --port 8080
```

- 实时看板（WebSocket 推送）
- 多团队概览
- 任务拖拽
- 消息历史

---

## 总览

```
v0.2         → 单机文件系统，能用
v0.3 (现在)  → Config 系统 + 多用户协作 + Web UI (已完成，跨机器用 SSHFS)
v0.4+        → 可选: Transport 抽象层 / Redis (如需超出 SSHFS 的场景)
```

### v0.3 已完成内容
- Config 系统：`oh config show/set/get/health`
- 多用户协作：`OH_USER` / `oh config set user`，(user, name) 复合唯一性
- Web UI：`oh board serve`，SSE 实时推送，深色主题看板
- 跨机器方案：SSHFS/云盘 + `CLAWTEAM_DATA_DIR`，零代码改动

## 协作建议

两人并行的最佳分工模式：

```
Phase 1:  人员 A — Transport 抽象 + FileTransport
          人员 B — Store 抽象 + FileTaskStore + 测试

Phase 2:  人员 A — RedisTransport 核心实现
          人员 B — 配置系统 + broadcast + 集成测试

Phase 3:  人员 A — RedisTeamStore
          人员 B — RedisTaskStore + 迁移工具
```

接口定义（Phase 1）要先一起对齐，后面就可以各做各的。
