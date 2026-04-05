"""Abstract base class for agent spawn backends."""

from __future__ import annotations

from abc import ABC, abstractmethod


class SpawnBackend(ABC):
    """Base class for different ways to spawn team agents."""

    @abstractmethod
    def spawn(
        self,
        command: list[str],
        agent_name: str,
        agent_id: str,
        agent_type: str,
        team_name: str,
        prompt: str | None = None,
        env: dict[str, str] | None = None,
        cwd: str | None = None,
        skip_permissions: bool = False,
        system_prompt: str | None = None,
        is_leader: bool = False,
    ) -> str:
        """Spawn a new agent process. Returns a status message."""

    @abstractmethod
    def list_running(self) -> list[dict[str, str]]:
        """List currently running agents."""
