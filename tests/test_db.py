from __future__ import annotations

import time
from datetime import date

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
    segments = analytics.sleep_segments(db, night)
    assert segments
    assert {stage for _start, _end, stage in segments} == {"core", "deep", "rem"}
    series = analytics.daily_series(db, "sleep", 2)
    assert series[-1]["value"] == 7.0
    db.close()


def test_resting_heart_rate_estimates_from_sleep_hr(tmp_path) -> None:
    db = Database(tmp_path / "test.db")
    day_start = start_of_local_day()
    sleep_start = day_start - 3600  # 昨晚 23:00
    sleep_end = day_start + 6 * 3600 + 30 * 60  # 今早 06:30
    db.insert_samples(
        [
            {
                **_sample(
                    "sleep1", "sleep_analysis", sleep_start, None, value_text="core"
                ),
                "end_ts": sleep_end,
            }
        ]
    )
    # 睡眠期间 30 个心率样本：50..79 bpm
    hr_rows = [
        _sample(f"hr{i}", "heart_rate", sleep_start + 600 + i * 600, 50.0 + i, unit="count/min")
        for i in range(30)
    ]
    db.insert_samples(hr_rows)

    series = analytics.resting_heart_rate_series(db, 2)
    today = series[-1]
    assert today["estimated"] is True
    assert today["value"] is not None
    assert 69.0 <= today["value"] <= 71.5  # 睡眠心率的 70% 分位
    db.close()


def test_resting_heart_rate_official_beats_estimate(tmp_path) -> None:
    db = Database(tmp_path / "test.db")
    day_start = start_of_local_day()
    db.insert_samples(
        [
            _sample(
                "rest1",
                "resting_heart_rate",
                day_start + 60,
                61.0,
                unit="count/min",
            )
        ]
    )
    series = analytics.resting_heart_rate_series(db, 2)
    today = series[-1]
    assert today["estimated"] is False
    assert today["value"] == 61.0
    db.close()


def test_resting_heart_rate_falls_back_to_night_window(tmp_path) -> None:
    db = Database(tmp_path / "test.db")
    day_start = start_of_local_day()
    hr_rows = [
        _sample(f"n{i}", "heart_rate", day_start + 600 + i * 600, 55.0 + i, unit="count/min")
        for i in range(30)
    ]
    db.insert_samples(hr_rows)
    series = analytics.resting_heart_rate_series(db, 2)
    today = series[-1]
    assert today["estimated"] is True
    assert today["value"] is not None
    assert 70.0 <= today["value"] <= 76.0
    db.close()


def test_hourly_step_totals_uses_max_source_per_hour(tmp_path) -> None:
    db = Database(tmp_path / "test.db")
    day_start = start_of_local_day()
    db.insert_samples(
        [
            _sample("sw1", "steps", day_start + 8 * 3600 + 600, 100.0, "Apple Watch"),
            _sample("si1", "steps", day_start + 8 * 3600 + 1200, 150.0, "iPhone"),
            _sample("sw2", "steps", day_start + 9 * 3600 + 60, 30.0, "Apple Watch"),
        ]
    )
    rows = db.hourly_step_totals(day_start)
    assert [row["value"] for row in rows] == [150.0, 30.0]
    assert analytics.estimated_stand_hours(db, day_start, threshold=50) == 1.0
    db.close()


def test_activity_rings_merge_live_samples_and_summary(tmp_path) -> None:
    db = Database(tmp_path / "test.db")
    day = date.today().isoformat()
    day_start = start_of_local_day()
    db.insert_samples(
        [
            _sample("ae1", "active_energy", day_start + 3600, 100.0, unit="kcal"),
            _sample("st1", "steps", day_start + 8 * 3600 + 60, 120.0),
        ]
    )
    db.insert_workouts(
        [
            {
                "uuid": "w-ring",
                "activity_type": "running",
                "start_ts": day_start + 7 * 3600,
                "end_ts": day_start + 7 * 3600 + 1800,
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
    db.upsert_activity_summaries(
        [
            {
                "date": day,
                "move_kcal": 9.0,
                "move_goal_kcal": 500.0,
                "exercise_min": 60.0,
                "exercise_goal_min": 60.0,
                "stand_hours": 0.0,
                "stand_goal_hours": 6.0,
            }
        ]
    )

    rings = analytics.activity_rings(db)
    assert rings["move"] == 100.0  # 实时样本高于导入摘要
    assert rings["exercise"] == 60.0  # 摘要高于 30 分钟训练
    assert rings["stand"] == 1.0  # 由步数估算
    assert rings["move_goal"] == 500.0
    assert rings["stand_goal"] == 6.0
    assert rings["live"] is True
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


def test_content_fingerprint_dedupes_across_channels(tmp_path) -> None:
    db = Database(tmp_path / "test.db")
    base = int(time.time()) - 3600
    first = _sample("puls-uuid", "heart_rate", base, 72.0, "Apple Watch", unit="count/min")
    second = _sample("apple-hash", "heart_rate", base, 72.0, "iPhone", unit="count/min")
    assert db.insert_samples([first]) == (1, 0)
    assert db.insert_samples([second]) == (0, 1)
    assert db.stats()["samples"] == 1

    workout_a = {
        "uuid": "puls-workout",
        "activity_type": "running",
        "start_ts": base,
        "end_ts": base + 1800,
        "duration_s": 1800,
        "distance_m": 5000,
        "energy_kcal": 300,
        "avg_hr": 150,
        "max_hr": 170,
        "source": "Apple Watch",
        "metadata": None,
    }
    workout_b = dict(workout_a, uuid="apple-workout", source="iPhone")
    assert db.insert_workouts([workout_a]) == (1, 0)
    assert db.insert_workouts([workout_b]) == (0, 1)
    assert db.stats()["workouts"] == 1
    db.close()


def test_legacy_sample_type_and_fingerprint_migration(tmp_path) -> None:
    path = tmp_path / "test.db"
    db = Database(path)
    base = int(time.time()) - 3600
    db.insert_samples(
        [_sample("legacy-speed", "walkingspeed", base, 4.5, "iPhone", unit="km/hr")]
    )
    db.close()

    reopened = Database(path)
    row = reopened.latest_sample("walking_speed")
    assert row is not None
    assert row["value"] == 4.5
    assert row["fingerprint"]
    assert reopened.latest_sample("walkingspeed") is None
    reopened.close()


def test_percentage_display_scaling() -> None:
    assert analytics.display_value("oxygen_saturation", 0.96) == 96
    assert analytics.display_value("oxygen_saturation", 96) == 96
    assert analytics.display_value("body_fat", 0.212) == 21.2
    assert analytics.display_value("steps", 0.5) == 0.5
