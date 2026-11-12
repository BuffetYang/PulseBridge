"""生成一份演示数据，并离屏渲染各页面截图。

用法：uv run python scripts/seed_demo.py
输出：docs/screenshots/*.png
"""

from __future__ import annotations

import math
import os
import random
import shutil
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pulsebridge.bus import IngestBus  # noqa: E402
from pulsebridge.config import Config  # noqa: E402
from pulsebridge.db import Database  # noqa: E402
from pulsebridge.server import ServerController  # noqa: E402
from pulsebridge.ui.main_window import MainWindow  # noqa: E402
from pulsebridge.ui.theme import apply_theme  # noqa: E402
from pulsebridge.util import start_of_local_day  # noqa: E402


def _sample(uuid: str, type_: str, start: int, end: int, value, source: str = "Apple Watch", unit: str | None = None, value_text: str | None = None) -> dict:
    return {
        "uuid": uuid,
        "type": type_,
        "start_ts": int(start),
        "end_ts": int(end),
        "value": value,
        "value_text": value_text,
        "unit": unit,
        "source": source,
        "device": "iPhone",
        "metadata": None,
    }


def seed(db: Database) -> None:
    rng = random.Random(20261112)
    now = int(time.time())
    today = start_of_local_day()
    samples: list[dict] = []

    # 24 小时心率（每 10 分钟）
    ts = now - 24 * 3600
    while ts <= now:
        from datetime import datetime

        hour = datetime.fromtimestamp(ts).hour
        base = 58 + (6 if 6 <= hour < 9 else 0) + (14 if 17 <= hour < 20 else 0)
        if hour < 6:
            base -= 4
        value = base + math.sin((now - ts) / 5400) * 5 + rng.uniform(-3.5, 5.5)
        samples.append(_sample(f"demo-hr-{ts}", "heart_rate", ts, ts + 60, round(value, 1), unit="count/min"))
        ts += 600

    for day in range(30):
        day_start = today - day * 86400
        resting_ts = day_start + 7 * 3600
        if resting_ts <= now:
            samples.append(
                _sample(
                    f"demo-resting-{day}",
                    "resting_heart_rate",
                    resting_ts,
                    resting_ts + 60,
                    round(rng.uniform(55, 61), 1),
                    unit="count/min",
                )
            )
            samples.append(
                _sample(
                    f"demo-hrv-{day}",
                    "hrv",
                    resting_ts + 300,
                    resting_ts + 360,
                    round(rng.uniform(38, 58), 1),
                    unit="ms",
                )
            )

        for hour in range(24):
            start = day_start + hour * 3600
            if start > now:
                continue
            if 7 <= hour <= 22:
                steps = rng.randint(180, 780)
                energy = rng.randint(12, 48)
            elif hour in (6, 23):
                steps = rng.randint(30, 160)
                energy = rng.randint(2, 12)
            else:
                continue
            samples.append(_sample(f"demo-steps-{day}-{hour}", "steps", start, start + 3600, steps, unit="count"))
            samples.append(_sample(f"demo-energy-{day}-{hour}", "active_energy", start, start + 3600, energy, unit="kcal"))

    # 最近 14 晚睡眠（醒来日记账）
    stage_plan = [
        ("in_bed", 0, 450),
        ("core", 0, 180),
        ("deep", 180, 300),
        ("core", 300, 360),
        ("rem", 360, 430),
        ("awake", 430, 450),
    ]
    for night in range(14):
        night_start = today - night * 86400 - 30 * 60
        for index, (stage, offset_min, end_min) in enumerate(stage_plan):
            samples.append(
                _sample(
                    f"demo-sleep-{night}-{index}",
                    "sleep_analysis",
                    night_start + offset_min * 60,
                    night_start + end_min * 60,
                    None,
                    value_text=stage,
                )
            )

    db.insert_samples(samples)

    workouts = [
        ("demo-w1", "running", today - 86400 + 18 * 3600, 30 * 60, 5020, 320, 152, 171),
        ("demo-w2", "cycling", today - 3 * 86400 + 7 * 3600 + 1800, 45 * 60, 15200, 410, 136, 158),
        ("demo-w3", "strength", today - 5 * 86400 + 19 * 3600, 40 * 60, None, 230, 118, 142),
        ("demo-w4", "walking", today - 8 * 86400 + 12 * 3600, 35 * 60, 2400, 120, 101, 124),
        ("demo-w5", "swimming", today - 11 * 86400 + 9 * 3600, 30 * 60, 1200, 280, 146, 160),
    ]
    db.insert_workouts(
        [
            {
                "uuid": uuid,
                "activity_type": activity,
                "start_ts": start,
                "end_ts": start + duration,
                "duration_s": duration,
                "distance_m": distance,
                "energy_kcal": energy,
                "avg_hr": avg_hr,
                "max_hr": max_hr,
                "source": "Apple Watch",
                "metadata": None,
            }
            for uuid, activity, start, duration, distance, energy, avg_hr, max_hr in workouts
        ]
    )

    for index in range(8):
        db.record_ingest(
            remote="192.168.1.23",
            device="iPhone",
            samples_new=40 + index * 7,
            samples_dupe=3,
            workouts_new=0 if index % 3 else 1,
            workouts_dupe=0,
            status="ok",
            received_at=now - index * 3600 - 240,
        )


def main() -> int:
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QApplication

    out_dir = ROOT / "docs" / "screenshots"
    out_dir.mkdir(parents=True, exist_ok=True)
    data_dir = Path(tempfile.gettempdir()) / "pulsebridge-demo"
    if data_dir.exists():
        shutil.rmtree(data_dir, ignore_errors=True)
    data_dir.mkdir(parents=True, exist_ok=True)

    db = Database(data_dir / "pulsebridge.db")
    seed(db)

    config = Config(data_dir / "config.json")
    config.set("port", 8765)

    app = QApplication([])
    app.setApplicationName("PulseBridge")
    app.setFont(QFont("Microsoft YaHei UI", 10))
    apply_theme(app)

    controller = ServerController(config, db)
    controller.start()
    window = MainWindow(config, db, controller, IngestBus())
    window.resize(1360, 880)
    window.show()
    app.processEvents()

    names = ["dashboard", "trends", "workouts", "sync", "ai", "settings"]
    for index, name in enumerate(names):
        window.navigate(index)
        for _ in range(6):
            app.processEvents()
        path = out_dir / f"{name}.png"
        window.grab().save(str(path))
        print(f"已生成 {path}")

    window._quitting = True
    window.close()
    controller.stop()
    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
