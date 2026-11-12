"""把 iPhone 快捷指令发来的 JSON 归一化成入库结构。

支持两种载荷：

1. PulseBridge 原生格式（推荐，快捷指令用「词典」直接构造）::

    {
      "device": "iPhone",
      "samples": [
        {"type": "heart_rate", "start": "2026-11-12T08:00:00+08:00",
         "end": "2026-11-12T08:01:00+08:00", "value": 72,
         "unit": "count/min", "source": "Apple Watch"}
      ],
      "workouts": [
        {"type": "running", "start": "...", "end": "...",
         "duration_s": 1800, "distance_m": 5000, "energy_kcal": 320,
         "avg_hr": 152, "max_hr": 171}
      ]
    }

2. Health Auto Export 风格的 ``metrics`` / ``workouts``（尽力兼容，便于手动导出）。
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any, Iterable

from .util import (
    normalize_sleep_stage,
    normalize_type,
    normalize_workout_type,
    parse_timestamp,
    parse_value,
)

MAX_SAMPLES = 50_000
MAX_WORKOUTS = 5_000


@dataclass
class NormalizedPayload:
    samples: list[dict[str, Any]] = field(default_factory=list)
    workouts: list[dict[str, Any]] = field(default_factory=list)
    device: str | None = None
    sent_at: int | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.samples) + len(self.workouts)


def _first(data: dict[str, Any], keys: Iterable[str]) -> Any:
    for key in keys:
        if key in data and data[key] not in (None, ""):
            return data[key]
    return None


def _stable_uuid(*parts: Any) -> str:
    raw = "|".join("" if part is None else str(part) for part in parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _numeric(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, dict):
        for key in ("qty", "quantity", "value", "doubleValue", "amount", "avg"):
            if key in value:
                return _numeric(value[key])
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    # HH:MM:SS（快捷指令的 Duration 可能以这种形式出现）
    if re.fullmatch(r"\d{1,2}:\d{2}(:\d{2})?", text):
        parts = [int(p) for p in text.split(":")]
        while len(parts) < 3:
            parts.insert(0, 0)
        return float(parts[0] * 3600 + parts[1] * 60 + parts[2])
    try:
        return float(text)
    except ValueError:
        return None


def _unit(value: Any) -> str | None:
    if isinstance(value, dict):
        for key in ("units", "unit", "unitString"):
            if value.get(key):
                return str(value[key])
        return None
    return str(value) if value else None


def _distance_m(value: Any, unit: str | None) -> float | None:
    number = _numeric(value)
    if number is None:
        return None
    unit_key = (unit or "").strip().lower()
    if unit_key in {"km", "kilometer", "kilometers", "公里", "千米"}:
        return number * 1000.0
    if unit_key in {"mi", "mile", "miles", "英里"}:
        return number * 1609.344
    if unit_key in {"ft", "feet", "英尺"}:
        return number * 0.3048
    return number


def _energy_kcal(value: Any, unit: str | None) -> float | None:
    number = _numeric(value)
    if number is None:
        return None
    if (unit or "").strip().lower() in {"kj", "kilojoule", "kilojoules", "千焦"}:
        return number * 0.239006
    return number


def _extract_sample_items(payload: dict[str, Any]) -> list[Any]:
    for key in ("samples", "health_samples", "metrics"):
        raw = payload.get(key)
        if isinstance(raw, list):
            # Health Auto Export: metrics: [{name, units, data: [{date, qty}]}]
            if any(isinstance(item, dict) and isinstance(item.get("data"), list) for item in raw):
                expanded: list[Any] = []
                for item in raw:
                    if isinstance(item, dict) and isinstance(item.get("data"), list):
                        name = _first(item, ("name", "type", "identifier"))
                        unit = _first(item, ("units", "unit"))
                        for point in item["data"]:
                            if isinstance(point, dict):
                                merged = dict(point)
                                merged.setdefault("type", name)
                                merged.setdefault("unit", unit)
                                expanded.append(merged)
                    else:
                        expanded.append(item)
                return expanded
            return raw
    data = payload.get("data")
    if isinstance(data, dict):
        return _extract_sample_items(data)
    return []


def _extract_workout_items(payload: dict[str, Any]) -> list[Any]:
    for key in ("workouts", "workout"):
        raw = payload.get(key)
        if isinstance(raw, list):
            return raw
    data = payload.get("data")
    if isinstance(data, dict):
        return _extract_workout_items(data)
    return []


def normalize_sample(
    raw: dict[str, Any], default_device: str | None = None
) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    type_ = normalize_type(
        _first(raw, ("type", "name", "metric", "identifier", "sample_type", "health_type"))
    )
    if not type_:
        return None
    start_ts = parse_timestamp(
        _first(raw, ("start", "start_ts", "startDate", "start_date", "startTime", "date"))
    )
    if start_ts is None:
        return None
    end_ts = parse_timestamp(
        _first(raw, ("end", "end_ts", "endDate", "end_date", "endTime", "end_time"))
    )
    if end_ts is None or end_ts < start_ts:
        end_ts = start_ts

    raw_value = _first(raw, ("value", "qty", "quantity", "amount"))
    value, value_text = parse_value(raw_value)
    if type_ == "sleep_analysis":
        value_text = normalize_sleep_stage(value, value_text)
        value = None  # 睡眠阶段用文本表达，时长由起止时间计算

    unit = _first(raw, ("unit", "units", "unitString"))
    source = _first(raw, ("source", "source_name", "sourceName", "app"))
    device = _first(raw, ("device", "device_name")) or default_device
    uuid = _first(raw, ("uuid", "id", "sample_uuid"))

    if value is None and value_text is None:
        return None

    if not uuid:
        uuid = _stable_uuid(type_, start_ts, end_ts, value, value_text, source, unit)

    return {
        "uuid": str(uuid),
        "type": type_,
        "start_ts": start_ts,
        "end_ts": end_ts,
        "value": value,
        "value_text": value_text,
        "unit": str(unit) if unit else None,
        "source": str(source) if source else None,
        "device": str(device) if device else None,
        "metadata": raw.get("metadata") if isinstance(raw.get("metadata"), dict) else None,
    }


def normalize_workout(
    raw: dict[str, Any], default_device: str | None = None
) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    activity = normalize_workout_type(
        _first(
            raw,
            (
                "activity_type",
                "activityType",
                "type",
                "workoutActivityType",
                "activity",
                "name",
            ),
        )
    )
    start_ts = parse_timestamp(
        _first(raw, ("start", "start_ts", "startDate", "start_date", "startTime"))
    )
    if start_ts is None:
        return None
    end_ts = parse_timestamp(
        _first(raw, ("end", "end_ts", "endDate", "end_date", "endTime"))
    )
    duration = _numeric(_first(raw, ("duration_s", "durationSeconds", "duration")))
    if duration is None and end_ts is not None and end_ts >= start_ts:
        duration = float(end_ts - start_ts)
    if end_ts is None:
        end_ts = start_ts + int(duration or 0)

    distance_raw = _first(raw, ("distance_m", "distance", "distanceMeters", "distance_km"))
    distance_value = None
    distance_unit = None
    if isinstance(distance_raw, dict):
        distance_value = _numeric(distance_raw)
        distance_unit = _unit(distance_raw)
    elif distance_raw is not None:
        distance_value = _numeric(distance_raw)
        distance_unit = _first(raw, ("distance_unit", "distanceUnit"))
        if _first(raw, ("distance_m",)) is not None:
            distance_unit = "m"
    if _first(raw, ("distance_km",)) is not None:
        distance_unit = "km"

    energy_raw = _first(
        raw, ("energy_kcal", "active_energy", "energy", "calories", "activeEnergyBurned")
    )
    energy_value = _numeric(energy_raw)
    energy_unit = _unit(energy_raw) or _first(raw, ("energy_unit", "energyUnit"))
    if _first(raw, ("energy_kcal",)) is not None:
        energy_unit = "kcal"

    avg_hr = _numeric(_first(raw, ("avg_hr", "average_heart_rate", "averageHeartRate")))
    max_hr = _numeric(_first(raw, ("max_hr", "maximum_heart_rate", "maximumHeartRate")))
    hr_raw = _first(raw, ("heartRate", "heart_rate"))
    if isinstance(hr_raw, dict):
        avg_hr = avg_hr if avg_hr is not None else _numeric(hr_raw.get("avg"))
        max_hr = max_hr if max_hr is not None else _numeric(hr_raw.get("max"))
    if isinstance(_first(raw, ("avg_hr",)), dict):
        avg_hr = _numeric(_first(raw, ("avg_hr",)))

    source = _first(raw, ("source", "source_name", "sourceName"))
    device = _first(raw, ("device", "device_name")) or default_device
    uuid = _first(raw, ("uuid", "id", "workout_uuid"))
    distance_m = _distance_m(distance_value, distance_unit)
    energy_kcal = _energy_kcal(energy_value, energy_unit)
    if not uuid:
        # 同一场运动可能同时来自 iPhone 与 Watch，来源不计入指纹以便去重
        uuid = _stable_uuid(
            "workout",
            activity,
            start_ts,
            end_ts,
            round(duration or 0),
            round(distance_m or 0),
            round(energy_kcal or 0),
        )

    return {
        "uuid": str(uuid),
        "activity_type": activity or "other",
        "start_ts": start_ts,
        "end_ts": end_ts,
        "duration_s": duration,
        "distance_m": distance_m,
        "energy_kcal": energy_kcal,
        "avg_hr": avg_hr,
        "max_hr": max_hr,
        "source": str(source) if source else None,
        "metadata": raw.get("metadata") if isinstance(raw.get("metadata"), dict) else None,
        "device": str(device) if device else None,
    }


def normalize_payload(payload: dict[str, Any]) -> NormalizedPayload:
    if not isinstance(payload, dict):
        raise ValueError("请求体必须是 JSON 对象")

    device = _first(payload, ("device", "device_name", "source"))
    device = str(device) if device else None
    sent_at = parse_timestamp(_first(payload, ("sent_at", "sentAt", "timestamp")))

    result = NormalizedPayload(device=device, sent_at=sent_at)

    sample_items = _extract_sample_items(payload)
    if len(sample_items) > MAX_SAMPLES:
        result.warnings.append(f"样本数量超过 {MAX_SAMPLES}，已截断")
        sample_items = sample_items[:MAX_SAMPLES]
    for item in sample_items:
        sample = normalize_sample(item, device)
        if sample:
            result.samples.append(sample)

    workout_items = _extract_workout_items(payload)
    if len(workout_items) > MAX_WORKOUTS:
        result.warnings.append(f"运动记录数量超过 {MAX_WORKOUTS}，已截断")
        workout_items = workout_items[:MAX_WORKOUTS]
    for item in workout_items:
        workout = normalize_workout(item, device)
        if workout:
            result.workouts.append(workout)

    if not result.samples and not result.workouts:
        raise ValueError("请求中没有可识别的 samples 或 workouts")

    return result
