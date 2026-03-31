"""MCP tool registry for ClawTeam."""

from clawteam.mcp.tools.board import board_overview, board_team
from clawteam.mcp.tools.cost import cost_summary
from clawteam.mcp.tools.mailbox import (
    mailbox_broadcast,
    mailbox_peek,
    mailbox_peek_count,
    mailbox_receive,
    mailbox_send,
)
from clawteam.mcp.tools.plan import plan_approve, plan_get, plan_reject, plan_submit
from clawteam.mcp.tools.task import task_create, task_get, task_list, task_stats, task_update
from clawteam.mcp.tools.team import (
    team_create,
    team_get,
    team_list,
    team_member_add,
    team_members_list,
)
from clawteam.mcp.tools.workspace import (
    workspace_agent_diff,
    workspace_agent_summary,
    workspace_cross_branch_log,
    workspace_file_owners,
)

TOOL_FUNCTIONS = [
    team_list,
    team_get,
    team_members_list,
    team_create,
    team_member_add,
    task_list,
    task_get,
    task_stats,
    task_create,
    task_update,
    mailbox_send,
    mailbox_broadcast,
    mailbox_receive,
    mailbox_peek,
    mailbox_peek_count,
    plan_submit,
    plan_get,
    plan_approve,
    plan_reject,
    board_overview,
    board_team,
    cost_summary,
    workspace_agent_diff,
    workspace_file_owners,
    workspace_cross_branch_log,
    workspace_agent_summary,
]

__all__ = ["TOOL_FUNCTIONS"]
