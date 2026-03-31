"""Thin runtime router for tmux live injection."""

from __future__ import annotations

import json
from datetime import datetime

from clawteam.spawn.tmux_backend import TmuxBackend
from clawteam.team.models import MessageType, TeamMessage
from clawteam.team.routing_policy import DefaultRoutingPolicy, RouteDecision, RuntimeEnvelope


class RuntimeRouter:
    """Normalize inbox messages, ask policy for a decision, then dispatch."""

    def __init__(
        self,
        team_name: str,
        agent_name: str,
        backend: TmuxBackend | None = None,
        policy: DefaultRoutingPolicy | None = None,
        session_agent_name: str | None = None,
    ):
        self.team_name = team_name
        self.inbox_agent_name = agent_name
        self.agent_name = session_agent_name or agent_name
        self.backend = backend or TmuxBackend()
        self.policy = policy or DefaultRoutingPolicy(team_name=team_name)

    def normalize_message(self, message: TeamMessage) -> RuntimeEnvelope:
        source = message.from_agent or "system"
        # Route to the live tmux pane name when the message does not carry an explicit target.
        target = message.to or self.agent_name
        channel = "team" if message.type == MessageType.broadcast else "direct"
        priority = self._priority_for_message(message)
        evidence = []
        if message.summary:
            evidence.append(f"summary: {message.summary}")
        if message.plan_file:
            evidence.append(f"planFile: {message.plan_file}")
        if message.status:
            evidence.append(f"status: {message.status}")
        if message.last_task:
            evidence.append(f"lastTask: {message.last_task}")
        if message.reason:
            evidence.append(f"reason: {message.reason}")
        if message.feedback:
            evidence.append(f"feedback: {message.feedback}")
        if message.request_id:
            evidence.append(f"requestId: {message.request_id}")

        summary = (message.content or "").strip() or f"{message.type.value} from {source}"
        payload = json.loads(message.model_dump_json(by_alias=True, exclude_none=True))

        return RuntimeEnvelope(
            source=source,
            target=target,
            channel=channel,
            priority=priority,
            message_type=message.type.value,
            summary=summary,
            evidence=evidence,
            recommended_next_action=self._recommended_next_action(message),
            payload=payload,
            dedupe_key=message.request_id or f"{source}:{target}:{message.type.value}:{message.timestamp}",
            created_at=message.timestamp,
        )

    def route_message(
        self,
        message: TeamMessage,
        *,
        now: datetime | str | None = None,
    ) -> RouteDecision:
        envelope = self.normalize_message(message)
        decision = self.policy.decide(envelope, now=now)
        self.dispatch(decision, now=now)
        return decision

    def flush_due(self, *, now: datetime | str | None = None) -> list[RouteDecision]:
        decisions = self.policy.flush_due(target_agent=self.agent_name, now=now)
        for decision in decisions:
            self.dispatch(decision, now=now)
        return decisions

    def dispatch(self, decision: RouteDecision, *, now: datetime | str | None = None) -> bool:
        if decision.action != "inject" or not decision.envelope.requires_injection:
            return False

        if not hasattr(self.backend, "inject_runtime_message"):
            self.policy.record_dispatch_result(
                decision,
                success=False,
                now=now,
                error="backend does not support runtime injection",
            )
            return False

        ok, reason = self.backend.inject_runtime_message(
            self.team_name,
            decision.envelope.target,
            decision.envelope,
        )
        self.policy.record_dispatch_result(
            decision,
            success=ok,
            now=now,
            error="" if ok else reason,
        )
        return ok

    @staticmethod
    def _priority_for_message(message: TeamMessage) -> str:
        if message.type in {MessageType.shutdown_request, MessageType.shutdown_approved, MessageType.shutdown_rejected}:
            return "high"
        if message.type in {MessageType.idle, MessageType.plan_approval_request, MessageType.plan_rejected}:
            return "high"
        return "medium"

    @staticmethod
    def _recommended_next_action(message: TeamMessage) -> str | None:
        if message.type == MessageType.plan_approval_request:
            return "Review the plan and respond with an approval decision."
        if message.type == MessageType.idle and message.last_task:
            return f"Check blocker status for {message.last_task}."
        return None
