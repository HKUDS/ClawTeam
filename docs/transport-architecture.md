# Transport 抽象层 — 架构图 & 时序图

## 1. 整体架构图

```
┌─────────────────────────────────────────────────────────────────────┐
│                        CLI / Agent 上层调用                          │
│  (commands.py, watcher.py, lifecycle.py, plan.py, collector.py)    │
└──────────────────────────────┬──────────────────────────────────────┘
                               │  send() / broadcast() / receive() / peek()
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      MailboxManager                                 │
│                                                                     │
│  - 构建 TeamMessage (Pydantic 模型)                                  │
│  - 序列化为 JSON bytes                                               │
│  - 反序列化 bytes → TeamMessage                                      │
│  - 委托 I/O 给 self._transport                                      │
└──────────────────────────────┬──────────────────────────────────────┘
                               │  deliver() / fetch() / count() / list_recipients()
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     Transport (ABC)                                  │
│                                                                     │
│  deliver(recipient, data: bytes)     投递原始字节                     │
│  fetch(agent, limit, consume)        取消息 (consume 控制是否删除)     │
│  count(agent)                        未读计数                        │
│  list_recipients()                   列出所有收件人                    │
│  close()                             释放资源                        │
├────────────────────┬────────────────────────────────────────────────┤
│                    │                                                │
│   ┌────────────────▼───────────────┐  ┌─────────────────────────┐  │
│   │       FileTransport            │  │     P2PTransport        │  │
│   │                                │  │                         │  │
│   │  inboxes/{agent}/msg-*.json    │  │  ZMQ PUSH/PULL          │  │
│   │  原子写入 (tmp + rename)        │  │  + FileTransport 兜底    │  │
│   │  sorted glob 读取              │  │  + peers/*.json 发现     │  │
│   └────────────────────────────────┘  └──────────┬──────────────┘  │
│                                                  │ 内部组合         │
│                                                  │ (fallback)      │
│                                        ┌─────────▼──────────┐     │
│                                        │   FileTransport     │     │
│                                        │   (离线兜底实例)      │     │
│                                        └────────────────────┘     │
└─────────────────────────────────────────────────────────────────────┘
                               │
            ┌──────────────────┼──────────────────┐
            ▼                  ▼                  ▼
┌──────────────────┐ ┌──────────────────┐ ┌──────────────────┐
│   共享文件系统     │ │   共享文件系统     │ │   ZMQ TCP        │
│                  │ │                  │ │                  │
│ teams/{team}/    │ │ teams/{team}/    │ │ tcp://host:port  │
│  inboxes/        │ │  peers/          │ │ PUSH ──► PULL    │
│   {agent}/       │ │   {agent}.json   │ │                  │
│    msg-*.json    │ │                  │ │ (进程间直连)       │
└──────────────────┘ └──────────────────┘ └──────────────────┘
   消息存储/兜底          Peer 地址发现         实时消息通道
```

## 2. 配置解析流程

```
_default_transport(team_name)
         │
         ▼
  CLAWTEAM_TRANSPORT 环境变量?
         │
    ┌────┴────┐
    │ 有值    │ 无值
    ▼         ▼
  使用该值   load_config().transport?
              │
         ┌────┴────┐
         │ 有值    │ 无值
         ▼         ▼
       使用该值   默认 "file"
         │         │
         └────┬────┘
              ▼
     name == "p2p"?
         │
    ┌────┴────┐
    │ 是      │ 否
    ▼         ▼
  P2PTransport   FileTransport
  (bind_agent=   (team_name)
   从 AgentIdentity
   读取)
```

## 3. FileTransport 时序图 — 发送 & 接收

```
  Alice (sender)          MailboxManager           FileTransport              文件系统
       │                       │                       │                       │
       │  send("alice",        │                       │                       │
       │    "bob", "hello")    │                       │                       │
       │──────────────────────►│                       │                       │
       │                       │  构建 TeamMessage      │                       │
       │                       │  序列化为 JSON bytes   │                       │
       │                       │                       │                       │
       │                       │  deliver("bob", data) │                       │
       │                       │──────────────────────►│                       │
       │                       │                       │  写入 .tmp-xxx.json    │
       │                       │                       │──────────────────────►│
       │                       │                       │  rename → msg-*.json  │
       │                       │                       │──────────────────────►│
       │                       │                       │◄─────────── ok ───────│
       │◄─────── TeamMessage ──│                       │                       │
       │                       │                       │                       │
       │                       │                       │                       │
  Bob (receiver)               │                       │                       │
       │                       │                       │                       │
       │  receive("bob")       │                       │                       │
       │──────────────────────►│                       │                       │
       │                       │  fetch("bob",         │                       │
       │                       │    consume=True)      │                       │
       │                       │──────────────────────►│                       │
       │                       │                       │  sorted glob          │
       │                       │                       │  ("msg-*.json")       │
       │                       │                       │──────────────────────►│
       │                       │                       │◄──── [file1, ...]  ───│
       │                       │                       │  read_bytes(file1)    │
       │                       │                       │──────────────────────►│
       │                       │                       │◄──── raw bytes ───────│
       │                       │                       │  unlink(file1)        │
       │                       │                       │──────────────────────►│
       │                       │◄──── [bytes, ...]  ───│                       │
       │                       │                       │                       │
       │                       │  json.loads → TeamMessage                     │
       │◄─── [TeamMessage] ────│                       │                       │
```

## 4. P2PTransport 时序图 — 对方在线 (ZMQ 直连)

