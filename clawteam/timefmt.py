"""Human-friendly timestamp formatting for CLI display."""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from clawteam.config import load_config


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

    tz_name = (load_config().timezone or "UTC").strip() or "UTC"
    if tz_name.upper() == "UTC":
        return dt.astimezone(timezone.utc).isoformat()[:19]

    try:
        local_dt = dt.astimezone(ZoneInfo(tz_name))
    except ZoneInfoNotFoundError:
        return dt.astimezone(timezone.utc).isoformat()[:19]

    suffix = local_dt.tzname() or tz_name
    return f"{local_dt.strftime('%Y-%m-%d %H:%M:%S')} {suffix}"
