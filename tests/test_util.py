from __future__ import annotations

from datetime import datetime

from pulsebridge.util import parse_timestamp


def test_parse_iso_with_timezone() -> None:
    assert parse_timestamp("2026-11-13T23:30:00+08:00") == int(
        datetime.fromisoformat("2026-11-13T23:30:00+08:00").timestamp()
    )


def test_parse_localized_chinese_date() -> None:
    expected = int(datetime(2026, 11, 13, 23, 30).timestamp())
    assert parse_timestamp("2026年11月13日 23:30:00") == expected
    assert parse_timestamp("2026年11月13日 23:30") == expected


def test_parse_epoch_seconds_and_milliseconds() -> None:
    assert parse_timestamp(1794496768) == 1794496768
    assert parse_timestamp(1794496768000) == 1794496768
