from __future__ import annotations

from datetime import datetime

from pulsebridge.ingest import normalize_payload, normalize_sample, normalize_workout


def ts(value: str) -> int:
    return int(datetime.fromisoformat(value).timestamp())


def test_normalize_sample_aliases_and_stable_uuid() -> None:
    sample = normalize_sample(
        {
            "type": "Heart Rate",
            "startDate": "2026-11-12T08:00:00+08:00",
            "endDate": "2026-11-12T08:01:00+08:00",
            "value": 72,
            "unit": "count/min",
            "source": "Apple Watch",
        }
    )
    assert sample is not None
    assert sample["type"] == "heart_rate"
    assert sample["start_ts"] == ts("2026-11-12T08:00:00+08:00")
    assert sample["value"] == 72.0
    assert len(sample["uuid"]) == 40

    duplicate = normalize_sample(
        {
            "type": "Heart Rate",
            "startDate": "2026-11-12T08:00:00+08:00",
            "endDate": "2026-11-12T08:01:00+08:00",
            "value": 72,
            "unit": "count/min",
            "source": "Apple Watch",
        }
    )
    assert duplicate is not None
    assert duplicate["uuid"] == sample["uuid"]


def test_chinese_types_and_sleep_stage() -> None:
    result = normalize_payload(
        {
            "samples": [
                {
                    "type": "心率",
                    "start": "2026-11-12T08:00:00+08:00",
                    "end": "2026-11-12T08:01:00+08:00",
                    "value": 68,
                },
                {
                    "type": "睡眠",
                    "start": "2026-11-12T01:00:00+08:00",
                    "end": "2026-11-12T02:30:00+08:00",
                    "value": "核心",
                },
            ]
        }
    )
    assert [s["type"] for s in result.samples] == ["heart_rate", "sleep_analysis"]
    assert result.samples[1]["value_text"] == "core"
    assert result.samples[1]["value"] is None


def test_health_auto_export_metric_shape() -> None:
    result = normalize_payload(
        {
            "metrics": [
                {
                    "name": "step_count",
                    "units": "count",
                    "data": [
                        {"date": "2026-11-12T08:00:00+08:00", "qty": 1200},
                    ],
                }
            ]
        }
    )
    assert len(result.samples) == 1
    assert result.samples[0]["type"] == "steps"
    assert result.samples[0]["value"] == 1200.0
    assert result.samples[0]["unit"] == "count"


def test_workout_nested_measurements() -> None:
    workout = normalize_workout(
        {
            "type": "Running",
            "startDate": "2026-11-12T07:00:00+08:00",
            "endDate": "2026-11-12T07:30:00+08:00",
            "duration": 1800,
            "distance": {"qty": 5.02, "units": "km"},
            "activeEnergyBurned": {"qty": 320, "units": "kcal"},
            "heartRate": {"avg": 152, "max": 171},
            "source": "Apple Watch",
        }
    )
    assert workout is not None
    assert workout["activity_type"] == "running"
    assert workout["duration_s"] == 1800
    assert abs(workout["distance_m"] - 5020) < 0.01
    assert workout["energy_kcal"] == 320
    assert workout["avg_hr"] == 152
    assert workout["max_hr"] == 171


def test_workout_type_and_uuid_dedupe_across_sources() -> None:
    first = normalize_workout(
        {
            "type": "跑步",
            "start": "2026-11-12T07:00:00+08:00",
            "end": "2026-11-12T07:30:00+08:00",
            "source": "Apple Watch",
        }
    )
    second = normalize_workout(
        {
            "type": "Running",
            "start": "2026-11-12T07:00:00+08:00",
            "end": "2026-11-12T07:30:00+08:00",
            "source": "iPhone",
        }
    )
    assert first is not None and second is not None
    assert first["activity_type"] == "running"
    assert first["uuid"] == second["uuid"]
    assert first["duration_s"] == 1800


def test_single_sample_payload() -> None:
    result = normalize_payload(
        {
            "device": "iPhone",
            "type": "heart_rate",
            "start": "2026-11-12T23:20:00+08:00",
            "end": "2026-11-12T23:20:00+08:00",
            "value": 72,
            "unit": "count/min",
            "source": "Test",
        }
    )
    assert len(result.samples) == 1
    assert result.samples[0]["type"] == "heart_rate"
    assert result.samples[0]["value"] == 72.0

    wrapped = normalize_payload(
        {
            "device": "iPhone",
            "sample": {
                "type": "steps",
                "start": "2026-11-12T23:20:00+08:00",
                "end": "2026-11-12T23:21:00+08:00",
                "value": 120,
            },
        }
    )
    assert len(wrapped.samples) == 1
    assert wrapped.samples[0]["type"] == "steps"


def test_single_sample_without_timestamps_defaults_to_now() -> None:
    import time

    before = int(time.time())
    result = normalize_payload(
        {"device": "iPhone", "type": "heart_rate", "value": 72, "unit": "count/min"}
    )
    assert len(result.samples) == 1
    sample = result.samples[0]
    assert sample["start_ts"] >= before
    assert sample["end_ts"] == sample["start_ts"]


def test_rejects_empty_payload() -> None:
    import pytest

    with pytest.raises(ValueError):
        normalize_payload({"samples": []})
