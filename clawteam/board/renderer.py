"""Renders board data using Rich tables, panels, and columns."""

from __future__ import annotations

import signal
import time

from rich.columns import Columns
from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from clawteam.timefmt import format_timestamp


class BoardRenderer:
    """Renders board data using Rich."""

    def __init__(self, console: Console | None = None):
        self.console = console or Console()

    def render_team_board(self, data: dict) -> None:
        """Render a full team board to the console."""
        self.console.print(self._build_team_board(data))

    def render_overview(self, teams: list[dict]) -> None:
        """Render a multi-team overview table."""
        if not teams:
            self.console.print("[dim]No teams found[/dim]")
            return

        table = Table(title="Team Overview")
        table.add_column("Team", style="cyan")
        table.add_column("Leader")
        table.add_column("Members", justify="right")
        table.add_column("Tasks", justify="right")
        table.add_column("Pending Msgs", justify="right")

        for t in teams:
            table.add_row(
                t["name"],
                t.get("leader", ""),
                str(t["members"]),
                str(t["tasks"]),
                str(t["pendingMessages"]),
            )
        self.console.print(table)

    def render_team_board_live(self, collector, team_name: str, interval: float = 2.0) -> None:
        """Render a live-refreshing team board. Ctrl+C to stop."""
        running = True
        notify_counter = 0
        notify_interval = 5  # auto_notify every N refresh cycles

        def _handle_signal(signum, frame):
            nonlocal running
            running = False

        old_sigint = signal.getsignal(signal.SIGINT)
        old_sigterm = signal.getsignal(signal.SIGTERM)
        signal.signal(signal.SIGINT, _handle_signal)
        signal.signal(signal.SIGTERM, _handle_signal)

        try:
            with Live(console=self.console, refresh_per_second=1, screen=False) as live:
                while running:
                    try:
                        data = collector.collect_team(team_name)
                        renderable = self._build_team_board(data)
                    except ValueError as e:
                        renderable = Text(str(e), style="red")
                        live.update(renderable)
                        break
                    live.update(renderable)

                    # Periodically run conflict auto-notification
                    notify_counter += 1
                    if notify_counter >= notify_interval:
                        notify_counter = 0
                        try:
                            from clawteam.team.mailbox import MailboxManager
                            from clawteam.workspace.conflicts import auto_notify
                            mailbox = MailboxManager(team_name)
                            auto_notify(team_name, mailbox)
                        except Exception:
                            pass

                    time.sleep(interval)
        finally:
            signal.signal(signal.SIGINT, old_sigint)
            signal.signal(signal.SIGTERM, old_sigterm)

    # ------------------------------------------------------------------
    # Internal builders
    # ------------------------------------------------------------------

    def _build_team_board(self, data: dict) -> Group:
        """Build the full team board as a Rich Group of renderables."""
        team = data["team"]
        members = data["members"]
        tasks = data["tasks"]
        summary = data["taskSummary"]

        parts = []

        # 1. Team header panel
        header_text = (
            f"Leader: [cyan]{team.get('leaderName', team.get('leadAgentId', ''))}[/cyan]  |  "
            f"Members: [cyan]{len(members)}[/cyan]  |  "
            f"Created: [dim]{format_timestamp(team['createdAt'])}[/dim]"
        )
        cost = data.get("cost", {})
        total_cents = cost.get("totalCostCents", 0)
        if total_cents > 0:
            budget_cents = team.get("budgetCents", 0)
            if budget_cents > 0:
                header_text += f"  |  Cost: [yellow]${total_cents / 100:.2f} / ${budget_cents / 100:.2f}[/yellow]"
            else:
                header_text += f"  |  Cost: [yellow]${total_cents / 100:.2f}[/yellow]"
        desc = team.get("description", "")
        if desc:
            header_text = f"{desc}\n{header_text}"
        parts.append(Panel(header_text, title=f"Team: {team['name']}", border_style="bright_blue"))

        # 2. Members table
        has_user = any(m.get("user") for m in members)
        mem_table = Table(title="Members")
        mem_table.add_column("Name", style="cyan")
        if has_user:
            mem_table.add_column("User", style="magenta")
        mem_table.add_column("Type")
        mem_table.add_column("Joined", style="dim")
        mem_table.add_column("Inbox", justify="right")
        for m in members:
            inbox_style = "red" if m["inboxCount"] > 0 else "dim"
            row = [m["name"]]
            if has_user:
                row.append(m.get("user", ""))
            row.extend([
                m["agentType"],
                format_timestamp(m["joinedAt"]),
                f"[{inbox_style}]{m['inboxCount']}[/{inbox_style}]",
            ])
            mem_table.add_row(*row)
        parts.append(mem_table)

        # 3. Task board (4-column kanban)
        parts.append(self._build_task_kanban(tasks, summary))

        # 4. Conflict warnings (if any)
        conflicts = data.get("conflicts", {})
        if conflicts.get("totalOverlaps", 0) > 0:
            parts.append(self._build_conflict_panel(conflicts))

        return Group(*parts)

    def _build_conflict_panel(self, conflicts: dict) -> Panel:
        """Build a panel showing file overlap / conflict warnings."""
        overlaps = conflicts.get("overlaps", [])
        high = conflicts.get("highSeverity", 0)
        medium = conflicts.get("mediumSeverity", 0)

        lines: list[str] = []
        for o in overlaps:
            severity = o["severity"]
            style = "red bold" if severity == "high" else "yellow"
            agents = ", ".join(o["agents"])
            lines.append(f"[{style}]{severity.upper()}[/{style}] `{o['file']}` — {agents}")

        body = "\n".join(lines) if lines else "[dim](none)[/dim]"
        title = f"Conflict Warnings ({high} high, {medium} medium)"
        return Panel(body, title=title, border_style="red" if high > 0 else "yellow")

    def _build_task_kanban(self, tasks: dict, summary: dict) -> Panel:
        """Build the 4-column kanban task board."""
        columns_cfg = [
            ("PENDING", "pending", "yellow"),
            ("IN PROGRESS", "in_progress", "cyan"),
            ("COMPLETED", "completed", "green"),
            ("BLOCKED", "blocked", "red"),
        ]

        panels = []
        for label, key, color in columns_cfg:
            count = summary.get(key, 0)
            items = tasks.get(key, [])
            lines = []
            for t in items:
                task_id = t.get("id", "")[:8]
                subject = t.get("subject", "")
                owner = t.get("owner", "") or "-"
                lines.append(f"[bold]#{task_id}[/bold] {subject}")
                lines.append(f"  owner: {owner}")
                if key == "in_progress" and t.get("lockedBy"):
                    lines.append(f"  locked by: [yellow]{t['lockedBy']}[/yellow]")
                if key == "blocked" and t.get("blockedBy"):
                    lines.append(f"  blocked by: {', '.join(t['blockedBy'])}")
                lines.append("")

            body = "\n".join(lines).rstrip() if lines else "[dim]  (none)[/dim]"
            panels.append(
                Panel(
                    body,
                    title=f"{label} ({count})",
                    border_style=color,
                    expand=True,
                )
            )

        total = summary.get("total", 0)
        return Panel(
            Columns(panels, equal=True, expand=True),
            title=f"Task Board ({total} total)",
        )
