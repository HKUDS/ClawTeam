"""Hook configuration and execution for ClawTeam events."""

from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
from dataclasses import asdict
from typing import Any

from pydantic import BaseModel

from clawteam.events.bus import EventBus
from clawteam.events.types import HarnessEvent


class HookDef(BaseModel):
    """A user-configurable event hook."""

    event: str  # event type name, e.g. "WorkerExit"
    action: str = "shell"  # "shell" | "python"
    command: str = ""  # shell command or dotted Python callable path
    priority: int = 0
    enabled: bool = True


class HookManager:
    """Loads HookDef entries and registers them on an EventBus."""

    def __init__(self, bus: EventBus) -> None:
        self._bus = bus
        self._registered: list[tuple[type, Any]] = []  # (event_type, handler)

    def load_hooks(self, hooks: list[HookDef]) -> int:
        """Register all enabled hooks. Returns count of hooks registered."""
        count = 0
        for hook in hooks:
            if not hook.enabled:
                continue
            if self.register_hook(hook):
                count += 1
        return count

    def register_hook(self, hook: HookDef) -> bool:
        """Register a single hook on the bus. Returns True on success."""
        event_type = _resolve_event_type(hook.event)
        if event_type is None:
            return False

        if hook.action == "shell":
            handler = _make_shell_handler(hook.command)
        elif hook.action == "python":
            handler = _resolve_python_callable(hook.command)
            if handler is None:
                return False
        else:
            return False

        self._bus.subscribe(event_type, handler, priority=hook.priority)
        self._registered.append((event_type, handler))
        return True

    def unregister_all(self) -> None:
        """Remove all hooks registered by this manager."""
        for event_type, handler in self._registered:
            self._bus.unsubscribe(event_type, handler)
        self._registered.clear()


def _resolve_event_type(name: str) -> type[HarnessEvent] | None:
    """Look up an event class by name. Supports built-in and plugin-registered types."""
    from clawteam.events.bus import resolve_event_type
    return resolve_event_type(name)


def _make_shell_handler(command: str):
    """Create a handler that runs a shell command with event data as env vars."""

    def handler(event: HarnessEvent) -> int | None:
        env = os.environ.copy()
        env["CLAWTEAM_EVENT_TYPE"] = type(event).__name__
        for key, value in asdict(event).items():
            formatted = _format_env_value(value)
            env[f"CLAWTEAM_{key.upper()}"] = formatted
            # Legacy alias for backward compatibility
            env[f"OH_{key.upper()}"] = formatted
        try:
            result = subprocess.run(
                command,
                shell=True,
                env=env,
                capture_output=True,
                timeout=30,
            )
            return result.returncode
        except Exception as exc:
            print(f"[clawteam] hook error: {exc}", file=sys.stderr)
            return None

    return handler


def _format_env_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return ",".join(str(item) for item in value)
    if isinstance(value, dict):
        return json.dumps(value, sort_keys=True)
    return str(value)


def _resolve_python_callable(dotted_path: str):
    """Import and return a callable from a dotted path like 'pkg.mod.func'."""
    try:
        module_path, _, attr_name = dotted_path.rpartition(".")
        if not module_path:
            return None
        mod = importlib.import_module(module_path)
        return getattr(mod, attr_name, None)
    except Exception:
        return None
