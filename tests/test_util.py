from __future__ import annotations

import uuid
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

from pulsebridge.util import (
    display_activity,
    normalize_workout_type,
    parse_timestamp,
    puls_pairing_link,
)


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


def test_parse_apple_health_export_date() -> None:
    utc_midnight = int(datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc).timestamp())
    assert parse_timestamp("2024-01-01 08:00:00 +0800") == utc_midnight
    assert parse_timestamp("2024-01-01 00:00:00 +0000") == utc_midnight


def test_puls_pairing_link_encodes_fields() -> None:
    link = puls_pairing_link("http://192.168.31.111:8765", "tok+en/一二")
    parsed = urlparse(link)
    assert parsed.scheme == "puls"
    assert parsed.netloc == "pair"
    query = parse_qs(parsed.query)
    assert query["url"] == ["http://192.168.31.111:8765"]
    assert query["token"] == ["tok+en/一二"]
    user_id = query["user"][0]
    uuid.UUID(user_id)  # 必须是合法 UUID
    # 同一 Token 的 User ID 稳定，IP 变化不影响身份派生
    assert puls_pairing_link("http://10.0.0.2:8765", "tok+en/一二").endswith(user_id)


def test_healthkit_workout_activity_numbers() -> None:
    # PulsHealth sends activity_<rawValue> for types its name switch doesn't cover.
    assert normalize_workout_type("activity_4") == "badminton"
    assert normalize_workout_type("activity4") == "badminton"
    assert normalize_workout_type("HKWorkoutActivityTypeBadminton") == "badminton"
    assert display_activity("badminton") == "羽毛球"
    assert normalize_workout_type("activity_999") == "other"