```
  Agent A (sender)        MailboxManager         P2PTransport               Agent B (receiver)
       │                       │                      │                          │
       │                       │                      │    _start_listener()     │
       │                       │                      │    ┌──────────────────┐  │
       │                       │                      │    │ PULL.bind(:port) │  │
       │                       │                      │    │ 写 peers/B.json  │  │
       │                       │                      │    └──────────────────┘  │
       │                       │                      │                          │
       │  send("A","B","hi")   │                      │                          │
       │──────────────────────►│                      │                          │
       │                       │  deliver("B", data)  │                          │
       │                       │─────────────────────►│                          │
       │                       │                      │                          │
       │                       │                      │  读 peers/B.json         │
       │                       │                      │  → tcp://hostB:port      │
       │                       │                      │                          │
       │                       │                      │  检查 PID 存活? ✓        │
       │                       │                      │                          │
       │                       │                      │  PUSH.connect(addr)      │
       │                       │                      │  PUSH.send(data)         │
       │                       │                      │─────── ZMQ TCP ─────────►│
       │                       │                      │                          │  PULL.recv()
       │                       │                      │                          │  收到 data!
       │◄─────── ok ───────────│                      │                          │
       │                       │                      │                          │
       │                       │                      │          receive("B")    │
       │                       │                      │◄─────────────────────────│
       │                       │                      │  PULL.recv(NOBLOCK)      │
       │                       │                      │  → data                  │
       │                       │                      │  (+ 检查文件兜底)         │
       │                       │                      │──── [bytes] ────────────►│
       │                       │                      │                          │
```

## 5. P2PTransport 时序图 — 对方离线 (文件兜底)

```
  Agent A (sender)        MailboxManager         P2PTransport          FileTransport       文件系统
       │                       │                      │                      │                │
       │  send("A","B","hi")   │                      │                      │                │
       │──────────────────────►│                      │                      │                │
       │                       │  deliver("B", data)  │                      │                │
       │                       │─────────────────────►│                      │                │
       │                       │                      │                      │                │
       │                       │                      │  读 peers/B.json     │                │
       │                       │                      │  → 不存在 或 PID 已死  │                │
       │                       │                      │                      │                │
       │                       │                      │  ╔══════════════════╗ │                │
       │                       │                      │  ║ ZMQ 不可达       ║ │                │
       │                       │                      │  ║ 回退到文件兜底    ║ │                │
       │                       │                      │  ╚══════════════════╝ │                │
       │                       │                      │                      │                │
       │                       │                      │  fallback.deliver()  │                │
       │                       │                      │─────────────────────►│                │
       │                       │                      │                      │  tmp + rename  │
       │                       │                      │                      │───────────────►│
       │◄─────── ok ───────────│                      │                      │                │
       │                       │                      │                      │                │
       │                       │                      │                      │                │
   === Agent B 上线 ===        │                      │                      │                │
       │                       │                      │                      │                │
  Agent B                      │                      │                      │                │
       │          receive("B") │                      │                      │                │
       │──────────────────────►│                      │                      │                │
       │                       │  fetch("B")          │                      │                │
       │                       │─────────────────────►│                      │                │
       │                       │                      │  1. PULL.recv() → 无  │                │
       │                       │                      │                      │                │
       │                       │                      │  2. fallback.fetch() │                │
       │                       │                      │─────────────────────►│                │
       │                       │                      │                      │  glob + read   │
       │                       │                      │                      │───────────────►│
       │                       │                      │                      │◄── raw bytes ──│
       │                       │                      │                      │  unlink        │
       │                       │                      │                      │───────────────►│
       │                       │                      │◄──── [bytes] ────────│                │
       │                       │◄──── [bytes] ────────│                      │                │
       │◄─── [TeamMessage] ────│                      │                      │                │
       │      (离线消息到达!)    │                      │                      │                │
```

## 6. P2P 与文件共享的正交关系

```
┌─────────────────────────────────────────────────────────────────┐
│                        ClawTeam 系统                             │
│                                                                 │
│  ┌───────────────────────┐    ┌───────────────────────────────┐ │
│  │   P2P 消息通道         │    │   共享文件系统 (SSHFS/网盘)     │ │
│  │                       │    │                               │ │
│  │  • 临时的,读完即删     │    │  • 持久的,所有人可见           │ │
│  │  • 传信号/通知/请求    │    │  • 传内容/配置/状态            │ │
│  │  • ZMQ PUSH/PULL      │    │  • 普通文件读写                │ │
│  │                       │    │                               │ │
│  │  ┌─────────────────┐  │    │  ┌───────────────────────┐    │ │
│  │  │ inbox 消息       │  │    │  │ teams/{team}/          │    │ │
│  │  │ (TeamMessage)   │  │    │  │   config.json  (团队)   │    │ │
│  │  └─────────────────┘  │    │  │   plan.md     (计划)    │    │ │
│  │                       │    │  │   tasks.json  (任务)    │    │ │
│  │  Transport 层负责      │    │  │   members/    (成员)    │    │ │
│  │  (FileTransport 或    │    │  │   board/      (看板)    │    │ │
│  │   P2PTransport)       │    │  └───────────────────────┘    │ │
│  └───────────────────────┘    └───────────────────────────────┘ │
│          完 全 正 交,互 不 干 扰                                  │
└─────────────────────────────────────────────────────────────────┘
```

## 7. 模块依赖关系

```
commands.py ─────┐
watcher.py ──────┤
lifecycle.py ────┤
plan.py ─────────┼──► MailboxManager ──► Transport (ABC)
collector.py ────┘                          │
                                    ┌───────┴───────┐
                                    ▼               ▼
                              FileTransport    P2PTransport
                                    ▲               │
                                    │               │
                                    └── fallback ───┘

config.py ◄──── _default_transport() ──── transport 字段
identity.py ◄── _default_transport() ──── bind_agent (P2P 模式)

pyproject.toml
  dependencies: typer, pydantic, rich     (必选)
  optional[p2p]: pyzmq                    (按需)
```
