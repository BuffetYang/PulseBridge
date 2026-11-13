"""Apple Health 导出导入提醒：每周几 / 每月几号，到点提醒一次。"""

from __future__ import annotations

from datetime import datetime, time, timedelta


def _time_of_day(value: str | None) -> time:
    try:
        hour, minute = str(value or "09:00").strip().split(":")
        hour = max(0, min(23, int(hour)))
        minute = max(0, min(59, int(minute)))
        return time(hour, minute)
    except (ValueError, TypeError):
        return time(9, 0)


def _settings(config) -> tuple[str, int, int, str]:
    frequency = str(config.get("import_reminder_frequency") or "monthly").lower()
    if frequency not in ("weekly", "monthly"):
        frequency = "monthly"
    weekday = max(0, min(6, int(config.get("import_reminder_weekday") or 0)))
    day = max(1, min(28, int(config.get("import_reminder_day") or 1)))
    clock = str(config.get("import_reminder_time") or "09:00")
    return frequency, weekday, day, clock


def most_recent_occurrence(
    now: datetime,
    frequency: str,
    weekday: int = 0,
    day: int = 1,
    time_str: str = "09:00",
) -> datetime | None:
    clock = _time_of_day(time_str)
    if frequency == "weekly":
        weekday = max(0, min(6, int(weekday)))
        days_since = (now.weekday() - weekday) % 7
        scheduled_date = (now - timedelta(days=days_since)).date()
        candidate = datetime.combine(scheduled_date, clock)
        if candidate > now:
            candidate -= timedelta(days=7)
        return candidate
    if frequency == "monthly":
        day = max(1, min(28, int(day)))
        candidate = datetime(now.year, now.month, day, clock.hour, clock.minute)
        if candidate > now:
            first_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            previous = first_of_month - timedelta(days=1)
            candidate = datetime(
                previous.year, previous.month, day, clock.hour, clock.minute
            )
        return candidate
    return None


def next_occurrence(
    now: datetime,
    frequency: str,
    weekday: int = 0,
    day: int = 1,
    time_str: str = "09:00",
) -> datetime | None:
    clock = _time_of_day(time_str)
    if frequency == "weekly":
        weekday = max(0, min(6, int(weekday)))
        days_ahead = (weekday - now.weekday()) % 7
        candidate = datetime.combine(
            (now + timedelta(days=days_ahead)).date(), clock
        )
        if candidate <= now:
            candidate += timedelta(days=7)
        return candidate
    if frequency == "monthly":
        day = max(1, min(28, int(day)))
        candidate = datetime(now.year, now.month, day, clock.hour, clock.minute)
        if candidate <= now:
            year = now.year + (1 if now.month == 12 else 0)
            month = 1 if now.month == 12 else now.month + 1
            candidate = datetime(year, month, day, clock.hour, clock.minute)
        return candidate
    return None


def most_recent_for_config(config, now: datetime) -> datetime | None:
    frequency, weekday, day, clock = _settings(config)
    return most_recent_occurrence(now, frequency, weekday, day, clock)


def next_for_config(config, now: datetime) -> datetime | None:
    frequency, weekday, day, clock = _settings(config)
    return next_occurrence(now, frequency, weekday, day, clock)


def due_occurrence(config, now: datetime | None = None) -> datetime | None:
    """如果当前到点且自上次导入后还没提醒过，返回本次应提醒的时间。"""
    if not bool(config.get("import_reminder_enabled")):
        return None
    now = now or datetime.now()
    occurrence = most_recent_for_config(config, now)
    if occurrence is None:
        return None
    last_import = int(config.get("last_health_import_ts") or 0)
    if occurrence.timestamp() <= last_import:
        return None
    if str(config.get("import_reminder_last_shown") or "") == occurrence.isoformat():
        return None
    return occurrence
