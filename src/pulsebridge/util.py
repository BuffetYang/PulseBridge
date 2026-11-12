"""时间、数值、类型归一化与展示格式化工具。"""

from __future__ import annotations

import math
import re
import socket
import time
from datetime import datetime, timedelta
from typing import Any, Iterable

# ---------------------------------------------------------------------------
# 时间
# ---------------------------------------------------------------------------

_DATE_FORMATS = (
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y/%m/%d %H:%M:%S",
    "%Y-%m-%dT%H:%M",
    "%Y-%m-%d %H:%M",
    "%Y年%m月%d日 %H:%M:%S",
    "%Y年%m月%d日 %H:%M",
    "%Y年%m月%d日",
    "%Y/%m/%d %H:%M",
)


def parse_timestamp(value: Any) -> int | None:
    """把 ISO 8601 / 本地时间 / 秒 / 毫秒时间戳统一成 UTC 秒。"""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        if math.isnan(number) or number <= 0:
            return None
        return int(number / 1000) if number > 1e12 else int(number)

    text = str(value).strip()
    if not text:
        return None

    try:
        number = float(text)
        if number > 0:
            return int(number / 1000) if number > 1e12 else int(number)
    except ValueError:
        pass

    iso = text.replace("Z", "+00:00").replace("z", "+00:00")
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        dt = None
        for fmt in _DATE_FORMATS:
            try:
                dt = datetime.strptime(iso, fmt)
                break
            except ValueError:
                continue
        if dt is None:
            return None
    if dt.tzinfo is None:
        dt = dt.astimezone()  # 视为本地时间
    return int(dt.timestamp())


def now_ts() -> int:
    return int(time.time())


def start_of_local_day(ts: int | None = None, offset_days: int = 0) -> int:
    dt = datetime.fromtimestamp(ts if ts is not None else time.time())
    dt = dt.replace(hour=0, minute=0, second=0, microsecond=0)
    dt += timedelta(days=offset_days)
    return int(dt.timestamp())


def local_date_str(ts: int) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d")


def local_date_label(date_str: str) -> str:
    """``2026-11-12`` -> ``11月12日``。"""
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return date_str
    return f"{dt.month}月{dt.day}日"


def local_time_label(ts: int) -> str:
    return datetime.fromtimestamp(ts).strftime("%H:%M")


def weekday_label(date_str: str) -> str:
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return ""
    return "周" + "一二三四五六日"[dt.weekday()]


def humanize_ago(ts: int | None) -> str:
    if not ts:
        return "从未同步"
    delta = max(0, int(time.time()) - int(ts))
    if delta < 60:
        return "刚刚"
    if delta < 3600:
        return f"{delta // 60} 分钟前"
    if delta < 86400:
        return f"{delta // 3600} 小时前"
    if delta < 86400 * 30:
        return f"{delta // 86400} 天前"
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# 类型归一化
# ---------------------------------------------------------------------------

_TYPE_ALIASES: dict[str, str] = {
    # English / HealthKit identifiers
    "heartrate": "heart_rate",
    "heart": "heart_rate",
    "restingheartrate": "resting_heart_rate",
    "heartratevariability": "hrv",
    "hrv": "hrv",
    "stepcount": "steps",
    "steps": "steps",
    "activeenergyburned": "active_energy",
    "activeenergy": "active_energy",
    "basalenergyburned": "basal_energy",
    "basalenergy": "basal_energy",
    "appleexercisetime": "exercise_minutes",
    "exercisetime": "exercise_minutes",
    "exercise": "exercise_minutes",
    "applewatchstandinghours": "stand_hours",
    "standhours": "stand_hours",
    "oxygensaturation": "oxygen_saturation",
    "oxygensaturationpercentage": "oxygen_saturation",
    "respiratoryrate": "respiratory_rate",
    "vo2max": "vo2max",
    "cardiorespiratoryfitness": "vo2max",
    "bodymass": "body_mass",
    "weight": "body_mass",
    "sleepanalysis": "sleep_analysis",
    "sleep": "sleep_analysis",
    "sleepanalysiscategory": "sleep_analysis",
    "flightsclimbed": "flights_climbed",
    "distancewalkingrunning": "distance",
    "walkingrunningdistance": "distance",
    "distance": "distance",
    "walkingheartrateaverage": "walking_heart_rate",
    "mindfulminutes": "mindful_minutes",
    "wristtemperature": "wrist_temperature",
    "dietaryenergyconsumed": "dietary_energy",
    "protein": "protein",
    "carbohydrates": "carbohydrates",
    "heartratevariabilitysdnn": "hrv",
    # 中文（快捷指令中文界面）
    "心率": "heart_rate",
    "静息心率": "resting_heart_rate",
    "心率变异性": "hrv",
    "步数": "steps",
    "步数计数": "steps",
    "活动能量": "active_energy",
    "静息能量": "basal_energy",
    "锻炼时间": "exercise_minutes",
    "体能训练时间": "exercise_minutes",
    "站立时间": "stand_hours",
    "血氧": "oxygen_saturation",
    "血氧饱和度": "oxygen_saturation",
    "呼吸频率": "respiratory_rate",
    "最大摄氧量": "vo2max",
    "体重": "body_mass",
    "睡眠": "sleep_analysis",
    "睡眠分析": "sleep_analysis",
    "爬楼层数": "flights_climbed",
    "距离": "distance",
    "步行心率平均值": "walking_heart_rate",
    "正念分钟": "mindful_minutes",
    "手腕温度": "wrist_temperature",
}

