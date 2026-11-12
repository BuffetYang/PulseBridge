"""PulsHealth Puls Sync Protocol v1 接收端。

PulsHealth（iOS，免费版支持自动同步 5 类数据）把 HealthKit 数据以 gzip NDJSON
批量 POST 到 ``{base}/v1/batches``。这里实现接收端的最小可用子集：

- 校验 Bearer Token、协议版本、批次头部与行数
- 解析 quantity / category（睡眠）/ workout 样本，转换成本应用的样本结构
- 支持删除行；其他行类型（路线、序列、聚合、活动圆环、profile）忽略
- 按 UUID 幂等入库

协议参考: https://github.com/pulshealth/pulshealth/blob/main/docs/protocol/README.md
"""

from __future__ import annotations

import json
import re
import zlib
from dataclasses import dataclass, field
from typing import Any

from .util import normalize_sleep_stage, normalize_type, normalize_workout_type

PROTOCOL_VERSION = 1
MAX_DECODED = 128 * 1024 * 1024
MAX_SAMPLES_PER_BATCH = 200_000

KINDS = {
    "quantity",
    "category",
    "workout",
    "heartbeatSeries",
    "ecg",
    "stateOfMind",
    "medicationDose",
}

_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-([0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$"
)
_COUNT_KEYS = (
    "sampleCount",
    "deletionCount",
    "routeCount",
    "seriesCount",
    "aggregateCount",
    "activitySummaryCount",
    "profileCount",
)


class PulsError(Exception):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


class UnsupportedProtocol(PulsError):
    def __init__(self, message: str = "unsupported protocol version") -> None:
        super().__init__(message, 400)


@dataclass
class PulsBatch:
    header: dict[str, Any]
    samples: list[dict[str, Any]] = field(default_factory=list)
    workouts: list[dict[str, Any]] = field(default_factory=list)
    deletions: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.samples) + len(self.workouts)


def is_uuid(value: Any) -> bool:
    return isinstance(value, str) and bool(_UUID_RE.match(value))


def decompress_body(raw: bytes, encoding: str | None) -> str:
    """把请求体解成 UTF-8 NDJSON，限制解压后大小，防止 zip bomb。"""
    encoding = (encoding or "").strip().lower()
    if encoding in ("", "identity"):
        if len(raw) > MAX_DECODED:
            raise PulsError("decompressed body too large", 413)
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise PulsError(f"body is not UTF-8: {exc}") from exc
    if encoding != "gzip":
        raise PulsError(f"unsupported Content-Encoding: {encoding}")

    output = bytearray()
    remaining = raw
    while remaining:
        decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
        try:
            output += decoder.decompress(remaining, MAX_DECODED + 1 - len(output))
        except zlib.error as exc:
            raise PulsError(f"invalid gzip body: {exc}") from exc
        if len(output) > MAX_DECODED:
            raise PulsError("decompressed body too large", 413)
        if not decoder.eof:
            raise PulsError("invalid gzip body: truncated")
        remaining = decoder.unused_data
    try:
        return bytes(output).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PulsError(f"body is not UTF-8: {exc}") from exc


