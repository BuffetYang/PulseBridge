from __future__ import annotations

from datetime import datetime

from pulsebridge.config import Config
from pulsebridge.reminders import (
    due_occurrence,
    most_recent_occurrence,
    next_occurrence,
)


def _config(tmp_path, **values) -> Config:
    config = Config(tmp_path / "config.json")
    for key, value in values.items():
        config.set(key, value)
    return config


def test_weekly_occurrence_and_due(tmp_path) -> None:
    now = datetime(2024, 1, 8, 10, 0)  # 周一
    recent = most_recent_occurrence(now, "weekly", 0, 1, "09:00")
    assert recent == datetime(2024, 1, 8, 9, 0)
    assert next_occurrence(now, "weekly", 0, 1, "09:00") == datetime(2024, 1, 15, 9, 0)

    config = _config(
        tmp_path,
        import_reminder_enabled=True,
        import_reminder_frequency="weekly",
        import_reminder_weekday=0,
        import_reminder_time="09:00",
        last_health_import_ts=0,
    )
    assert due_occurrence(config, now) == datetime(2024, 1, 8, 9, 0)

    # 已导入过本周期
    config.set("last_health_import_ts", int(datetime(2024, 1, 8, 9, 30).timestamp()))
    assert due_occurrence(config, now) is None

    # 已提醒过
    config.set("last_health_import_ts", 0)
    config.set("import_reminder_last_shown", datetime(2024, 1, 8, 9, 0).isoformat())
    assert due_occurrence(config, now) is None


def test_weekly_before_time_uses_previous_week(tmp_path) -> None:
    now = datetime(2024, 1, 8, 8, 0)  # 周一 08:00，还没到 09:00
    recent = most_recent_occurrence(now, "weekly", 0, 1, "09:00")
    assert recent == datetime(2024, 1, 1, 9, 0)


def test_monthly_occurrence_and_due(tmp_path) -> None:
    now = datetime(2024, 3, 15, 12, 0)
    recent = most_recent_occurrence(now, "monthly", 0, 1, "09:00")
    assert recent == datetime(2024, 3, 1, 9, 0)
    assert next_occurrence(now, "monthly", 0, 1, "09:00") == datetime(2024, 4, 1, 9, 0)

    config = _config(
        tmp_path,
        import_reminder_enabled=True,
        import_reminder_frequency="monthly",
        import_reminder_day=1,
        import_reminder_time="09:00",
        last_health_import_ts=int(datetime(2024, 2, 20).timestamp()),
    )
    assert due_occurrence(config, now) == datetime(2024, 3, 1, 9, 0)

    config.set("last_health_import_ts", int(datetime(2024, 3, 2).timestamp()))
    assert due_occurrence(config, now) is None


def test_monthly_before_time_uses_previous_month(tmp_path) -> None:
    now = datetime(2024, 2, 1, 8, 0)
    recent = most_recent_occurrence(now, "monthly", 0, 1, "09:00")
    assert recent == datetime(2024, 1, 1, 9, 0)
    assert next_occurrence(now, "monthly", 0, 1, "09:00") == datetime(2024, 2, 1, 9, 0)


def test_disabled_reminder(tmp_path) -> None:
    config = _config(tmp_path, import_reminder_enabled=False)
    assert due_occurrence(config, datetime(2024, 3, 15, 12, 0)) is None
