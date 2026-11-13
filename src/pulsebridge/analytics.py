"""健康数据聚合：日汇总、心率序列、睡眠夜间统计。"""

from __future__ import annotations

import time
from datetime import date, datetime, timedelta
from typing import Any

from .db import Database
from .util import start_of_local_day

CUMULATIVE_TYPES = {
    "steps",
    "active_energy",
    "basal_energy",
    "exercise_minutes",
    "stand_minutes",
    "stand_hours",
    "flights_climbed",
    "distance",
    "distance_cycling",
    "daylight_minutes",
    "swimming_distance",
    "swimming_strokes",
    "dietary_energy",
}

AVERAGE_TYPES = {
    "heart_rate",
    "resting_heart_rate",
    "hrv",
    "oxygen_saturation",
    "respiratory_rate",
    "vo2max",
    "body_mass",
    "walking_heart_rate",
    "wrist_temperature",
}

METRIC_META: dict[str, dict[str, Any]] = {
    "steps": {"label": "步数", "unit": "步", "digits": 0, "cumulative": True},
    "heart_rate": {"label": "心率", "unit": "bpm", "digits": 0, "cumulative": False},
    "resting_heart_rate": {
        "label": "静息心率",
        "unit": "bpm",
        "digits": 0,
        "cumulative": False,
    },
    "walking_heart_rate": {
        "label": "步行平均心率",
        "unit": "bpm",
        "digits": 0,
        "cumulative": False,
    },
    "hrv": {"label": "心率变异性", "unit": "ms", "digits": 0, "cumulative": False},
    "heart_rate_recovery": {
        "label": "1 分钟心率恢复",
        "unit": "bpm",
        "digits": 0,
        "cumulative": False,
    },
    "active_energy": {"label": "活动能量", "unit": "kcal", "digits": 0, "cumulative": True},
    "basal_energy": {"label": "静息能量", "unit": "kcal", "digits": 0, "cumulative": True},
    "exercise_minutes": {
        "label": "锻炼时间",
        "unit": "分钟",
        "digits": 0,
        "cumulative": True,
    },
    "stand_minutes": {
        "label": "站立时间",
        "unit": "分钟",
        "digits": 0,
        "cumulative": True,
    },
    "stand_hours": {"label": "站立时间", "unit": "小时", "digits": 0, "cumulative": True},
    "oxygen_saturation": {
        "label": "血氧",
        "unit": "%",
        "digits": 0,
        "cumulative": False,
        "scale": 100,
    },
    "respiratory_rate": {
        "label": "呼吸频率",
        "unit": "次/分",
        "digits": 1,
        "cumulative": False,
    },
    "vo2max": {"label": "最大摄氧量", "unit": "mL/min·kg", "digits": 1, "cumulative": False},
    "body_mass": {"label": "体重", "unit": "kg", "digits": 1, "cumulative": False},
    "body_fat": {
        "label": "体脂率",
        "unit": "%",
        "digits": 1,
        "cumulative": False,
        "scale": 100,
    },
    "bmi": {"label": "BMI", "unit": "", "digits": 1, "cumulative": False},
    "waist": {"label": "腰围", "unit": "cm", "digits": 1, "cumulative": False},
    "height": {"label": "身高", "unit": "cm", "digits": 0, "cumulative": False},
    "sleep": {"label": "睡眠", "unit": "小时", "digits": 1, "cumulative": False},
    "sleep_goal": {"label": "睡眠目标", "unit": "小时", "digits": 1, "cumulative": False},
    "wrist_temperature": {
        "label": "手腕温度",
        "unit": "°C",
        "digits": 1,
        "cumulative": False,
    },
    "breathing_disturbances": {
        "label": "睡眠呼吸紊乱",
        "unit": "次",
        "digits": 2,
        "cumulative": False,
    },
    "distance": {"label": "步行+跑步距离", "unit": "km", "digits": 2, "cumulative": True},
    "distance_cycling": {"label": "骑行距离", "unit": "km", "digits": 2, "cumulative": True},
    "flights_climbed": {"label": "爬楼层数", "unit": "层", "digits": 0, "cumulative": True},
    "walking_speed": {"label": "步速", "unit": "km/h", "digits": 2, "cumulative": False},
    "walking_step_length": {
        "label": "步长",
        "unit": "cm",
        "digits": 1,
        "cumulative": False,
    },
    "walking_double_support": {
        "label": "双支撑占比",
        "unit": "%",
        "digits": 1,
        "cumulative": False,
        "scale": 100,
    },
    "walking_asymmetry": {
        "label": "步行不对称",
        "unit": "%",
        "digits": 1,
        "cumulative": False,
        "scale": 100,
    },
    "walking_steadiness": {
        "label": "步行稳定性",
        "unit": "%",
        "digits": 0,
        "cumulative": False,
        "scale": 100,
    },
    "six_minute_walk": {
        "label": "6 分钟步行",
        "unit": "m",
        "digits": 0,
        "cumulative": False,
    },
    "stair_ascent_speed": {
        "label": "上楼速度",
        "unit": "m/s",
        "digits": 2,
        "cumulative": False,
    },
    "stair_descent_speed": {
        "label": "下楼速度",
        "unit": "m/s",
        "digits": 2,
        "cumulative": False,
    },
    "headphone_audio": {
        "label": "耳机音量",
        "unit": "dB",
        "digits": 0,
        "cumulative": False,
    },
    "environmental_audio": {
        "label": "环境音量",
        "unit": "dB",
        "digits": 0,
        "cumulative": False,
    },
    "daylight_minutes": {
        "label": "日照时间",
        "unit": "分钟",
        "digits": 0,
        "cumulative": True,
    },
    "physical_effort": {
        "label": "体力活动",
        "unit": "kcal/hr·kg",
        "digits": 1,
        "cumulative": False,
    },
    "workout_effort": {
        "label": "运动努力",
        "unit": "分",
        "digits": 0,
        "cumulative": False,
    },
    "estimated_workout_effort": {
        "label": "估算运动努力",
        "unit": "分",
        "digits": 0,
        "cumulative": False,
    },
    "swimming_distance": {
        "label": "游泳距离",
        "unit": "m",
        "digits": 0,
        "cumulative": True,
    },
    "swimming_strokes": {
        "label": "划水次数",
        "unit": "次",
        "digits": 0,
        "cumulative": True,
    },
    "mindful_minutes": {
        "label": "正念",
        "unit": "次",
        "digits": 0,
        "cumulative": True,
    },
    "stand_hour": {"label": "站立小时", "unit": "", "digits": 0, "cumulative": False},
    "audio_exposure_event": {"label": "音量超限事件", "unit": "", "digits": 0, "cumulative": False},
    "headphone_audio_event": {"label": "耳机音量超限", "unit": "", "digits": 0, "cumulative": False},
}