def _parse_json_line(raw: str, where: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except ValueError as exc:
        raise PulsError(f"{where}: invalid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise PulsError(f"{where}: expected a JSON object")
    return value


def _ms(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value == 0 or not (-62135596800000 <= value <= 253402300799999):
        return None
    return float(value)


def _sleep_category(value: Any) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return "asleep_unspecified"
    return normalize_sleep_stage(float(value), None)


def _convert_sample(line: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    kind = line.get("kind")
    sample_uuid = str(line.get("uuid") or "").lower()
    start_ms = _ms(line.get("start"))
    if not sample_uuid or not kind or start_ms is None:
        return None
    end_ms = _ms(line.get("end")) or start_ms
    if end_ms < start_ms:
        end_ms = start_ms
    start_ts = int(start_ms / 1000)
    end_ts = max(start_ts, int(end_ms / 1000))
    source = line.get("sourceName")
    device = line.get("device")
    type_id = str(line.get("type") or "")

    if kind == "workout":
        workout = line.get("workout")
        if not isinstance(workout, dict):
            return None
        activity = normalize_workout_type(workout.get("activityType") or "other")
        duration = workout.get("duration")
        distance = workout.get("totalDistanceMeters")
        energy = workout.get("totalEnergyKcal")
        avg_hr = None
        max_hr = None
        details = workout.get("statisticsDetail")
        if isinstance(details, dict):
            heart_rate = details.get("HKQuantityTypeIdentifierHeartRate")
            if isinstance(heart_rate, dict):
                avg_hr = heart_rate.get("avg")
                max_hr = heart_rate.get("max")
        flat = workout.get("statistics")
        if avg_hr is None and isinstance(flat, dict):
            avg_hr = flat.get("HKQuantityTypeIdentifierHeartRate")
        metadata = {"puls_kind": kind, "puls_type": type_id}
        return (
            "workout",
            {
                "uuid": sample_uuid,
                "activity_type": activity,
                "start_ts": start_ts,
                "end_ts": end_ts,
                "duration_s": float(duration) if isinstance(duration, (int, float)) else None,
                "distance_m": float(distance) if isinstance(distance, (int, float)) else None,
                "energy_kcal": float(energy) if isinstance(energy, (int, float)) else None,
                "avg_hr": float(avg_hr) if isinstance(avg_hr, (int, float)) else None,
                "max_hr": float(max_hr) if isinstance(max_hr, (int, float)) else None,
                "source": str(source) if source else None,
                "metadata": metadata,
            },
        )

    if kind not in ("quantity", "category"):
        return None

    type_ = normalize_type(type_id)
    if not type_:
        return None

    value = line.get("value")
    value_text = None
    if kind == "category":
        category = line.get("category")
        if type_ == "sleep_analysis":
            value_text = _sleep_category(category)
            value = None
        else:
            value = float(category) if isinstance(category, (int, float)) else None
    if kind == "quantity" and not isinstance(value, (int, float)):
        value = None
    if value is None and value_text is None:
        return None

    unit = line.get("unit")
    metadata = {"puls_kind": kind, "puls_type": type_id}
    return (
        "sample",
        {
            "uuid": sample_uuid,
            "type": type_,
            "start_ts": start_ts,
            "end_ts": end_ts,
            "value": float(value) if value is not None else None,
            "value_text": value_text,
            "unit": str(unit) if unit else None,
            "source": str(source) if source else None,
            "device": str(device) if device else None,
            "metadata": metadata,
        },
    )


def parse_batch(text: str) -> PulsBatch:
    """解析一个 Puls Sync Protocol v1 批次；无效输入抛 ``PulsError``。"""
    lines = [line for line in text.split("\n") if line.strip()]
    if not lines:
        raise PulsError("empty body")
    header = _parse_json_line(lines[0], "batch header")

    version = header.get("schemaVersion")
    if version is not None and version != PROTOCOL_VERSION:
        raise UnsupportedProtocol(f"schemaVersion {version}")

    if not is_uuid(header.get("batchID")) or not header.get("type"):
        raise PulsError("invalid batch header: batchID must be a UUID and type non-empty")

    counts: dict[str, int] = {}
    for key in _COUNT_KEYS:
        value = header.get(key) or 0
        if isinstance(value, bool) or not isinstance(value, int) or not (0 <= value <= 100_000):
            raise PulsError(f"invalid batch header: {key} must be an integer 0..100000")
        counts[key] = value
    if counts["profileCount"] > 1:
        raise PulsError("invalid batch header: profileCount must be 0 or 1")
    if sum(counts.values()) > MAX_SAMPLES_PER_BATCH:
        raise PulsError("invalid batch header: too many declared lines")

    index = 1
    batch = PulsBatch(header=header)

    def take(where: str) -> dict[str, Any]:
        nonlocal index
        if index >= len(lines):
            raise PulsError(f"{where}: unexpected end of body")
        line = _parse_json_line(lines[index], where)
        index += 1
        return line

    for number in range(1, counts["sampleCount"] + 1):
        line = take(f"sample {number}")
        if not is_uuid(line.get("uuid")) or not line.get("type") or not line.get("kind"):
            raise PulsError(f"sample {number}: bad uuid, type or kind")
        converted = _convert_sample(line)
        if not converted:
            continue
        kind, row = converted
        if kind == "sample":
            batch.samples.append(row)
        else:
            batch.workouts.append(row)

    for number in range(1, counts["deletionCount"] + 1):
        line = take(f"deletion {number}")
        deleted = line.get("deleted")
        if isinstance(deleted, dict) and is_uuid(deleted.get("uuid")):
            batch.deletions.append(str(deleted["uuid"]).lower())

    # 其余行类型（路线、序列、聚合、活动圆环、profile）本应用暂不展示，
    # 但仍需按声明的数量消费掉，保持行对齐。
    skip = (
        counts["routeCount"]
        + counts["seriesCount"]
        + counts["aggregateCount"]
        + counts["activitySummaryCount"]
        + counts["profileCount"]
    )
    for _ in range(skip):
        take("ignored line")

    if index != len(lines):
        raise PulsError("unexpected trailing line after the declared counts")
    return batch
