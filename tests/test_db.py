from __future__ import annotations

import time

from pulsebridge import analytics
from pulsebridge.db import Database
from pulsebridge.util import start_of_local_day


def _sample(uuid: str, type_: str, start_ts: int, value: float | None, source: str = "Watch", **kwargs):
    return {
        "uuid": uuid,
        "type": type_,
        "start_ts": start_ts,
        "end_ts": start_ts + 60,
        "value": value,
        "value_text": kwargs.get("value_text"),
        "unit": kwargs.get("unit", "count"),
        "source": source,
        "device": "iPhone",
        "metadata": None,
    }


def test_insert_dedupes_by_uuid(tmp_path) -> None:
    db = Database(tmp_path / "test.db")
    sample = _sample("a" * 40, "steps", int(time.time()) - 100, 100.0)
    assert db.insert_samples([sample]) == (1, 0)
    assert db.insert_samples([sample]) == (0, 1)
    assert db.stats()["samples"] == 1
    db.close()


def test_daily_cumulative_uses_max_source(tmp_path) -> None:
    db = Database(tmp_path / "test.db")
    base = start_of_local_day() + 8 * 3600
    db.insert_samples(
        [
            _sample("w1", "steps", base, 100.0, source="Apple Watch"),
            _sample("w2", "steps", base + 3600, 200.0, source="Apple Watch"),
            _sample("p1", "steps", base, 250.0, source="iPhone"),
        ]
    )
    rows = db.daily_cumulative("steps", start_of_local_day())
    assert len(rows) == 1
    assert rows[0]["value"] == 300.0
    db.close()


def test_sleep_night_picks_best_source(tmp_path) -> None:
    db = Database(tmp_path / "test.db")
    day_start = start_of_local_day()
    # 昨晚 23:30 -> 今天 06:30（Watch 记录完整）
    watch_end = day_start + 6 * 3600 + 30 * 60
    watch_start = watch_end - 7 * 3600
    db.insert_samples(
        [
            {
                **_sample(
                    "s1",
                    "sleep_analysis",
                    watch_start,
                    None,
                    source="Apple Watch",
                    value_text="core",
                ),
                "end_ts": watch_start + 4 * 3600,
            },
            {
                **_sample(
                    "s2",
                    "sleep_analysis",
                    watch_start + 4 * 3600,
                    None,
                    source="Apple Watch",
                    value_text="deep",
                ),
                "end_ts": watch_start + 6 * 3600,
            },
            {
                **_sample(
                    "s3",
                    "sleep_analysis",
                    watch_start + 6 * 3600,
                    None,
                    source="Apple Watch",
                    value_text="rem",
                ),
                "end_ts": watch_end,
            },
        ]
    )
    # iPhone 只有一小段，不应被选中
    db.insert_samples(
        [
            {
                **_sample(
                    "i1",
                    "sleep_analysis",
                    watch_start,
                    None,
                    source="iPhone",
                    value_text="asleep_unspecified",
                ),
                "end_ts": watch_start + 3600,
            }
        ]
    )

    nights = analytics.sleep_nights(db, days=2)
    assert nights
    night = nights[-1]
    assert night["source"] == "Apple Watch"
    assert night["asleep_min"] == 420.0
    assert night["deep_min"] == 120.0
    assert night["core_min"] == 240.0
    assert night["rem_min"] == 60.0
    series = analytics.daily_series(db, "sleep", 2)
    assert series[-1]["value"] == 7.0
    db.close()


def test_daily_series_fills_missing_days(tmp_path) -> None:
    db = Database(tmp_path / "test.db")
    rows = analytics.daily_series(db, "steps", 7)
    assert len(rows) == 7
    assert all(row["value"] is None for row in rows)
    db.close()


def test_heart_rate_points_buckets_by_minute(tmp_path) -> None:
    db = Database(tmp_path / "test.db")
    base = (int(time.time()) // 60) * 60 - 120
    db.insert_samples(
        [
            _sample("h1", "heart_rate", base, 70.0, "Watch", unit="count/min"),
            _sample("h2", "heart_rate", base + 10, 80.0, "iPhone", unit="count/min"),
        ]
    )
    points = analytics.heart_rate_points(db, hours=1)
    assert len(points) == 1
    assert points[0][1] == 75.0
    db.close()


def test_legacy_activity_type_is_normalized_on_open(tmp_path) -> None:
    path = tmp_path / "test.db"
    db = Database(path)
    now = int(time.time())
    db.insert_workouts(
        [
            {
                "uuid": "legacy-workout",
                "activity_type": "activity4",
                "start_ts": now,
                "end_ts": now + 1800,
                "duration_s": 1800,
                "distance_m": None,
                "energy_kcal": None,
                "avg_hr": None,
                "max_hr": None,
                "source": "Apple Watch",
                "metadata": None,
            }
        ]
    )
    db.close()

    reopened = Database(path)
    rows = reopened.workout_rows(0)
    assert rows and rows[0]["activity_type"] == "badminton"
    reopened.close()
