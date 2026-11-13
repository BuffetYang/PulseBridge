from __future__ import annotations

from pulsebridge.db import Database
from pulsebridge.ui.floating import build_floating_snapshot
from pulsebridge.util import start_of_local_day


def _sample(
    uuid: str,
    type_: str,
    start_ts: int,
    value: float,
    unit: str = "count",
    duration: int = 60,
) -> dict:
    return {
        "uuid": uuid,
        "type": type_,
        "start_ts": start_ts,
        "end_ts": start_ts + duration,
        "value": value,
        "value_text": None,
        "unit": unit,
        "source": "Apple Watch",
        "device": "Apple Watch",
        "metadata": None,
    }


def test_floating_snapshot(tmp_path) -> None:
    db = Database(tmp_path / "test.db")
    day_start = start_of_local_day()
    db.insert_samples(
        [
            _sample("steps", "steps", day_start + 8 * 3600, 5000.0, unit="步"),
            _sample("distance", "distance", day_start + 8 * 3600, 2.0, unit="km"),
            _sample(
                "flights",
                "flights_climbed",
                day_start + 8 * 3600,
                6.0,
                unit="层",
            ),
            _sample(
                "resting",
                "resting_heart_rate",
                day_start + 60,
                60.0,
                unit="count/min",
            ),
            {
                **_sample(
                    "sleep",
                    "sleep_analysis",
                    day_start - 3600,
                    0.0,
                    duration=0,
                ),
                "value": None,
                "value_text": "core",
                "end_ts": day_start + 7 * 3600,
            },
        ]
    )
    db.insert_workouts(
        [
            {
                "uuid": "workout",
                "activity_type": "running",
                "start_ts": day_start + 9 * 3600,
                "end_ts": day_start + 9 * 3600 + 1800,
                "duration_s": 1800,
                "distance_m": 3000,
                "energy_kcal": 180,
                "avg_hr": 140,
                "max_hr": 160,
                "source": "Apple Watch",
                "metadata": None,
            }
        ]
    )

    snapshot = build_floating_snapshot(db)
    assert snapshot["steps"] == 5000.0
    assert snapshot["step_percent"] == 50
    assert snapshot["sleep_hours"] == 8.0
    assert snapshot["mood"] == "training"
    assert snapshot["step_goal"] == 10000
    assert "绕操场" in snapshot["playful"]
    assert "爬 6 层楼" in snapshot["playful"]
    assert snapshot["rings"]["move"] >= 0
    db.close()
