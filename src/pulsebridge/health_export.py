"""导入 Apple Health 的「导出所有健康数据」文件（export.zip / export.xml）。

Apple 的导出是 XML，数据量大（可能几十万到上百万条），这里用 iterparse 流式解析，
分批写入 SQLite，并支持取消与进度回调。导入的数据按内容指纹去重，可重复导入。
"""

from __future__ import annotations

import time
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import BinaryIO, Callable

from .db import Database
from .ingest import normalize_sample, normalize_workout

ProgressCallback = Callable[[int, int, int, int], None]
# (records_seen, workouts_seen, samples_new, workouts_new)


class HealthExportError(Exception):
    pass


@dataclass
class ImportSummary:
    records: int = 0
    workouts_seen: int = 0
    samples_new: int = 0
    samples_dupe: int = 0
    workouts_new: int = 0
    workouts_dupe: int = 0
    skipped: int = 0
    cancelled: bool = False
    duration_s: float = 0.0
    source_file: str = ""
    activity_summaries: int = 0

    def as_dict(self) -> dict:
        return asdict(self)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _num(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _duration_seconds(value: str | None, unit: str | None) -> float | None:
    number = _num(value)
    if number is None:
        return None
    unit = (unit or "").strip().lower()
    if unit in ("min", "minute", "minutes", "分", "分钟"):
        return number * 60
    if unit in ("h", "hr", "hour", "hours", "小时"):
        return number * 3600
    return number  # 秒（或未标注，按秒处理）


def _distance_meters(value: str | None, unit: str | None) -> float | None:
    number = _num(value)
    if number is None:
        return None
    unit = (unit or "").strip().lower()
    if unit in ("km", "kilometer", "kilometers", "公里", "千米"):
        return number * 1000
    if unit in ("mi", "mile", "miles", "英里"):
        return number * 1609.344
    if unit in ("ft", "feet", "英尺"):
        return number * 0.3048
    if unit in ("yd", "yard", "yards", "码"):
        return number * 0.9144
    return number


def _energy_kcal(value: str | None, unit: str | None) -> float | None:
    number = _num(value)
    if number is None:
        return None
    unit = (unit or "").strip().lower()
    if unit in ("kj", "kilojoule", "kilojoules", "千焦"):
        return number * 0.239006
    return number


def _find_export_xml(archive: zipfile.ZipFile) -> str:
    """找到主数据 XML。

    Apple 的英文导出叫 export.xml；中文系统可能叫「导出.xml」，zip 里甚至可能
    呈现为乱码文件名。优先 export.xml，否则选择最大的非 export_cda.xml。
    """
    entries = [
        info for info in archive.infolist() if info.filename.lower().endswith(".xml")
    ]
    candidates = [
        info
        for info in entries
        if not info.filename.replace("\\", "/").lower().endswith("export_cda.xml")
    ]
    if not candidates:
        raise HealthExportError("压缩包里没有找到健康数据 XML（export.xml / 导出.xml）")

    preferred = [
        info
        for info in candidates
        if info.filename.replace("\\", "/").lower().endswith("/export.xml")
        or info.filename.lower() == "export.xml"
    ]
    chosen = preferred[0] if preferred else max(candidates, key=lambda item: item.file_size)
    return chosen.filename


def _record_to_sample(element: ET.Element) -> dict | None:
    attrs = element.attrib
    raw = {
        "type": attrs.get("type"),
        "start": attrs.get("startDate"),
        "end": attrs.get("endDate"),
        "value": attrs.get("value"),
        "unit": attrs.get("unit"),
        "source": attrs.get("sourceName"),
        "device": attrs.get("device"),
    }
    return normalize_sample(raw)


def _activity_summary_to_row(element: ET.Element) -> dict | None:
    attrs = element.attrib
    date_text = str(attrs.get("dateComponents") or attrs.get("date") or "")[:10]
    if len(date_text) != 10:
        return None
    return {
        "date": date_text,
        "move_kcal": _num(attrs.get("activeEnergyBurned")),
        "move_goal_kcal": _num(attrs.get("activeEnergyBurnedGoal")),
        "exercise_min": _num(attrs.get("appleExerciseTime")),
        "exercise_goal_min": _num(attrs.get("appleExerciseTimeGoal")),
        "stand_hours": _num(attrs.get("appleStandHours")),
        "stand_goal_hours": _num(attrs.get("appleStandHoursGoal")),
    }


def _workout_to_row(element: ET.Element) -> dict | None:
    attrs = element.attrib
    avg_hr = None
    max_hr = None
    for child in element:
        if _local(child.tag) != "WorkoutStatistics":
            continue
        if child.attrib.get("type") == "HKQuantityTypeIdentifierHeartRate":
            avg_hr = _num(child.attrib.get("average"))
            max_hr = _num(child.attrib.get("maximum"))

    raw = {
        "type": attrs.get("workoutActivityType"),
        "start": attrs.get("startDate"),
        "end": attrs.get("endDate"),
        "duration_s": _duration_seconds(
            attrs.get("duration"), attrs.get("durationUnit")
        ),
        "distance_m": _distance_meters(
            attrs.get("totalDistance"), attrs.get("totalDistanceUnit")
        ),
        "energy_kcal": _energy_kcal(
            attrs.get("totalEnergyBurned"), attrs.get("totalEnergyBurnedUnit")
        ),
        "avg_hr": avg_hr,
        "max_hr": max_hr,
        "source": attrs.get("sourceName"),
        "metadata": {"source": "apple_health_export"},
    }
    return normalize_workout(raw)


def _parse_stream(
    fp: BinaryIO,
    db: Database,
    summary: ImportSummary,
    progress: ProgressCallback | None,
    stop_event,
) -> None:
    batch_samples: list[dict] = []
    batch_workouts: list[dict] = []
    batch_activities: list[dict] = []
    last_flush = 0

    def flush() -> None:
        nonlocal last_flush
        if batch_samples:
            new, dupe = db.insert_samples(batch_samples)
            summary.samples_new += new
            summary.samples_dupe += dupe
            batch_samples.clear()
        if batch_workouts:
            new, dupe = db.insert_workouts(batch_workouts)
            summary.workouts_new += new
            summary.workouts_dupe += dupe
            batch_workouts.clear()
        if batch_activities:
            summary.activity_summaries += db.upsert_activity_summaries(
                batch_activities
            )
            batch_activities.clear()
        if progress and summary.records - last_flush >= 1000:
            last_flush = summary.records
            progress(
                summary.records,
                summary.workouts_seen,
                summary.samples_new,
                summary.workouts_new,
            )

    context = ET.iterparse(fp, events=("start", "end"))
    try:
        _, root = next(context)
    except StopIteration as exc:
        raise HealthExportError("export.xml 是空文件") from exc

    for event, element in context:
        if event != "end":
            continue
        tag = _local(element.tag)
        if tag == "Record":
            summary.records += 1
            sample = _record_to_sample(element)
            if sample:
                batch_samples.append(sample)
            else:
                summary.skipped += 1
        elif tag == "Workout":
            summary.workouts_seen += 1
            workout = _workout_to_row(element)
            if workout:
                batch_workouts.append(workout)
            else:
                summary.skipped += 1
        elif tag == "ActivitySummary":
            row = _activity_summary_to_row(element)
            if row:
                batch_activities.append(row)
        else:
            continue

        if len(batch_samples) + len(batch_workouts) + len(batch_activities) >= 2000:
            flush()
            root.clear()
        elif summary.records % 2000 == 0 and summary.records:
            root.clear()

        if stop_event is not None and stop_event.is_set():
            summary.cancelled = True
            break

    flush()
    root.clear()


def import_health_export(
    path: Path | str,
    db: Database,
    progress: ProgressCallback | None = None,
    stop_event=None,
) -> ImportSummary:
    """导入 Apple Health 导出的 zip 或 export.xml。"""
    path = Path(path)
    if not path.exists():
        raise HealthExportError(f"文件不存在：{path}")

    started = time.time()
    summary = ImportSummary(source_file=str(path))
    if path.suffix.lower() == ".zip":
        try:
            with zipfile.ZipFile(path) as archive:
                name = _find_export_xml(archive)
                with archive.open(name) as fp:
                    _parse_stream(fp, db, summary, progress, stop_event)
        except zipfile.BadZipFile as exc:
            raise HealthExportError(f"不是有效的 zip 文件：{exc}") from exc
    else:
        with path.open("rb") as fp:
            _parse_stream(fp, db, summary, progress, stop_event)

    summary.duration_s = round(time.time() - started, 1)
    return summary
