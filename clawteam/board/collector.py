"""Aggregates team/task/inbox data into plain dicts for rendering."""

from __future__ import annotations

import json

from clawteam.team.mailbox import MailboxManager
from clawteam.team.manager import TeamManager
from clawteam.team.models import TaskStatus
from clawteam.team.tasks import TaskStore


class BoardCollector:
    """Aggregates team/task/inbox data into plain dicts."""

    def collect_team(self, team_name: str) -> dict:
        """Collect full board data for a single team.

        Returns a dict with keys: team, members, tasks, taskSummary.
        Raises ValueError if the team does not exist.
        """
        config = TeamManager.get_team(team_name)
        if not config:
            raise ValueError(f"Team '{team_name}' not found")

        mailbox = MailboxManager(team_name)
        store = TaskStore(team_name)

        # Members with inbox counts
        members = []
        for m in config.members:
            inbox_name = f"{m.user}_{m.name}" if m.user else m.name
            entry = {
                "name": m.name,
                "agentId": m.agent_id,
                "agentType": m.agent_type,
                "joinedAt": m.joined_at,
                "inboxCount": mailbox.peek_count(inbox_name),
            }
            if m.user:
                entry["user"] = m.user
            members.append(entry)

        # Tasks grouped by status
        all_tasks = store.list_tasks()
        grouped: dict[str, list[dict]] = {
            "pending": [],
            "in_progress": [],
            "completed": [],
            "blocked": [],
        }
        for t in all_tasks:
            td = json.loads(t.model_dump_json(by_alias=True, exclude_none=True))
            grouped[t.status.value].append(td)

        summary = {
            s: len(grouped[s]) for s in grouped
        }
        summary["total"] = len(all_tasks)

        # Find leader name
        leader_name = ""
        for m in config.members:
            if m.agent_id == config.lead_agent_id:
                leader_name = m.name
                break

        # Collect message history from event log (persistent, never consumed)
        all_messages = []
        try:
            events = mailbox.get_event_log(limit=200)
            for msg in events:
                all_messages.append(
                    json.loads(msg.model_dump_json(by_alias=True, exclude_none=True))
                )
        except Exception:
            pass

        # Cost summary
        cost_data = {}
        try:
            from clawteam.team.costs import CostStore
            cost_store = CostStore(team_name)
            cost_summary = cost_store.summary()
            cost_data = {
                "totalCostCents": cost_summary.total_cost_cents,
                "totalInputTokens": cost_summary.total_input_tokens,
                "totalOutputTokens": cost_summary.total_output_tokens,
                "eventCount": cost_summary.event_count,
                "byAgent": cost_summary.by_agent,
            }
        except Exception:
            pass

        # Conflict/overlap data
        conflict_data = {}
        try:
            from clawteam.workspace.conflicts import detect_overlaps
            overlaps = detect_overlaps(team_name)
            conflict_data = {
                "overlaps": [
                    {"file": o["file"], "agents": o["agents"], "severity": o["severity"]}
                    for o in overlaps
                ],
                "totalOverlaps": len(overlaps),
                "highSeverity": sum(1 for o in overlaps if o["severity"] == "high"),
                "mediumSeverity": sum(1 for o in overlaps if o["severity"] == "medium"),
            }
        except Exception:
            pass

        return {
            "team": {
                "name": config.name,
                "description": config.description,
                "leadAgentId": config.lead_agent_id,
                "leaderName": leader_name,
                "createdAt": config.created_at,
                "budgetCents": config.budget_cents,
            },
            "members": members,
            "tasks": grouped,
            "taskSummary": summary,
            "messages": all_messages,
            "cost": cost_data,
            "conflicts": conflict_data,
        }

    def collect_overview(self) -> list[dict]:
        """Collect summary data for all teams.

        Returns a list of dicts with keys: name, description, leader,
        members, tasks, pendingMessages.
        """
        teams_meta = TeamManager.discover_teams()
        result = []
        for meta in teams_meta:
            name = meta["name"]
            try:
                data = self.collect_team(name)
                total_inbox = sum(m["inboxCount"] for m in data["members"])
                leader = data["team"].get("leaderName", "")
                result.append({
                    "name": name,
                    "description": meta.get("description", ""),
                    "leader": leader,
                    "members": len(data["members"]),
                    "tasks": data["taskSummary"]["total"],
                    "pendingMessages": total_inbox,
                })
            except Exception:
                result.append({
                    "name": name,
                    "description": meta.get("description", ""),
                    "leader": "",
                    "members": meta.get("memberCount", 0),
                    "tasks": 0,
                    "pendingMessages": 0,
                })
        return result