METRIC_ORDER = [
    "steps",
    "heart_rate",
    "resting_heart_rate",
    "hrv",
    "sleep",
    "active_energy",
    "basal_energy",
    "exercise_minutes",
    "stand_minutes",
    "distance",
    "distance_cycling",
    "walking_speed",
    "walking_step_length",
    "walking_double_support",
    "walking_asymmetry",
    "walking_steadiness",
    "six_minute_walk",
    "oxygen_saturation",
    "respiratory_rate",
    "vo2max",
    "heart_rate_recovery",
    "walking_heart_rate",
    "wrist_temperature",
    "breathing_disturbances",
    "sleep_goal",
    "body_mass",
    "body_fat",
    "bmi",
    "waist",
    "height",
    "headphone_audio",
    "environmental_audio",
    "daylight_minutes",
    "physical_effort",
    "workout_effort",
    "estimated_workout_effort",
    "stair_ascent_speed",
    "stair_descent_speed",
    "swimming_distance",
    "swimming_strokes",
    "flights_climbed",
]


def metric_meta(metric: str) -> dict[str, Any]:
    meta = METRIC_META.get(metric)
    if meta is not None:
        return meta
    label = metric.replace("_", " ").strip()
    if label:
        label = label[0].upper() + label[1:]
    return {"label": label or metric, "unit": "", "digits": 1, "cumulative": False}


