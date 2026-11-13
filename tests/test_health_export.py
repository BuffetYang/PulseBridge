from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from pulsebridge.db import Database
from pulsebridge.health_export import HealthExportError, import_health_export

XML = """<?xml version="1.0" encoding="UTF-8"?>
<HealthData locale="zh_CN">
  <ExportDate value="2024-01-02 00:00:00 +0800"/>
  <Record type="HKQuantityTypeIdentifierHeartRate" sourceName="Apple Watch"
          unit="count/min" startDate="2024-01-01 08:00:00 +0800"
          endDate="2024-01-01 08:01:00 +0800" value="72"/>
  <Record type="HKQuantityTypeIdentifierStepCount" sourceName="Apple Watch"
          unit="count" startDate="2024-01-01 08:00:00 +0800"
          endDate="2024-01-01 09:00:00 +0800" value="1200"/>
  <Record type="HKCategoryTypeIdentifierSleepAnalysis" sourceName="Apple Watch"
          startDate="2024-01-01 01:00:00 +0800"
          endDate="2024-01-01 02:30:00 +0800"
          value="HKCategoryValueSleepAnalysisAsleepCore"/>
  <Workout workoutActivityType="HKWorkoutActivityTypeBadminton"
           duration="30" durationUnit="min"
           totalDistance="1.2" totalDistanceUnit="km"
           totalEnergyBurned="300" totalEnergyBurnedUnit="kcal"
           sourceName="Apple Watch"
           startDate="2024-01-01 18:00:00 +0800"
           endDate="2024-01-01 18:30:00 +0800">
    <WorkoutStatistics type="HKQuantityTypeIdentifierHeartRate"
                       average="150" maximum="170" unit="count/min"/>
  </Workout>
  <ActivitySummary dateComponents="2024-01-01" activeEnergyBurned="420"
                   activeEnergyBurnedGoal="500" appleExerciseTime="35"
                   appleExerciseTimeGoal="30" appleStandHours="10"
                   appleStandHoursGoal="12"/>
</HealthData>
"""


def _make_zip(tmp_path: Path) -> Path:
    path = tmp_path / "export.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("apple_health_export/export.xml", XML)
    return path


def test_import_export_zip(tmp_path) -> None:
    db = Database(tmp_path / "test.db")
    progress_calls = []
    summary = import_health_export(
        _make_zip(tmp_path),
        db,
        progress=lambda *args: progress_calls.append(args),
    )
    assert summary.records == 3
    assert summary.workouts_seen == 1
    assert summary.samples_new == 3
    assert summary.workouts_new == 1
    assert not summary.cancelled
    assert db.stats()["samples"] == 3
    assert db.stats()["workouts"] == 1

    hr = db.latest_sample("heart_rate")
    assert hr is not None and hr["value"] == 72.0
    sleep = db.sleep_samples(0)
    assert sleep and sleep[0]["value_text"] == "core"

    workout = db.workout_rows(0)[0]
    assert workout["activity_type"] == "badminton"
    assert workout["duration_s"] == 1800
    assert workout["distance_m"] == 1200
    assert workout["energy_kcal"] == 300
    assert workout["avg_hr"] == 150
    assert workout["max_hr"] == 170

    summary_row = db.latest_activity_summary()
    assert summary_row is not None
    assert summary_row["date"] == "2024-01-01"
    assert summary_row["move_kcal"] == 420
    assert summary_row["move_goal_kcal"] == 500
    assert summary_row["exercise_min"] == 35
    assert summary_row["stand_hours"] == 10

    # 再次导入：UUID 指纹去重
    again = import_health_export(_make_zip(tmp_path), db)
    assert again.samples_new == 0
    assert again.samples_dupe == 3
    assert again.workouts_new == 0
    assert db.stats()["samples"] == 3
    db.close()


def test_import_plain_xml(tmp_path) -> None:
    path = tmp_path / "export.xml"
    path.write_text(XML, "utf-8")
    db = Database(tmp_path / "test.db")
    summary = import_health_export(path, db)
    assert summary.samples_new == 3
    assert summary.workouts_new == 1
    db.close()


def test_import_localized_main_xml_filename(tmp_path) -> None:
    """中文系统的 zip 主文件可能叫「导出.xml」，且可能伴随 export_cda.xml。"""
    path = tmp_path / "localized.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("apple_health_export/导出.xml", XML)
        archive.writestr("apple_health_export/export_cda.xml", "<ClinicalDocument/>")
    db = Database(tmp_path / "test.db")
    summary = import_health_export(path, db)
    assert summary.samples_new == 3
    assert summary.workouts_new == 1
    db.close()


def test_missing_export_xml(tmp_path) -> None:
    path = tmp_path / "bad.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("other.txt", "x")
    db = Database(tmp_path / "test.db")
    with pytest.raises(HealthExportError):
        import_health_export(path, db)
    db.close()


def test_cancel_import(tmp_path) -> None:
    db = Database(tmp_path / "test.db")

    class Stop:
        def is_set(self) -> bool:
            return True

    summary = import_health_export(_make_zip(tmp_path), db, stop_event=Stop())
    assert summary.cancelled
    db.close()