_WORKOUT_ALIASES: dict[str, str] = {
    "running": "running",
    "run": "running",
    "跑步": "running",
    "户外跑步": "running",
    "室内跑步": "running",
    "walking": "walking",
    "walk": "walking",
    "步行": "walking",
    "户外步行": "walking",
    "cycling": "cycling",
    "biking": "cycling",
    "骑行": "cycling",
    "户外骑行": "cycling",
    "室内骑行": "cycling",
    "hiking": "hiking",
    "徒步": "hiking",
    "swimming": "swimming",
    "游泳": "swimming",
    "strengthtraining": "strength",
    "functionaltraining": "strength",
    "functionalstrengthtraining": "strength",
    "traditionalstrengthtraining": "strength",
    "力量训练": "strength",
    "yoga": "yoga",
    "瑜伽": "yoga",
    "pilates": "pilates",
    "普拉提": "pilates",
    "elliptical": "elliptical",
    "椭圆机": "elliptical",
    "rowing": "rowing",
    "划船": "rowing",
    "highintensityintervaltraining": "hiit",
    "hiit": "hiit",
    "高强度间歇训练": "hiit",
    "coretraining": "core_training",
    "核心训练": "core_training",
    "dance": "dance",
    "danceinspiredtraining": "dance",
    "cardiodance": "dance",
    "socialdance": "social_dance",
    "舞蹈": "dance",
    "tennis": "tennis",
    "网球": "tennis",
    "basketball": "basketball",
    "篮球": "basketball",
    "soccer": "soccer",
    "football": "soccer",
    "足球": "soccer",
    "badminton": "badminton",
    "羽毛球": "badminton",
    "baseball": "baseball",
    "棒球": "baseball",
    "bowling": "bowling",
    "保龄球": "bowling",
    "boxing": "boxing",
    "拳击": "boxing",
    "climbing": "climbing",
    "攀岩": "climbing",
    "cricket": "cricket",
    "板球": "cricket",
    "crosstraining": "cross_training",
    "curling": "curling",
    "冰壶": "curling",
    "equestrian": "equestrian",
    "马术": "equestrian",
    "fencing": "fencing",
    "击剑": "fencing",
    "fishing": "fishing",
    "钓鱼": "fishing",
    "flexibility": "flexibility",
    "柔韧训练": "flexibility",
    "golf": "golf",
    "高尔夫": "golf",
    "gymnastics": "gymnastics",
    "体操": "gymnastics",
    "handball": "handball",
    "手球": "handball",
    "hockey": "hockey",
    "冰球": "hockey",
    "hunting": "hunting",
    "打猎": "hunting",
    "lacrosse": "lacrosse",
    "长曲棍球": "lacrosse",
    "martialarts": "martial_arts",
    "武术": "martial_arts",
    "mindandbody": "mind_and_body",
    "racquetball": "racquetball",
    "壁球": "racquetball",
    "rugby": "rugby",
    "橄榄球": "rugby",
    "sailing": "sailing",
    "帆船": "sailing",
    "softball": "softball",
    "垒球": "softball",
    "squash": "squash",
    "壁球": "squash",
    "tabletennis": "table_tennis",
    "pingpong": "table_tennis",
    "乒乓球": "table_tennis",
    "trackandfield": "track_and_field",
    "田径": "track_and_field",
    "volleyball": "volleyball",
    "排球": "volleyball",
    "waterfitness": "water_fitness",
    "水上健身": "water_fitness",
    "waterpolo": "water_polo",
    "水球": "water_polo",
    "watersports": "water_sports",
    "水上运动": "water_sports",
    "wrestling": "wrestling",
    "摔跤": "wrestling",
    "barre": "barre",
    "kickboxing": "kickboxing",
    "踢拳": "kickboxing",
    "snowboarding": "snowboarding",
    "单板滑雪": "snowboarding",
    "snowsports": "snow_sports",
    "雪上运动": "snow_sports",
    "surfing": "surfing",
    "冲浪": "surfing",
    "paddlesports": "paddle_sports",
    "桨板": "paddle_sports",
    "pickleball": "pickleball",
    "匹克球": "pickleball",
    "swimbikerun": "triathlon",
    "triathlon": "triathlon",
    "铁人三项": "triathlon",
    "transition": "transition",
    "过渡": "transition",
    "diving": "diving",
    "潜水": "diving",
    "cooldown": "cooldown",
    "放松": "cooldown",
    "recovery": "recovery",
    "恢复": "recovery",
    "play": "play",
    "玩耍": "play",
    "wheelchairwalk": "wheelchair_walk",
    "wheelchairrun": "wheelchair_run",
    "taichi": "tai_chi",
    "太极": "tai_chi",
    "handcycling": "hand_cycling",
    "discsports": "disc_sports",
    "飞盘": "disc_sports",
    "fitnessgaming": "fitness_gaming",
    "skiing": "skiing",
    "滑雪": "skiing",
    "skating": "skating",
    "滑冰": "skating",
    "jumprope": "jump_rope",
    "跳绳": "jump_rope",
    "stairclimbing": "stair_climbing",
    "爬楼": "stair_climbing",
    "mixedcardio": "mixed_cardio",
    "混合有氧": "mixed_cardio",
    "other": "other",
    "其他": "other",
}

