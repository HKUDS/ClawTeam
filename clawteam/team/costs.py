"""Cost tracking for multi-agent teams."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, Field

from clawteam.fileutil import atomic_write_text, file_locked
from clawteam.paths import ensure_within_root, validate_identifier
from clawteam.team.models import get_data_dir


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class CostEvent(BaseModel):
    """A single cost event reported by an agent."""

    model_config = {"populate_by_name": True}

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:8])
    agent_name: str = Field(alias="agentName")
    provider: str = ""
    model: str = ""
    input_tokens: int = Field(default=0, alias="inputTokens")
    output_tokens: int = Field(default=0, alias="outputTokens")
    cost_cents: float = Field(default=0.0, alias="costCents")
    reported_at: str = Field(default_factory=_now_iso, alias="reportedAt")


class CostSummary(BaseModel):
    """Aggregated cost summary for a team."""

    model_config = {"populate_by_name": True}

    team_name: str = Field(alias="teamName")
    total_cost_cents: float = Field(default=0.0, alias="totalCostCents")
    total_input_tokens: int = Field(default=0, alias="totalInputTokens")
    total_output_tokens: int = Field(default=0, alias="totalOutputTokens")
    by_agent: dict[str, float] = Field(default_factory=dict, alias="byAgent")
    event_count: int = Field(default=0, alias="eventCount")


class _CostCacheEntry(BaseModel):
    """Cached contribution from a single event file."""

    model_config = {"populate_by_name": True}

    agent_name: str = Field(alias="agentName")
    input_tokens: int = Field(default=0, alias="inputTokens")
    output_tokens: int = Field(default=0, alias="outputTokens")
    cost_cents: float = Field(default=0.0, alias="costCents")
    size: int = 0
    mtime_ns: int = Field(default=0, alias="mtimeNs")


class _CostSummaryCache(BaseModel):
    """Internal rolling cache stored alongside cost events."""

    model_config = {"populate_by_name": True}

    team_name: str = Field(alias="teamName")
    total_cost_cents: float = Field(default=0.0, alias="totalCostCents")
    total_input_tokens: int = Field(default=0, alias="totalInputTokens")
    total_output_tokens: int = Field(default=0, alias="totalOutputTokens")
    by_agent: dict[str, float] = Field(default_factory=dict, alias="byAgent")
    event_count: int = Field(default=0, alias="eventCount")
    files: dict[str, _CostCacheEntry] = Field(default_factory=dict)


def _costs_root(team_name: str) -> Path:
    d = ensure_within_root(get_data_dir() / "costs", validate_identifier(team_name, "team name"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def _summary_cache_path(team_name: str) -> Path:
    return _costs_root(team_name) / "summary.json"


def _read_event_file(path: Path) -> CostEvent | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return CostEvent.model_validate(data)
    except Exception:
        return None


def _empty_summary_cache(team_name: str) -> _CostSummaryCache:
    return _CostSummaryCache(team_name=team_name)


def _load_summary_cache(team_name: str) -> _CostSummaryCache | None:
    path = _summary_cache_path(team_name)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        cache = _CostSummaryCache.model_validate(data)
        if cache.team_name != team_name:
            return None
        return cache
    except Exception:
        return None


def _write_summary_cache(team_name: str, cache: _CostSummaryCache) -> None:
    atomic_write_text(
        _summary_cache_path(team_name),
        cache.model_dump_json(indent=2, by_alias=True),
    )


def _normalize_cost(value: float) -> float:
    return 0.0 if abs(value) < 1e-12 else value


def _add_cache_entry(
    cache: _CostSummaryCache, filename: str, entry: _CostCacheEntry
) -> None:
    cache.total_cost_cents += entry.cost_cents
    cache.total_input_tokens += entry.input_tokens
    cache.total_output_tokens += entry.output_tokens
    cache.by_agent[entry.agent_name] = (
        cache.by_agent.get(entry.agent_name, 0.0) + entry.cost_cents
    )
    cache.files[filename] = entry
    cache.event_count = len(cache.files)


def _remove_cache_entry(cache: _CostSummaryCache, filename: str) -> None:
    entry = cache.files.pop(filename, None)
    if entry is None:
        return
    cache.total_cost_cents = _normalize_cost(cache.total_cost_cents - entry.cost_cents)
    cache.total_input_tokens -= entry.input_tokens
    cache.total_output_tokens -= entry.output_tokens
    remaining = _normalize_cost(cache.by_agent.get(entry.agent_name, 0.0) - entry.cost_cents)
    if remaining == 0.0:
        cache.by_agent.pop(entry.agent_name, None)
    else:
        cache.by_agent[entry.agent_name] = remaining
    cache.event_count = len(cache.files)


def _cache_entry_from_event(path: Path, event: CostEvent) -> _CostCacheEntry:
    stat = path.stat()
    return _CostCacheEntry(
        agent_name=event.agent_name,
        input_tokens=event.input_tokens,
        output_tokens=event.output_tokens,
        cost_cents=event.cost_cents,
        size=stat.st_size,
        mtime_ns=stat.st_mtime_ns,
    )


def _sync_summary_cache(team_name: str) -> _CostSummaryCache:
    with file_locked(_summary_cache_path(team_name)):
        root = _costs_root(team_name)
        cache = _load_summary_cache(team_name) or _empty_summary_cache(team_name)
        cache_exists = _summary_cache_path(team_name).exists()
        changed = not cache_exists

        current_files = {path.name: path for path in sorted(root.glob("cost-*.json"))}

        for filename in list(cache.files):
            if filename not in current_files:
                _remove_cache_entry(cache, filename)
                changed = True

        for filename, path in current_files.items():
            stat = path.stat()
            cached_entry = cache.files.get(filename)
            if (
                cached_entry is not None
                and cached_entry.size == stat.st_size
                and cached_entry.mtime_ns == stat.st_mtime_ns
            ):
                continue

            if cached_entry is not None:
                _remove_cache_entry(cache, filename)
                changed = True

            event = _read_event_file(path)
            if event is None:
                continue

            _add_cache_entry(cache, filename, _cache_entry_from_event(path, event))
            changed = True

        if changed:
            _write_summary_cache(team_name, cache)
        return cache


def _record_event_in_summary_cache(team_name: str, path: Path, event: CostEvent) -> None:
    with file_locked(_summary_cache_path(team_name)):
        cache = _load_summary_cache(team_name) or _empty_summary_cache(team_name)
        _remove_cache_entry(cache, path.name)
        _add_cache_entry(cache, path.name, _cache_entry_from_event(path, event))
        _write_summary_cache(team_name, cache)


def _cache_to_summary(cache: _CostSummaryCache) -> CostSummary:
    return CostSummary(
        team_name=cache.team_name,
        total_cost_cents=cache.total_cost_cents,
        total_input_tokens=cache.total_input_tokens,
        total_output_tokens=cache.total_output_tokens,
        by_agent=dict(cache.by_agent),
        event_count=cache.event_count,
    )


class CostStore:
    """File-based cost event store.

    Each event is stored as a separate JSON file:
    ``{data_dir}/costs/{team}/cost-{timestamp}-{id}.json``
    """

    def __init__(self, team_name: str):
        self.team_name = team_name

    def report(
        self,
        agent_name: str,
        provider: str = "",
        model: str = "",
        input_tokens: int = 0,
        output_tokens: int = 0,
        cost_cents: float = 0.0,
    ) -> CostEvent:
        event = CostEvent(
            agent_name=agent_name,
            provider=provider,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_cents=cost_cents,
        )
        ts = event.reported_at.replace(":", "-").replace("+", "p")
        filename = f"cost-{ts}-{event.id}.json"
        path = _costs_root(self.team_name) / filename
        tmp = path.with_suffix(".tmp")
        tmp.write_text(
            event.model_dump_json(indent=2, by_alias=True), encoding="utf-8"
        )
        import os
        os.replace(str(tmp), str(path))
        try:
            _record_event_in_summary_cache(self.team_name, path, event)
        except Exception:
            pass
        return event

    def list_events(self, agent_name: str = "") -> list[CostEvent]:
        root = _costs_root(self.team_name)
        events = []
        for f in sorted(root.glob("cost-*.json")):
            event = _read_event_file(f)
            if event is None:
                continue
            if agent_name and event.agent_name != agent_name:
                continue
            events.append(event)
        return events

    def summary(self) -> CostSummary:
        return _cache_to_summary(_sync_summary_cache(self.team_name))