def display_value(metric: str, value: float | None) -> float | None:
    """百分比类 Apple 数据可能以 0–1 的小数存储，展示时统一成百分数。"""
    if value is None:
        return None
    meta = METRIC_META.get(metric, {})
    if meta.get("scale") == 100 and 0 <= value <= 1.0:
        return value * 100
    return value


def date_range(days: int) -> list[str]:
    today = date.today()
    return [(today - timedelta(days=i)).isoformat() for i in range(days - 1, -1, -1)]


def daily_series(db: Database, metric: str, days: int) -> list[dict[str, Any]]:
    """返回连续 ``days`` 天的 ``{date, value}``，缺失日期 value 为 None。"""
    days = max(1, int(days))
    dates = date_range(days)
    start = start_of_local_day(offset_days=-(days - 1))

    values: dict[str, float | None]
    if metric == "sleep":
        nights = {n["date"]: n["asleep_min"] / 60.0 for n in sleep_nights(db, days)}
        values = {day: nights.get(day) for day in dates}
    elif metric in CUMULATIVE_TYPES:
        rows = db.daily_cumulative(metric, start)
        found = {str(row["day"]): float(row["value"]) for row in rows}
        values = {day: found.get(day) for day in dates}
    else:
        rows = db.daily_stats(metric, start)
        found = {str(row["day"]): float(row["avg"]) for row in rows}
        values = {day: found.get(day) for day in dates}

    return [{"date": day, "value": values.get(day)} for day in dates]


RESTING_ESTIMATE_MIN_SAMPLES = 20
RESTING_ESTIMATE_PERCENTILE = 0.7


def _percentile(sorted_values: list[float], q: float) -> float:
    """线性插值分位数；调用方需先升序排序。"""
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    position = (len(sorted_values) - 1) * q
    lower = int(position)
    upper = min(lower + 1, len(sorted_values) - 1)
    weight = position - lower
    return float(sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight)


def _day_start_ts(day: str) -> int:
    try:
        return int(datetime.strptime(day, "%Y-%m-%d").timestamp())
    except ValueError:
        return 0


def _estimate_resting_hr_for_day(
    db: Database, day: str, sleep_intervals: list[tuple[int, int]]
) -> float | None:
    """用睡眠期间的心率估算静息心率。

    Apple 的静息心率是独立指标，原始心率流无法完全复现；这里取睡眠心率
    的 70% 分位，作为缺失日期的近似值。没有睡眠记录时退化为 00:00–07:00
    的夜间心率。
    """
    day_start = _day_start_ts(day)
    if not day_start:
        return None
    day_end = day_start + 86400

    values: list[float] = []
    if sleep_intervals:
        lo = max(day_start - 12 * 3600, min(start for start, _end in sleep_intervals))
        hi = min(day_end + 6 * 3600, max(end for _start, end in sleep_intervals))
        for row in db.samples_between("heart_rate", lo, hi, limit=50000):
            value = row.get("value")
            if value is None:
                continue
            ts = int(row["start_ts"])
            if any(start <= ts <= end for start, end in sleep_intervals):
                values.append(float(value))

    if len(values) < RESTING_ESTIMATE_MIN_SAMPLES:
        rows = db.samples_between(
            "heart_rate", day_start, day_start + 7 * 3600, limit=20000
        )
        values = [float(row["value"]) for row in rows if row.get("value") is not None]

    if len(values) < RESTING_ESTIMATE_MIN_SAMPLES:
        return None
    values.sort()
    return _percentile(values, RESTING_ESTIMATE_PERCENTILE)


