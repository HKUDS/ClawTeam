"""Phase state machine for harness orchestration."""

from __future__ import annotations

import json
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# Phase is an open str — not an Enum. Plugins/templates can define custom phases.
Phase = str

DISCUSS: Phase = "discuss"
PLAN: Phase = "plan"
EXECUTE: Phase = "execute"
VERIFY: Phase = "verify"
SHIP: Phase = "ship"

DEFAULT_PHASES: list[Phase] = [DISCUSS, PLAN, EXECUTE, VERIFY, SHIP]

DEFAULT_PHASE_ROLES: dict[str, str] = {
    "discuss": "planner",
    "plan": "planner",
    "execute": "executor",
    "verify": "evaluator",
    "ship": "",
}


class PhaseState(BaseModel):
    """Persisted state of a harness run."""

    harness_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    team_name: str = ""
    current_phase: str = DISCUSS
    phases: list[str] = Field(default_factory=lambda: list(DEFAULT_PHASES))
    phase_roles: dict[str, str] = Field(default_factory=lambda: dict(DEFAULT_PHASE_ROLES))
    phase_history: list[dict[str, Any]] = Field(default_factory=list)
    artifacts: dict[str, str] = Field(default_factory=dict)
    goal: str = ""
    cli: str = "claude"
    agent_count: int = 3
    created_at: str = Field(default_factory=_now_iso)
    updated_at: str = Field(default_factory=_now_iso)


class PhaseGate(ABC):
    """Gate that must pass before a phase can advance."""

    @abstractmethod
    def check(self, state: PhaseState) -> tuple[bool, str]:
        """Return (passed, reason)."""


class ArtifactRequiredGate(PhaseGate):
    """Requires specific artifacts to exist."""

    def __init__(self, artifact_names: list[str]):
        self.artifact_names = artifact_names

    def check(self, state: PhaseState) -> tuple[bool, str]:
        missing = [n for n in self.artifact_names if n not in state.artifacts]
        if missing:
            return False, f"Missing artifacts: {', '.join(missing)}"
        return True, ""


class AllTasksCompleteGate(PhaseGate):
    """Requires all team tasks to be completed."""

    def check(self, state: PhaseState) -> tuple[bool, str]:
        from clawteam.team.models import TaskStatus
        from clawteam.team.tasks import TaskStore
        store = TaskStore(state.team_name)
        tasks = store.list_tasks()
        incomplete = [t for t in tasks if t.status != TaskStatus.completed]
        if incomplete:
            return False, f"{len(incomplete)} task(s) not completed"
        return True, ""


class HumanApprovalGate(PhaseGate):
    """Requires explicit human approval before advancing.

    Approval is stored as an artifact: approval-{phase_name}.json
    """

    def __init__(self, phase_name: str):
        self._artifact_name = f"approval-{phase_name}.json"

    def check(self, state: PhaseState) -> tuple[bool, str]:
        if self._artifact_name not in state.artifacts:
            return False, f"Human approval required: clawteam harness approve {state.team_name}"
        return True, ""


class PhaseRunner:
    """Manages phase transitions with gate checking."""

    def __init__(self, state: PhaseState) -> None:
        self.state = state
        self._gates: dict[str, list[PhaseGate]] = {}

    def register_gate(self, phase: str, gate: PhaseGate) -> None:
        """Register a gate that must pass before *phase* can advance."""
        self._gates.setdefault(phase, []).append(gate)

    def can_advance(self) -> tuple[bool, str]:
        """Check if the current phase can advance."""
        gates = self._gates.get(self.state.current_phase, [])
        for gate in gates:
            ok, reason = gate.check(self.state)
            if not ok:
                return False, reason
        return True, ""

    def advance(self) -> str | None:
        """Advance to the next phase. Returns new phase or None if blocked/finished."""
        ok, reason = self.can_advance()
        if not ok:
            return None

        phases = self.state.phases
        idx = phases.index(self.state.current_phase)
        if idx >= len(phases) - 1:
            return None  # already at last phase

        old_phase = self.state.current_phase
        new_phase = phases[idx + 1]

        self.state.phase_history.append({
            "phase": old_phase,
            "completed_at": _now_iso(),
        })
        self.state.current_phase = new_phase
        self.state.updated_at = _now_iso()

        # Emit PhaseTransition event
        try:
            from clawteam.events.global_bus import get_event_bus
            from clawteam.events.types import PhaseTransition
            get_event_bus().emit(PhaseTransition(
                team_name=self.state.team_name,
                from_phase=old_phase,
                to_phase=new_phase,
                artifacts=list(self.state.artifacts.keys()),
            ))
        except Exception:
            pass

        return new_phase

    def rollback(self, to_phase: str) -> str | None:
        """Rollback to a previous phase."""
        phases = self.state.phases
        if to_phase not in phases:
            return None
        target_idx = phases.index(to_phase)
        current_idx = phases.index(self.state.current_phase)
        if target_idx >= current_idx:
            return None  # can't rollback forward
        self.state.current_phase = to_phase
        self.state.updated_at = _now_iso()
        return to_phase

    # ── Persistence ───────────────────────────────────────────────────

    def save(self, base_dir: Path) -> Path:
        """Save state to disk."""
        harness_dir = base_dir / self.state.team_name / self.state.harness_id
        harness_dir.mkdir(parents=True, exist_ok=True)
        state_path = harness_dir / "state.json"
        state_path.write_text(
            self.state.model_dump_json(indent=2), encoding="utf-8"
        )
        return state_path

    @classmethod
    def load(cls, state_path: Path) -> PhaseRunner:
        """Load state from disk."""
        data = json.loads(state_path.read_text(encoding="utf-8"))
        state = PhaseState.model_validate(data)
        return cls(state)