# HealthKit 的 HKWorkoutActivityType 原始值兜底（PulsHealth 对未映射类型发送 activity_<n>）
_HK_WORKOUT_NUMBERS: dict[int, str] = {
    4: "badminton",  # HKWorkoutActivityTypeBadminton
}


def _slug(text: Any) -> str:
    raw = str(text or "").strip()
    key = re.sub(r"[^0-9a-z一-鿿]+", "", raw.lower())
    return key


def normalize_type(raw: Any) -> str:
    """把健康数据类型归一化为稳定的 snake_case。"""
    key = _slug(raw)
    if not key:
        return ""
    for prefix in ("hkquantitytypeidentifier", "hkcategorytypeidentifier"):
        if key.startswith(prefix):
            key = key[len(prefix) :]
    return _TYPE_ALIASES.get(key, key)


def normalize_workout_type(raw: Any) -> str:
    key = _slug(raw)
    if key.startswith("hkworkoutactivitytype"):
        key = key[len("hkworkoutactivitytype") :]
    if key.startswith("activity") and key[8:].isdigit():
        return _HK_WORKOUT_NUMBERS.get(int(key[8:]), "other")
    return _WORKOUT_ALIASES.get(key, key or "other")


# ---------------------------------------------------------------------------
# 数值与睡眠阶段
# ---------------------------------------------------------------------------

def parse_value(raw: Any) -> tuple[float | None, str | None]:
    """返回 ``(数值, 文本值)``；文本值用于睡眠阶段等枚举型数据。"""
    if raw is None:
        return None, None
    if isinstance(raw, bool):
        return (1.0 if raw else 0.0), None
    if isinstance(raw, (int, float)):
        return float(raw), None
    text = str(raw).strip()
    if not text:
        return None, None
    try:
        return float(text), None
    except ValueError:
        return None, text


