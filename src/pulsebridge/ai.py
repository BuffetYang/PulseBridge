"""AI 健康周报：本地规则分析 + 可选的用户自有模型。

隐私约定：
- 默认不调用任何网络服务，只根据本地 SQLite 统计数据生成规则周报；
- 只有用户显式配置并点击「生成周报」时，才把聚合统计（7/30 天平均值等）
  发给他自己填写的 API 地址或本地 Ollama；
- 不内置、不读取任何第三方 API Key。
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from . import analytics
from .db import Database
from .util import display_activity

APP_USER_AGENT = "PulseBridge-AI/1.0"

GLM_BASE_URL = "https://open.bigmodel.cn/api/paas/v4"
GLM_MODEL = "glm-4.7-flash"
GLM_VISION_MODEL = "glm-4.6v-flash"
DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"
DEEPSEEK_MODEL = "deepseek-flash"
OLLAMA_BASE_URL = "http://127.0.0.1:11434"
OLLAMA_MODEL = "qwen2.5:7b"


class AIError(RuntimeError):
    """模型调用失败（网络、鉴权、返回格式等）。"""


@dataclass
class AIConfig:
    provider: str = "none"  # none | openai | ollama
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    timeout: int = 90
    max_tokens: int = 4096
    temperature: float = 0.4

    @property
    def enabled(self) -> bool:
        return (
            self.provider in ("openai", "ollama")
            and bool(self.base_url.strip())
            and bool(self.model.strip())
        )


def ai_config_from_config(config: Any) -> AIConfig:
    """从 Config（或任意带 get 的对象）读取模型设置。"""
    try:
        timeout = int(config.get("ai_timeout", 90) or 90)
    except (TypeError, ValueError):
        timeout = 90
    try:
        max_tokens = int(config.get("ai_max_tokens", 4096) or 4096)
    except (TypeError, ValueError):
        max_tokens = 4096
    return AIConfig(
        provider=str(config.get("ai_provider") or "none").strip().lower(),
        base_url=str(config.get("ai_base_url") or "").strip(),
        api_key=str(config.get("ai_api_key") or "").strip(),
        model=str(config.get("ai_model") or "").strip(),
        timeout=max(10, min(timeout, 300)),
        max_tokens=max(256, min(max_tokens, 8000)),
    )


# ---------------------------------------------------------------------------
# 模型调用
# ---------------------------------------------------------------------------

def openai_chat_url(base_url: str) -> str:
    """把用户填写的 Base URL 规范化为 OpenAI 兼容的 chat/completions 地址。"""
    base = (base_url or "").strip().rstrip("/")
    if not base:
        raise AIError("未填写 API 地址")
    if base.endswith("/chat/completions"):
        return base
    path = urllib.parse.urlparse(base).path.rstrip("/")
    if path in ("", "/"):
        return base + "/v1/chat/completions"
    return base + "/chat/completions"


def ollama_chat_url(base_url: str) -> str:
    base = (base_url or "").strip().rstrip("/")
    if not base:
        raise AIError("未填写 Ollama 地址")
    if base.endswith("/api/chat"):
        return base
    if base.endswith("/api"):
        return base + "/chat"
    return base + "/api/chat"


def _read_error(body: str) -> str:
    """从错误响应里提取可读信息，不包含请求头或密钥。"""
    try:
        data = json.loads(body)
    except (TypeError, ValueError):
        return body.strip()[:600] or "空响应"
    if isinstance(data, dict):
        error = data.get("error")
        if isinstance(error, dict):
            message = error.get("message") or error.get("code")
            if message:
                return str(message)[:600]
        if error:
            return str(error)[:600]
        message = data.get("message")
        if message:
            return str(message)[:600]
    return body.strip()[:600] or "未知错误"


def _post_json(
    url: str, payload: dict[str, Any], headers: dict[str, str], timeout: int
) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=body, method="POST")
    request.add_header("Content-Type", "application/json; charset=utf-8")
    request.add_header("User-Agent", APP_USER_AGENT)
    for key, value in headers.items():
        request.add_header(key, value)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        raise AIError(f"HTTP {exc.code}：{_read_error(detail)}") from exc
    except urllib.error.URLError as exc:
        raise AIError(f"连接失败：{exc.reason}") from exc
    except TimeoutError as exc:
        raise AIError("请求超时，请检查网络或减小模型上下文") from exc
    try:
        data = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise AIError("模型返回的不是有效 JSON") from exc
    if not isinstance(data, dict):
        raise AIError("模型返回格式异常")
    return data


def _message_content(
    payload: dict[str, Any], allow_empty_content: bool = False
) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        error = payload.get("error")
        if error:
            raise AIError(_read_error(json.dumps(payload, ensure_ascii=False)))
        raise AIError("模型没有返回 choices")
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, list):
        content = "".join(
            str(part.get("text") or "")
            for part in content
            if isinstance(part, dict)
        )
    if not isinstance(content, str) or not content.strip():
        if allow_empty_content:
            return ""
        raise AIError("模型返回了空内容")
    return content.strip()


def call_openai_compatible(
    config: AIConfig,
    messages: list[dict[str, str]],
    max_tokens: int | None = None,
    allow_empty_content: bool = False,
) -> str:
    headers: dict[str, str] = {}
    if config.api_key:
        headers["Authorization"] = f"Bearer {config.api_key}"
    payload = {
        "model": config.model,
        "messages": messages,
        "temperature": config.temperature,
        "max_tokens": max_tokens or config.max_tokens,
        "stream": False,
    }
    data = _post_json(openai_chat_url(config.base_url), payload, headers, config.timeout)
    return _message_content(data, allow_empty_content=allow_empty_content)


def call_ollama(
    config: AIConfig,
    messages: list[dict[str, str]],
    max_tokens: int | None = None,
    allow_empty_content: bool = False,
) -> str:
    payload = {
        "model": config.model,
        "messages": messages,
        "stream": False,
        "options": {
            "temperature": config.temperature,
            "num_predict": max_tokens or config.max_tokens,
        },
    }
    data = _post_json(
        ollama_chat_url(config.base_url), payload, {}, config.timeout
    )
    if isinstance(data.get("error"), str):
        raise AIError(str(data["error"])[:600])
    message = data.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str) or not content.strip():
        if allow_empty_content:
            return ""
        raise AIError("Ollama 返回了空内容")
    return content.strip()


def call_model(
    config: AIConfig,
    messages: list[dict[str, str]],
    max_tokens: int | None = None,
    allow_empty_content: bool = False,
) -> str:
    if config.provider == "ollama":
        return call_ollama(
            config, messages, max_tokens, allow_empty_content
        )
    if config.provider == "openai":
        return call_openai_compatible(
            config, messages, max_tokens, allow_empty_content
        )
    raise AIError("未配置模型")


def test_connection(config: AIConfig) -> tuple[bool, str]:
    if not config.enabled:
        return False, "请先填写 API 地址和模型名称"
    try:
        reply = call_model(
            config,
            [
                {
                    "role": "user",
                    "content": "这是连接测试。请只回复两个字母：OK。不要解释，不要输出思考过程。",
                }
            ],
            max_tokens=1024,
            allow_empty_content=True,
        )
    except AIError as exc:
        return False, str(exc)
    if not reply:
        return True, "模型已响应（处于思考模式，未返回文本）"
    return True, reply[:120]


def clean_markdown(text: str) -> str:
    content = (text or "").strip()
    if content.startswith("```"):
        lines = content.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        content = "\n".join(lines).strip()
    return content


# ---------------------------------------------------------------------------
# 周报上下文
# ---------------------------------------------------------------------------

_METRICS = (
    ("steps", "步数", "步", 0, True),
    ("active_energy", "活动能量", "kcal", 0, True),
    ("exercise_minutes", "锻炼时间", "分钟", 0, True),
    ("resting_heart_rate", "静息心率", "bpm", 0, False),
    ("hrv", "HRV", "ms", 0, False),
    ("oxygen_saturation", "血氧", "%", 0, False),
    ("respiratory_rate", "呼吸频率", "次/分", 1, False),
    ("wrist_temperature", "手腕温度", "°C", 1, False),
    ("body_mass", "体重", "kg", 1, False),
    ("vo2max", "最大摄氧量", "mL/min·kg", 1, False),
    ("daylight_minutes", "日照", "分钟", 0, True),
)


def _metric_points(db: Database, metric: str, days: int) -> list[dict[str, Any]]:
    if metric == "resting_heart_rate":
        raw = analytics.resting_heart_rate_series(db, days)
        return [
            {
                "date": point["date"],
                "value": analytics.display_value(metric, point.get("value")),
                "estimated": bool(point.get("estimated")),
            }
            for point in raw
        ]
    raw = analytics.daily_series(db, metric, days)
    return [
        {
            "date": point["date"],
            "value": analytics.display_value(metric, point.get("value")),
        }
        for point in raw
    ]


def _stats(points: list[dict[str, Any]], cumulative: bool) -> dict[str, Any] | None:
    values = [float(p["value"]) for p in points if p.get("value") is not None]
    if not values:
        return None
    return {
        "avg": sum(values) / len(values),
        "min": min(values),
        "max": max(values),
        "total": sum(values) if cumulative else None,
        "data_days": len(values),
    }


def _metric_context(
    db: Database,
    metric: str,
    label: str,
    unit: str,
    digits: int,
    cumulative: bool,
    days: int,
    baseline_days: int,
) -> dict[str, Any] | None:
    points = _metric_points(db, metric, days)
    baseline = _metric_points(db, metric, baseline_days)
    current = _stats(points, cumulative)
    base = _stats(baseline, cumulative)
    if current is None and base is None:
        return None

    def rounded(value: Any) -> Any:
        return round(float(value), digits) if value is not None else None

    delta = None
    if current and base and base.get("avg"):
        delta = (current["avg"] - base["avg"]) / base["avg"] * 100.0

    estimated_days = sum(1 for point in points if point.get("estimated"))
    change = None
    valid = [float(p["value"]) for p in points if p.get("value") is not None]
    if len(valid) >= 2:
        change = valid[-1] - valid[0]

    return {
        "label": label,
        "unit": unit,
        "digits": digits,
        "cumulative": cumulative,
        "avg": rounded(current["avg"]) if current else None,
        "min": rounded(current["min"]) if current else None,
        "max": rounded(current["max"]) if current else None,
        "total": rounded(current["total"]) if current else None,
        "data_days": current["data_days"] if current else 0,
        "baseline_avg": rounded(base["avg"]) if base else None,
        "delta_pct": round(delta, 1) if delta is not None else None,
        "change": rounded(change),
        "estimated_days": estimated_days if metric == "resting_heart_rate" else 0,
    }


def _avg(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _sleep_context(db: Database, days: int, baseline_days: int) -> dict[str, Any]:
    today = datetime.now().date()
    cutoff = (today - timedelta(days=days - 1)).isoformat()
    baseline_cutoff = (today - timedelta(days=baseline_days - 1)).isoformat()
    nights = [
        night
        for night in analytics.sleep_nights(db, days)
        if float(night.get("asleep_min") or 0) > 0
        and str(night.get("date") or "") >= cutoff
    ]
    baseline = [
        night
        for night in analytics.sleep_nights(db, baseline_days)
        if float(night.get("asleep_min") or 0) > 0
        and str(night.get("date") or "") >= baseline_cutoff
    ]

    def minutes(items: list[dict[str, Any]], key: str) -> float | None:
        return _avg([float(item.get(key) or 0) for item in items])

    avg_asleep = minutes(nights, "asleep_min")
    base_asleep = minutes(baseline, "asleep_min")
    avg_deep = minutes(nights, "deep_min")
    avg_rem = minutes(nights, "rem_min")
    avg_awake = minutes(nights, "awake_min")
    delta = None
    if avg_asleep and base_asleep:
        delta = (avg_asleep - base_asleep) / base_asleep * 100.0

    last_night = analytics.last_night(db)
    last = None
    if last_night:
        last = {
            "date": last_night["date"],
            "asleep_hours": round(float(last_night["asleep_min"]) / 60.0, 1),
            "deep_min": round(float(last_night["deep_min"])),
            "rem_min": round(float(last_night["rem_min"])),
            "start": datetime.fromtimestamp(int(last_night["start_ts"])).strftime("%H:%M"),
            "end": datetime.fromtimestamp(int(last_night["end_ts"])).strftime("%H:%M"),
        }

    return {
        "nights": len(nights),
        "avg_hours": round(avg_asleep / 60.0, 1) if avg_asleep else None,
        "avg_deep_min": round(avg_deep) if avg_deep else None,
        "avg_rem_min": round(avg_rem) if avg_rem else None,
        "avg_awake_min": round(avg_awake) if avg_awake else None,
        "baseline_hours": round(base_asleep / 60.0, 1) if base_asleep else None,
        "delta_pct": round(delta, 1) if delta is not None else None,
        "last_night": last,
    }


def _workout_context(db: Database, days: int, baseline_days: int) -> dict[str, Any]:
    start = int(datetime.now().timestamp()) - (days - 1) * 86400
    start = datetime.fromtimestamp(start).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    since = int(start.timestamp())
    baseline_since = int(
        (start - timedelta(days=max(0, baseline_days - days))).timestamp()
    )

    rows = analytics.workout_history(db, since, limit=2000)
    baseline_rows = analytics.workout_history(db, baseline_since, limit=5000)

    total_seconds = sum(float(row.get("duration_s") or 0) for row in rows)
    baseline_seconds = sum(float(row.get("duration_s") or 0) for row in baseline_rows)
    total_energy = sum(float(row.get("energy_kcal") or 0) for row in rows)
    by_type: dict[str, int] = {}
    hr_weighted = 0.0
    hr_seconds = 0.0
    for row in rows:
        label = display_activity(str(row.get("activity_type") or "other"))
        by_type[label] = by_type.get(label, 0) + 1
        if row.get("avg_hr") and row.get("duration_s"):
            seconds = float(row["duration_s"])
            hr_weighted += float(row["avg_hr"]) * seconds
            hr_seconds += seconds

    longest = max(
        rows,
        key=lambda row: float(row.get("duration_s") or 0),
        default=None,
    )
    longest_info = None
    if longest:
        longest_info = {
            "type": display_activity(str(longest.get("activity_type") or "other")),
            "minutes": round(float(longest.get("duration_s") or 0) / 60.0),
        }

    return {
        "count": len(rows),
        "total_minutes": round(total_seconds / 60.0),
        "total_energy": round(total_energy),
        "avg_hr": round(hr_weighted / hr_seconds) if hr_seconds else None,
        "by_type": by_type,
        "longest": longest_info,
        "baseline_count": len(baseline_rows),
        "baseline_total_minutes": round(baseline_seconds / 60.0),
    }


def _build_flags(context: dict[str, Any]) -> list[str]:
    flags: list[str] = []
    sleep = context.get("sleep") or {}
    hours = sleep.get("avg_hours")
    if hours is not None and hours < 7.0:
        flags.append(f"平均睡眠 {hours:.1f} 小时，低于 7 小时")
    if hours is not None and hours < 6.0:
        flags.append("睡眠明显不足，建议优先保证休息")

    metrics = context.get("metrics") or {}
    resting = metrics.get("resting_heart_rate") or {}
    if resting.get("delta_pct") is not None and resting["delta_pct"] > 5:
        flags.append(f"静息心率较基线升高 {resting['delta_pct']:+.0f}%")
    hrv = metrics.get("hrv") or {}
    if hrv.get("delta_pct") is not None and hrv["delta_pct"] < -15:
        flags.append(f"HRV 较基线下降 {hrv['delta_pct']:+.0f}%")

    oxygen = metrics.get("oxygen_saturation") or {}
    if oxygen.get("avg") is not None and oxygen["avg"] < 95:
        flags.append(f"平均血氧 {oxygen['avg']:.0f}%，偏低")

    breathing = metrics.get("respiratory_rate") or {}
    if (
        breathing.get("avg") is not None
        and breathing.get("baseline_avg") is not None
        and breathing["avg"] > breathing["baseline_avg"] + 2
    ):
        flags.append("呼吸频率高于基线")

    temperature = metrics.get("wrist_temperature") or {}
    if (
        temperature.get("avg") is not None
        and temperature.get("baseline_avg") is not None
        and temperature["avg"] > temperature["baseline_avg"] + 0.3
    ):
        flags.append("手腕温度高于基线")

    weight = metrics.get("body_mass") or {}
    if weight.get("change") is not None and abs(weight["change"]) >= 2:
        flags.append(f"本周体重变化 {weight['change']:+.1f} kg")

    steps = metrics.get("steps") or {}
    if steps.get("delta_pct") is not None and steps["delta_pct"] < -20:
        flags.append(f"步数较基线下降 {steps['delta_pct']:+.0f}%")

    workouts = context.get("workouts") or {}
    if workouts.get("count") == 0:
        flags.append("本周没有训练记录")

    missing = context.get("data_quality", {}).get("missing_metrics") or []
    if len(missing) >= 3:
        flags.append("部分指标数据不足，结论仅供参考")
    return flags


def build_weekly_context(
    db: Database, days: int = 7, baseline_days: int = 30
) -> dict[str, Any]:
    """构造周报所需的聚合统计（不含原始样本）。"""
    days = max(1, int(days))
    baseline_days = max(days, int(baseline_days))
    dates = analytics.date_range(days)
    metrics: dict[str, Any] = {}
    missing: list[str] = []
    for metric, label, unit, digits, cumulative in _METRICS:
        block = _metric_context(
            db, metric, label, unit, digits, cumulative, days, baseline_days
        )
        if block is None:
            missing.append(label)
            continue
        if block.get("data_days", 0) == 0:
            missing.append(label)
        metrics[metric] = block

    context: dict[str, Any] = {
        "period": {
            "start": dates[0],
            "end": dates[-1],
            "days": days,
            "baseline_days": baseline_days,
        },
        "metrics": metrics,
        "sleep": _sleep_context(db, days, baseline_days),
        "workouts": _workout_context(db, days, baseline_days),
        "activity_rings": analytics.activity_rings(db),
        "data_quality": {
            "missing_metrics": missing,
            "last_sync_ts": db.stats().get("last_sync_ts"),
        },
        "generated_at": int(datetime.now().timestamp()),
    }
    context["flags"] = _build_flags(context)
    return context


# ---------------------------------------------------------------------------
# 报告生成
# ---------------------------------------------------------------------------

def _num(value: Any, digits: int = 1) -> str:
    if value is None:
        return "--"
    return f"{float(value):.{digits}f}"


def _delta(value: Any) -> str:
    if value is None:
        return ""
    return f"，较基线 {float(value):+.0f}%"


def rule_based_report(context: dict[str, Any]) -> str:
    """不调用模型，直接根据统计规则生成中文周报。"""
    period = context.get("period") or {}
    metrics = context.get("metrics") or {}
    sleep = context.get("sleep") or {}
    workouts = context.get("workouts") or {}
    flags = context.get("flags") or []

    lines = [
        "# PulseBridge 健康周报",
        f"{period.get('start', '--')} 至 {period.get('end', '--')}"
        f" · 对比近 {period.get('baseline_days', 30)} 天基线",
        "",
        "## 本周概览",
    ]

    for key in (
        "steps",
        "active_energy",
        "exercise_minutes",
        "resting_heart_rate",
        "hrv",
    ):
        item = metrics.get(key)
        if not item:
            continue
        unit = item["unit"]
        digits = int(item["digits"])
        if item["cumulative"]:
            text = (
                f"日均 {_num(item['avg'], digits)} {unit}，"
                f"7 天合计 {_num(item['total'], digits)} {unit}"
            )
        else:
            text = (
                f"平均 {_num(item['avg'], digits)} {unit}"
                f"（{_num(item['min'], digits)}–{_num(item['max'], digits)}）"
            )
        lines.append(f"- {item['label']}：{text}{_delta(item.get('delta_pct'))}")

    if sleep.get("avg_hours") is not None:
        lines.append(
            f"- 睡眠：平均 {sleep['avg_hours']:.1f} 小时"
            f"，深睡 {int(sleep.get('avg_deep_min') or 0)} 分钟"
            f"，REM {int(sleep.get('avg_rem_min') or 0)} 分钟"
            f"{_delta(sleep.get('delta_pct'))}"
        )
    lines.append(
        f"- 训练：{workouts.get('count', 0)} 次，"
        f"共 {workouts.get('total_minutes', 0)} 分钟"
        f"，消耗 {workouts.get('total_energy', 0)} kcal"
    )

    lines.extend(["", "## 睡眠"])
    if sleep.get("avg_hours") is None:
        lines.append("本周没有足够的睡眠记录。")
    else:
        lines.append(
            f"平均每晚 {sleep['avg_hours']:.1f} 小时，"
            f"深睡 {int(sleep.get('avg_deep_min') or 0)} 分钟、"
            f"REM {int(sleep.get('avg_rem_min') or 0)} 分钟、"
            f"清醒 {int(sleep.get('avg_awake_min') or 0)} 分钟。"
        )
        if sleep.get("last_night"):
            last = sleep["last_night"]
            lines.append(
                f"最近一夜：{last['date']}，{last['start']}–{last['end']}，"
                f"睡眠 {last['asleep_hours']:.1f} 小时。"
            )
        if sleep.get("avg_hours", 0) < 7:
            lines.append("睡眠时长低于常见建议范围，建议优先保证规律作息。")

    lines.extend(["", "## 恢复"])
    recovery_items = (
        ("resting_heart_rate", "静息心率"),
        ("hrv", "HRV"),
        ("oxygen_saturation", "血氧"),
        ("respiratory_rate", "呼吸频率"),
        ("wrist_temperature", "手腕温度"),
    )
    wrote_recovery = False
    for key, label in recovery_items:
        item = metrics.get(key)
        if not item:
            continue
        wrote_recovery = True
        text = f"{label}平均 {_num(item['avg'], int(item['digits']))} {item['unit']}"
        if item.get("delta_pct") is not None:
            text += _delta(item["delta_pct"])
        if key == "resting_heart_rate" and item.get("estimated_days"):
            text += f"（其中 {item['estimated_days']} 天为估算）"
        lines.append(f"- {text}")
    if not wrote_recovery:
        lines.append("本周恢复类指标数据不足。")

    lines.extend(["", "## 训练"])
    if workouts.get("count", 0) == 0:
        lines.append("本周没有训练记录。")
    else:
        type_text = "、".join(
            f"{name} {count} 次"
            for name, count in (workouts.get("by_type") or {}).items()
        )
        lines.append(
            f"共 {workouts.get('count', 0)} 次，"
            f"合计 {workouts.get('total_minutes', 0)} 分钟，"
            f"消耗 {workouts.get('total_energy', 0)} kcal。"
        )
        if type_text:
            lines.append(f"类型：{type_text}。")
        if workouts.get("avg_hr"):
            lines.append(f"训练平均心率约 {workouts['avg_hr']} bpm。")
        if workouts.get("longest"):
            longest = workouts["longest"]
            lines.append(
                f"最长一次：{longest['type']}，{longest['minutes']} 分钟。"
            )
        if workouts.get("baseline_count"):
            lines.append(
                f"近 {period.get('baseline_days', 30)} 天共 "
                f"{workouts.get('baseline_count', 0)} 次训练，可作为训练量的参考。"
            )

    lines.extend(["", "## 需要关注"])
    if flags:
        for flag in flags:
            lines.append(f"- {flag}")
    else:
        lines.append("- 本周没有发现明显异常波动。")

    lines.extend(["", "## 下周建议"])
    suggestions: list[str] = []
    if sleep.get("avg_hours") is not None and sleep["avg_hours"] < 7:
        suggestions.append("把睡眠放在优先位置，尽量固定入睡和起床时间。")
    if (
        (metrics.get("resting_heart_rate") or {}).get("delta_pct", 0) > 5
        or (metrics.get("hrv") or {}).get("delta_pct", 0) < -15
    ):
        suggestions.append("恢复指标偏弱时，减少连续高强度训练，安排轻松活动或休息日。")
    if workouts.get("count", 0) == 0:
        suggestions.append("每周安排 2–3 次中等强度运动，从快走或短时间训练开始。")
    if (metrics.get("steps") or {}).get("delta_pct", 0) < -20:
        suggestions.append("在日程中加入短距离步行，逐步把日均步数拉回基线附近。")
    if not suggestions:
        suggestions.append("保持当前的作息和运动节奏，继续观察趋势变化。")
    for suggestion in suggestions:
        lines.append(f"- {suggestion}")

    missing = context.get("data_quality", {}).get("missing_metrics") or []
    if missing:
        lines.extend(["", f"数据说明：{('、'.join(missing))} 本周记录不足，相关结论仅供参考。"])

    lines.extend(
        [
            "",
            "---",
            "以上内容基于本地健康数据的趋势统计，不构成医疗诊断或治疗建议。"
            "如有持续不适或异常，请咨询专业医生。",
        ]
    )
    return "\n".join(lines)


def build_messages(context: dict[str, Any]) -> list[dict[str, str]]:
    system = (
        "你是 PulseBridge 的健康数据分析助手。你只根据用户提供的统计数据写一份中文健康周报，"
        "不要编造缺失的数据，不做医疗诊断。使用 Markdown，结构为：本周概览、睡眠、恢复、"
        "训练、需要关注、下周建议。引用具体数字；数据不足时明确说明；出现持续异常时建议"
        "咨询医生。语气客观、简洁，控制在 600–900 字。不要输出代码块。"
    )
    user = (
        "以下是本周与 30 天基线的聚合统计（JSON，不含原始样本）：\n"
        + json.dumps(context, ensure_ascii=False, indent=2)
        + "\n\n请生成周报。"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def generate_report(
    config: AIConfig, context: dict[str, Any]
) -> tuple[str, str, str]:
    """返回 ``(内容, 模式, 错误信息)``；模型失败时回退到本地规则版。"""
    fallback = rule_based_report(context)
    if not config.enabled:
        return fallback, "rule", ""
    try:
        content = clean_markdown(call_model(config, build_messages(context)))
        if len(content) < 80:
            raise AIError("模型返回内容过短")
        return content, "llm", ""
    except Exception as exc:  # noqa: BLE001
        return fallback, "rule", str(exc)
