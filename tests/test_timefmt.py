from __future__ import annotations

from clawteam.config import ClawTeamConfig, save_config
from clawteam.timefmt import format_timestamp


def test_format_timestamp_defaults_to_utc_without_suffix():
    save_config(ClawTeamConfig())
    assert format_timestamp("2026-03-18T11:19:04+00:00") == "2026-03-18T11:19:04"


def test_format_timestamp_converts_to_configured_timezone():
    save_config(ClawTeamConfig(timezone="Asia/Shanghai"))
    rendered = format_timestamp("2026-03-18T11:19:04+00:00")
    assert rendered == "2026-03-18 19:19:04 CST"


def test_format_timestamp_falls_back_for_invalid_timezone():
    save_config(ClawTeamConfig(timezone="Mars/Base"))
    assert format_timestamp("2026-03-18T11:19:04+00:00") == "2026-03-18T11:19:04"
