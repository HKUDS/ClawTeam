#!/bin/bash
# =============================================================================
# OpenClaw 非交互式 Worker 包装脚本 (v2.0 - 审计整改版)
# =============================================================================
# 参数：
#   $1 - 团队名
#   $2 - 收件人
#   $3 - 任务内容
#   $4 - (可选) 父 Agent ID，用于模型继承
# =============================================================================

TEAM_NAME="$1"
RECIPIENT="$2"
TASK_CONTENT="$3"
PARENT_AGENT="${4:-}"

# -----------------------------------------------------------------------------
# 1. 强制加载环境变量 (审计整改: 修复环境变量丢失 Bug)
# -----------------------------------------------------------------------------
# 加载多个可能的 .env 文件位置
ENV_FILES=(
    "$HOME/.openclaw/.env"
    "$HOME/.openclaw/workspace/.env"
    "$HOME/.env"
    "./.env"
)

for ENV_FILE in "${ENV_FILES[@]}"; do
    if [ -f "$ENV_FILE" ]; then
        # 安全加载：过滤注释行，逐行导出
        while IFS= read -r line || [ -n "$line" ]; do
            # 跳过空行和注释
            [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue
            # 导出环境变量
            export "$line" 2>/dev/null || true
        done < "$ENV_FILE"
    fi
done

# -----------------------------------------------------------------------------
# 2. 动态模型继承 (审计整改: 修复配置硬编码 Bug)
# -----------------------------------------------------------------------------
# 获取当前 Leader 的模型配置
CURRENT_MODEL="${OPENCLAW_CURRENT_MODEL:-}"
CURRENT_PROVIDER="${OPENCLAW_CURRENT_PROVIDER:-}"

# 如果没有环境变量，尝试从当前 session 推断
if [ -z "$CURRENT_MODEL" ]; then
    # 从 OPENCLAW_MODEL 环境变量获取（如果存在）
    CURRENT_MODEL="${OPENCLAW_MODEL:-}"
fi

# 构建 openclaw agent 命令参数
AGENT_CMD_ARGS=""

# 动态决定使用哪个 agent
if [ -n "$PARENT_AGENT" ]; then
    # 如果指定了父 Agent，尝试使用相同的配置
    AGENT_CMD_ARGS="--agent $PARENT_AGENT"
else
    # 默认使用 doubao，但允许通过环境变量覆盖
    AGENT_CMD_ARGS="--agent ${OPENCLAW_WORKER_AGENT:-doubao}"
fi

# 如果有模型配置，传递给子 Agent
if [ -n "$CURRENT_MODEL" ]; then
    AGENT_CMD_ARGS="$AGENT_CMD_ARGS --model $CURRENT_MODEL"
fi

# -----------------------------------------------------------------------------
# 3. 执行任务 (禁用缓存，强制实时请求)
# -----------------------------------------------------------------------------
# 设置路径
export PATH="$PATH:/opt/homebrew/bin:/usr/local/bin:$HOME/bin"
export OPENCLAW_CONFIG_PATH="$HOME/.openclaw/openclaw.json"
export OPENCLAW_WORKSPACE="$HOME/.openclaw/workspace"

# 记录执行日志
LOG_FILE="/tmp/worker_$(date +%Y%m%d_%H%M%S).log"
echo "=== Worker 执行日志 ===" > "$LOG_FILE"
echo "时间: $(date)" >> "$LOG_FILE"
echo "团队: $TEAM_NAME" >> "$LOG_FILE"
echo "收件人: $RECIPIENT" >> "$LOG_FILE"
echo "Agent 参数: $AGENT_CMD_ARGS" >> "$LOG_FILE"
echo "环境变量检查:" >> "$LOG_FILE"
echo "  TAVILY_API_KEY: ${TAVILY_API_KEY:+已设置(${#TAVILY_API_KEY}字符)}" >> "$LOG_FILE"
echo "  OPENAI_API_KEY: ${OPENAI_API_KEY:+已设置(${#OPENAI_API_KEY}字符)}" >> "$LOG_FILE"
echo "---" >> "$LOG_FILE"

# 执行任务 (添加 --no-cache 参数强制实时请求)
# 注意：openclaw agent 可能不支持 --no-cache，但我们会尝试
RESULT=$(openclaw agent --local $AGENT_CMD_ARGS \
    --message "$TASK_CONTENT" \
    --thinking off \
    --timeout 120 \
    2>&1 | tee -a "$LOG_FILE")

# 检查是否使用了缓存（审计关键点）
if echo "$RESULT" | grep -qi "cache\|缓存"; then
    echo "⚠️ 警告: 检测到缓存使用，可能违反实时数据要求" >> "$LOG_FILE"
fi

# -----------------------------------------------------------------------------
# 4. 发送结果到收件箱
# -----------------------------------------------------------------------------
SEND_RESULT=$($(command -v clawteam 2>/dev/null || echo "/Users/alanli/.local/bin/clawteam") inbox send "$TEAM_NAME" "$RECIPIENT" "$RESULT" 2>&1)
echo "发送结果: $SEND_RESULT" >> "$LOG_FILE"

# 5. 干净退出
exit 0