_SLEEP_STAGE_ALIASES = {
    "inbed": "in_bed",
    "in_bed": "in_bed",
    "在床上": "in_bed",
    "awake": "awake",
    "清醒": "awake",
    "asleep": "asleep_unspecified",
    "asleepunspecified": "asleep_unspecified",
    "asleep_unspecified": "asleep_unspecified",
    "睡眠": "asleep_unspecified",
    "asleepcore": "core",
    "core": "core",
    "核心": "core",
    "asleepdeep": "deep",
    "deep": "deep",
    "深度": "deep",
    "asleeprem": "rem",
    "rem": "rem",
    "快速动眼": "rem",
    "快速动眼睡眠": "rem",
    # 旧版数值编码
    "0": "in_bed",
    "1": "asleep_unspecified",
    "2": "awake",
    "3": "core",
    "4": "deep",
    "5": "rem",
}

_SLEEP_NUMERIC_STAGES = {
    0: "in_bed",
    1: "asleep_unspecified",
    2: "awake",
    3: "core",
    4: "deep",
    5: "rem",
}


def normalize_sleep_stage(value: float | None, text: str | None) -> str:
    if text:
        key = _slug(text)
        if key in _SLEEP_STAGE_ALIASES:
            return _SLEEP_STAGE_ALIASES[key]
    if value is not None:
        try:
            return _SLEEP_NUMERIC_STAGES.get(int(value), "asleep_unspecified")
        except (TypeError, ValueError):
            pass
    return "asleep_unspecified"


# ---------------------------------------------------------------------------
# 展示格式
# ---------------------------------------------------------------------------

def fmt_int(value: float | None) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "--"
    return f"{int(round(value)):,}"


def fmt_float(value: float | None, digits: int = 1) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "--"
    if digits <= 0:
        return f"{int(round(value)):,}"
    text = f"{value:,.{digits}f}"
    return text


def fmt_duration(minutes: float | None, compact: bool = False) -> str:
    if minutes is None or minutes <= 0:
        return "--"
    total = int(round(minutes))
    hours, mins = divmod(total, 60)
    if hours and mins:
        return f"{hours}{'h' if compact else ' 小时'} {mins}{'m' if compact else ' 分钟'}"
    if hours:
        return f"{hours}{'h' if compact else ' 小时'}"
    return f"{mins}{'m' if compact else ' 分钟'}"


def fmt_distance(meters: float | None) -> str:
    if not meters or meters <= 0:
        return "--"
    if meters >= 1000:
        return f"{meters / 1000:.2f} km"
    return f"{int(meters)} m"


def fmt_hours(minutes: float | None) -> str:
    if not minutes or minutes <= 0:
        return "--"
    return f"{minutes / 60:.1f}"


# ---------------------------------------------------------------------------
# 网络
# ---------------------------------------------------------------------------

def _default_route_ip() -> str | None:
    """通过 UDP connect 探测默认路由使用的本机地址（最有可能是 Wi-Fi/以太网）。"""
    for probe in ("8.8.8.8", "223.5.5.5", "114.114.114.114"):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.connect((probe, 80))
            ip = str(sock.getsockname()[0])
            if ip and not ip.startswith(("127.", "0.", "169.254.")):
                return ip
        except OSError:
            pass
        finally:
            sock.close()
    return None


def local_ipv4_addresses() -> list[str]:
    """枚举本机可用的局域网 IPv4 地址，默认路由地址排在最前。

    很多电脑装了 VMware / VirtualBox / Hyper-V，虚拟网卡也会出现在地址列表里
    （例如 192.168.119.1），手机无法访问这些地址，所以必须优先使用默认路由地址。
    """
    found: set[str] = set()

    def _add(ip: str) -> None:
        if not ip or ip.startswith(("127.", "169.254.", "0.")):
            return
        if ":" in ip:  # IPv6
            return
        found.add(ip)

    default_ip = _default_route_ip()
    if default_ip:
        _add(default_ip)

    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            _add(str(info[4][0]))
    except OSError:
        pass

    for probe in ("8.8.8.8", "223.5.5.5"):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.connect((probe, 80))
            _add(str(sock.getsockname()[0]))
        except OSError:
            pass
        finally:
            sock.close()

    def _rank(ip: str) -> tuple[int, int, str]:
        if default_ip and ip == default_ip:
            return (0, 0, ip)
        if ip.startswith("192.168."):
            return (1, 0, ip)
        if ip.startswith("10."):
            return (2, 0, ip)
        if ip.startswith("172."):
            return (3, 0, ip)
        return (4, 0, ip)

    return sorted(found, key=_rank)


