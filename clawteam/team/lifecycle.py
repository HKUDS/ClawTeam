"""Lifecycle management for team agents (shutdown protocol)."""

from __future__ import annotations

import shutil

from clawteam.paths import ensure_within_root, validate_identifier
from clawteam.team.mailbox import MailboxManager
from clawteam.team.models import MessageType, get_data_dir


class LifecycleManager:
    """Manages agent lifecycle within a team (shutdown, idle, cleanup)."""

    def __init__(self, team_name: str, mailbox: MailboxManager):
        self.team_name = team_name
        self.mailbox = mailbox

    def request_shutdown(
        self,
        from_agent: str,
        to_agent: str,
        reason: str = "",
    ) -> str:
        msg = self.mailbox.send(
            from_agent=from_agent,
            to=to_agent,
            content=f"Shutdown requested.{(' Reason: ' + reason) if reason else ''}",
            msg_type=MessageType.shutdown_request,
            reason=reason or None,
        )
        return msg.request_id

    def approve_shutdown(
        self,
        agent_name: str,
        request_id: str,
        requester_name: str,
    ) -> None:
        self.mailbox.send(
            from_agent=agent_name,
            to=requester_name,
            content=f"{agent_name} shutting down.",
            msg_type=MessageType.shutdown_approved,
            request_id=request_id,
        )

    def reject_shutdown(
        self,
        agent_name: str,
        request_id: str,
        requester_name: str,
        reason: str = "",
    ) -> None:
        self.mailbox.send(
            from_agent=agent_name,
            to=requester_name,
            content=f"Shutdown rejected.{(' Reason: ' + reason) if reason else ''}",
            msg_type=MessageType.shutdown_rejected,
            request_id=request_id,
            reason=reason or None,
        )

    def send_idle(
        self,
        agent_name: str,
        agent_id: str,
        leader_name: str,
        last_task: str = "",
        task_status: str = "",
    ) -> None:
        """Send idle notification to leader."""
        self.mailbox.send(
            from_agent=agent_name,
            to=leader_name,
            msg_type=MessageType.idle,
            agent_id=agent_id,
            last_task=last_task or None,
            status=task_status or None,
        )

    @staticmethod
    def cleanup_team(team_name: str) -> bool:
        validate_identifier(team_name, "team name")
        # Best-effort cleanup of git workspaces
        try:
            from clawteam.workspace import get_workspace_manager
            ws_mgr = get_workspace_manager()
            if ws_mgr:
                ws_mgr.cleanup_team(team_name)
        except Exception:
            pass

        team_dir = ensure_within_root(get_data_dir() / "teams", team_name)
        tasks_dir = ensure_within_root(get_data_dir() / "tasks", team_name)
        costs_dir = ensure_within_root(get_data_dir() / "costs", team_name)
        sessions_dir = ensure_within_root(get_data_dir() / "sessions", team_name)
        cleaned = False
        for d in (team_dir, tasks_dir, costs_dir, sessions_dir):
            if d.exists():
                shutil.rmtree(d)
                cleaned = True
        return cleaned