def resting_heart_rate_series(db: Database, days: int = 7) -> list[dict[str, Any]]:
    """每日静息心率：优先 Apple 官方样本，缺失日期用心率估算。

    返回 ``[{date, value, estimated}]``，日期连续；``estimated`` 为 True 表示
    该天的值由睡眠心率推算，不是 HealthKit 的 RestingHeartRate 样本。
    """
    days = max(1, int(days))
    dates = date_range(days)
    start = start_of_local_day(offset_days=-(days - 1))
    official = {
        str(row["day"]): float(row["avg"])
        for row in db.daily_stats("resting_heart_rate", start)
    }
    # 只估算「官方样本之后」的缺失日期，避免在历史空档里凭空生成估算值。
    # 最多回看 14 天，既覆盖最近未导入的几天，也不会拖慢 90 天趋势。
    recent_floor = dates[max(0, len(dates) - 14)]
    last_official_day = max(official) if official else ""
    estimate_floor = max(last_official_day, recent_floor)

    # 睡眠区间按「醒来日」分组，供缺失日期估算使用。
    intervals_by_day: dict[str, list[tuple[int, int]]] = {}
    for row in db.sleep_samples(start - 86400):
        stage = str(row.get("value_text") or "")
        if stage in ("awake", "in_bed"):
            continue
        end_ts = int(row["end_ts"])
        day = _local_date(end_ts)
        if day < dates[0] or day > dates[-1]:
            continue
        intervals_by_day.setdefault(day, []).append((int(row["start_ts"]), end_ts))

    series: list[dict[str, Any]] = []
    for day in dates:
        if day in official:
            series.append({"date": day, "value": official[day], "estimated": False})
            continue
        if day <= estimate_floor:
            series.append({"date": day, "value": None, "estimated": False})
            continue
        estimate = _estimate_resting_hr_for_day(db, day, intervals_by_day.get(day, []))
        series.append(
            {"date": day, "value": estimate, "estimated": estimate is not None}
        )
    return series


def series_stats(points: list[dict[str, Any]], cumulative: bool) -> dict[str, Any]:
    values = [p["value"] for p in points if p.get("value") is not None]
    if not values:
        return {"avg": None, "min": None, "max": None, "total": None, "count": 0}
    return {
        "avg": sum(values) / len(values),
        "min": min(values),
        "max": max(values),
        "total": sum(values) if cumulative else None,
        "count": len(values),
    }


def today_cumulative(db: Database, metric: str) -> float:
    rows = db.daily_cumulative(metric, start_of_local_day())
    if not rows:
        return 0.0
    return float(rows[-1]["value"] or 0.0)


def today_sum(db: Database, metric: str) -> float:
    row = db.latest_sample(metric, since_ts=start_of_local_day())
    return float(row["value"]) if row and row.get("value") is not None else 0.0


def latest_sample(
    db: Database, metric: str, within_hours: int | None = None
) -> dict[str, Any] | None:
    since = int(time.time()) - within_hours * 3600 if within_hours else None
    return db.latest_sample(metric, since_ts=since)


def heart_rate_points(db: Database, hours: int = 24) -> list[tuple[int, float]]:
    since = int(time.time()) - hours * 3600
    rows = db.samples_between("heart_rate", since)
    # 同一分钟内多来源取平均，减少毛刺
    buckets: dict[int, list[float]] = {}
    for row in rows:
        value = row.get("value")
        if value is None:
            continue
        key = int(row["start_ts"]) // 60 * 60
        buckets.setdefault(key, []).append(float(value))
    return [(key, sum(vals) / len(vals)) for key, vals in sorted(buckets.items())]


def _stage_minutes(row: dict[str, Any]) -> float:
    start = int(row["start_ts"])
    end = int(row["end_ts"])
    return max(0.0, (end - start) / 60.0)