def primary_lan_ip() -> str:
    addresses = local_ipv4_addresses()
    return addresses[0] if addresses else "127.0.0.1"


def app_base_url(port: int, ip: str | None = None) -> str:
    return f"http://{ip or primary_lan_ip()}:{port}"


def display_activity(activity_type: str) -> str:
    return {
        "running": "跑步",
        "walking": "步行",
        "cycling": "骑行",
        "hiking": "徒步",
        "swimming": "游泳",
        "strength": "力量训练",
        "yoga": "瑜伽",
        "pilates": "普拉提",
        "elliptical": "椭圆机",
        "rowing": "划船",
        "hiit": "高强度间歇",
        "core_training": "核心训练",
        "dance": "舞蹈",
        "tennis": "网球",
        "basketball": "篮球",
        "soccer": "足球",
        "badminton": "羽毛球",
        "table_tennis": "乒乓球",
        "skiing": "滑雪",
        "skating": "滑冰",
        "jump_rope": "跳绳",
        "stair_climbing": "爬楼",
        "mixed_cardio": "混合有氧",
        "cross_training": "交叉训练",
        "flexibility": "柔韧训练",
        "golf": "高尔夫",
        "snow_sports": "雪上运动",
        "snowboarding": "单板滑雪",
        "surfing": "冲浪",
        "paddle_sports": "桨板",
        "climbing": "攀岩",
        "equestrian": "马术",
        "fishing": "钓鱼",
        "hunting": "打猎",
        "recovery": "恢复",
        "play": "玩耍",
        "pickleball": "匹克球",
        "triathlon": "铁人三项",
        "diving": "潜水",
        "cooldown": "放松",
        "volleyball": "排球",
        "kickboxing": "踢拳",
        "martial_arts": "武术",
        "social_dance": "社交舞",
        "tai_chi": "太极",
        "wheelchair_walk": "轮椅步行",
        "wheelchair_run": "轮椅跑步",
        "disc_sports": "飞盘",
        "fitness_gaming": "体感游戏",
        "barre": "芭蕾塑形",
        "bowling": "保龄球",
        "boxing": "拳击",
        "baseball": "棒球",
        "cricket": "板球",
        "curling": "冰壶",
        "fencing": "击剑",
        "gymnastics": "体操",
        "handball": "手球",
        "hockey": "冰球",
        "lacrosse": "长曲棍球",
        "racquetball": "壁球",
        "rugby": "橄榄球",
        "sailing": "帆船",
        "softball": "垒球",
        "squash": "壁球",
        "track_and_field": "田径",
        "water_fitness": "水上健身",
        "water_polo": "水球",
        "water_sports": "水上运动",
        "wrestling": "摔跤",
        "hand_cycling": "手摇车",
        "other": "其他运动",
    }.get(activity_type, activity_type.replace("_", " ").title() if activity_type else "运动")


def activity_emoji(activity_type: str) -> str:
    return {
        "running": "🏃",
        "walking": "🚶",
        "cycling": "🚴",
        "hiking": "🥾",
        "swimming": "🏊",
        "strength": "🏋️",
        "yoga": "🧘",
        "pilates": "🤸",
        "elliptical": "🔄",
        "rowing": "🚣",
        "hiit": "⚡",
        "core_training": "🎯",
        "dance": "💃",
        "tennis": "🎾",
        "basketball": "🏀",
        "soccer": "⚽",
        "badminton": "🏸",
        "table_tennis": "🏓",
        "skiing": "⛷️",
        "skating": "⛸️",
        "jump_rope": "🪢",
        "stair_climbing": "🪜",
        "mixed_cardio": "❤️‍🔥",
    }.get(activity_type, "🏅")


def chunked(items: Iterable[Any], size: int) -> Iterable[list[Any]]:
    bucket: list[Any] = []
    for item in items:
        bucket.append(item)
        if len(bucket) >= size:
            yield bucket
            bucket = []
    if bucket:
        yield bucket
