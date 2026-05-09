"""Human-friendly timestamp formatting for CLI display."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from clawteam.config import config_path, load_config

_tz_cache: tuple[float, str] | None = None


def _get_timezone() -> str:
    """Return the configured display timezone, cached by config file mtime."""
    global _tz_cache
    try:
        mtime = os.path.getmtime(config_path())
    except OSError:
        mtime = 0.0

    if _tz_cache is not None and _tz_cache[0] == mtime:
        return _tz_cache[1]

    tz_name = (load_config().timezone or "UTC").strip() or "UTC"
    _tz_cache = (mtime, tz_name)
    return tz_name


def _parse_timestamp(value: str) -> datetime | None:
    text = (value or "").strip()
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def format_timestamp(value: str | None) -> str:
    """Format an ISO timestamp using configured display timezone.

    Default behavior stays backward-compatible for UTC by returning the original
    `YYYY-MM-DDTHH:MM:SS` slice. Non-UTC timezones are converted and rendered
    with a timezone abbreviation.
    """
    if not value:
        return ""

    dt = _parse_timestamp(value)
    if dt is None:
        return str(value)[:19]

    tz_name = _get_timezone()
    if tz_name.upper() == "UTC":
        return dt.astimezone(timezone.utc).isoformat()[:19]

    try:
        local_dt = dt.astimezone(ZoneInfo(tz_name))
    except ZoneInfoNotFoundError:
        return dt.astimezone(timezone.utc).isoformat()[:19]

    suffix = local_dt.tzname() or tz_name
    return f"{local_dt.strftime('%Y-%m-%d %H:%M:%S')} {suffix}"