def sleep_nights(db: Database, days: int = 14) -> list[dict[str, Any]]:
    """按「醒来日」汇总睡眠。

    HealthKit 中同一晚可能有 iPhone / Watch 两份记录；这里按来源分别汇总，
    取睡眠时长最大的来源，避免叠加导致睡眠时间翻倍。
    """
    since = start_of_local_day(offset_days=-(days + 1))
    rows = db.sleep_samples(since)
    by_night_source: dict[tuple[str, str], dict[str, Any]] = {}

    for row in rows:
        day = _local_date(row["end_ts"])
        source = row.get("source") or "unknown"
        bucket = by_night_source.setdefault(
            (day, source),
            {
                "date": day,
                "source": source,
                "core_min": 0.0,
                "deep_min": 0.0,
                "rem_min": 0.0,
                "unspecified_min": 0.0,
                "awake_min": 0.0,
                "in_bed_min": 0.0,
                "start_ts": int(row["start_ts"]),
                "end_ts": int(row["end_ts"]),
            },
        )
        minutes = _stage_minutes(row)
        stage = row.get("value_text") or "asleep_unspecified"
        if stage == "core":
            bucket["core_min"] += minutes
        elif stage == "deep":
            bucket["deep_min"] += minutes
        elif stage == "rem":
            bucket["rem_min"] += minutes
        elif stage == "awake":
            bucket["awake_min"] += minutes
        elif stage == "in_bed":
            bucket["in_bed_min"] += minutes
        else:
            bucket["unspecified_min"] += minutes
        bucket["start_ts"] = min(bucket["start_ts"], int(row["start_ts"]))
        bucket["end_ts"] = max(bucket["end_ts"], int(row["end_ts"]))

    by_night: dict[str, dict[str, Any]] = {}
    for (day, _source), bucket in by_night_source.items():
        bucket["asleep_min"] = (
            bucket["core_min"]
            + bucket["deep_min"]
            + bucket["rem_min"]
            + bucket["unspecified_min"]
        )
        bucket["in_bed_min"] = max(bucket["in_bed_min"], bucket["asleep_min"] + bucket["awake_min"])
        bucket["efficiency"] = (
            bucket["asleep_min"] / bucket["in_bed_min"] * 100 if bucket["in_bed_min"] else 0.0
        )
        existing = by_night.get(day)
        if existing is None or bucket["asleep_min"] > existing["asleep_min"]:
            by_night[day] = bucket

    return [by_night[day] for day in sorted(by_night)]


def last_night(db: Database) -> dict[str, Any] | None:
    nights = sleep_nights(db, days=3)
    if not nights:
        return None
    latest = nights[-1]
    if latest["asleep_min"] <= 0 and latest["in_bed_min"] <= 0:
        return None
    return latest


def sleep_segments(db: Database, night: dict[str, Any] | None) -> list[tuple[int, int, str]]:
    """某一夜的阶段片段，用于 hypnogram。"""
    if not night:
        return []
    start_limit = int(night["start_ts"])
    end_limit = int(night["end_ts"])
    source = night.get("source")
    rows = db.sleep_samples(start_limit - 3600)
    segments: list[tuple[int, int, str]] = []
    for row in rows:
        if source and row.get("source") != source:
            continue
        start = max(int(row["start_ts"]), start_limit)
        end = min(int(row["end_ts"]), end_limit)
        if end <= start:
            continue
        stage = row.get("value_text") or "asleep_unspecified"
        if stage == "in_bed":
            continue
        segments.append((start, end, stage))
    segments.sort()
    return segments


def sleep_minutes_today(db: Database) -> float:
    """今天 0 点后结束的睡眠（用于“今天”统计的补充）。"""
    rows = db.sleep_samples(start_of_local_day())
    return sum(_stage_minutes(r) for r in rows if (r.get("value_text") or "") != "awake")


def recent_workouts(db: Database, days: int = 30, limit: int = 100) -> list[dict[str, Any]]:
    since = start_of_local_day(offset_days=-(days - 1))
    rows = db.workout_rows(since, limit=limit)
    for row in rows:
        if not row.get("duration_s") and row.get("end_ts") and row.get("start_ts"):
            row["duration_s"] = max(0, int(row["end_ts"]) - int(row["start_ts"]))
        if row.get("metadata"):
            try:
                import json

                row["metadata"] = json.loads(row["metadata"])
            except (TypeError, ValueError):
                row["metadata"] = None
    return rows


def today_workouts(db: Database) -> list[dict[str, Any]]:
    return [w for w in recent_workouts(db, days=1, limit=20)]


def _local_date(ts: int) -> str:
    from datetime import datetime

    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
