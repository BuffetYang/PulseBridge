"""桌面悬浮球：悬停显示今日数据，可选、可拖动。

只在用户于设置中开启后创建显示；数据全部来自本地 SQLite，不联网。
"""

from __future__ import annotations

import math
import random
import time
from datetime import datetime

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPolygonF, QRadialGradient
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .. import analytics
from ..config import Config
from ..db import Database
from ..util import fmt_int, humanize_ago
from .theme import COLORS

STEP_GOAL = 10000

_TIPS = {
    "training": [
        "训练后记得拉伸，给身体留一点恢复时间。",
        "今天已经练过了，晚上早点睡。",
        "补水比再练一组更重要。",
    ],
    "rest": [
        "今天适合轻松恢复，散散步就好。",
        "睡眠优先，训练可以往后放一放。",
        "慢一点也没关系，恢复也是训练的一部分。",
    ],
    "active": [
        "动得不错，记得补水。",
        "保持这个节奏，晚上会睡得更好。",
        "再走一小段，今天的圆环就更好看了。",
    ],
    "calm": [
        "久坐一小时，起来走两步。",
        "今天喝水了吗？",
        "睡前把手机放远一点。",
        "步数不是全部，睡眠也很重要。",
    ],
}


def build_floating_snapshot(db: Database) -> dict:
    """悬浮卡片使用的聚合数据（不包含原始样本）。"""
    stats = db.stats()
    steps = float(analytics.today_cumulative(db, "steps") or 0)
    percent = min(100, int(steps / STEP_GOAL * 100)) if STEP_GOAL else 0

    night = analytics.last_night(db)
    sleep_hours = None
    deep_min = None
    if night and float(night.get("asleep_min") or 0) > 0:
        sleep_hours = float(night["asleep_min"]) / 60.0
        deep_min = float(night.get("deep_min") or 0)

    rings = analytics.activity_rings(db)
    resting_series = analytics.resting_heart_rate_series(db, 30)
    resting_value = None
    resting_estimated = False
    for point in reversed(resting_series):
        if point.get("value") is not None:
            resting_value = float(point["value"])
            resting_estimated = bool(point.get("estimated"))
            break
    values = [
        float(point["value"])
        for point in resting_series
        if point.get("value") is not None
    ]
    baseline = None
    if len(values) >= 2:
        baseline = sum(values[-8:-1]) / len(values[-8:-1])

    distance = float(analytics.today_cumulative(db, "distance") or 0)
    if distance > 200:  # 某些来源以米存储
        distance /= 1000.0
    if distance <= 0 and steps > 0:
        distance = steps * 0.0007
    flights = float(analytics.today_cumulative(db, "flights_climbed") or 0)
    laps = distance / 0.4 if distance > 0 else 0.0

    today = datetime.now().strftime("%Y-%m-%d")
    streak = 0
    for point in reversed(analytics.daily_series(db, "steps", 30)):
        value = float(point.get("value") or 0)
        if point.get("date") == today and value < STEP_GOAL:
            continue
        if value >= STEP_GOAL:
            streak += 1
        else:
            break

    workouts = analytics.today_workouts(db)
    if workouts:
        mood, mood_label, mood_hint = "training", "训练日", "今天已有训练记录"
    elif sleep_hours is not None and sleep_hours < 6.5:
        mood, mood_label, mood_hint = "rest", "恢复日", "睡眠偏短，适合轻松活动"
    elif (
        resting_value is not None
        and baseline is not None
        and resting_value > baseline * 1.05
    ):
        mood, mood_label, mood_hint = "rest", "恢复日", "静息心率高于近期基线"
    elif steps >= 8000 or (
        rings.get("move_goal") and rings.get("move", 0) >= rings["move_goal"] * 0.8
    ):
        mood, mood_label, mood_hint = "active", "活跃", "今天动得不错"
    else:
        mood, mood_label, mood_hint = "calm", "平稳", "保持当前节奏"

    parts: list[str] = []
    if laps >= 1:
        parts.append(f"≈ 绕操场 {laps:.0f} 圈")
    if flights >= 1:
        parts.append(f"≈ 爬 {flights:.0f} 层楼")
    remaining = max(0.0, STEP_GOAL - steps)
    if streak >= 2:
        parts.append(f"连续达标 {streak} 天")
    elif steps >= STEP_GOAL:
        parts.append("今日目标已达成")
    elif remaining > 0:
        parts.append(f"还差 {remaining:,.0f} 步")
    playful = " · ".join(parts) if parts else "今天动起来了吗？"

    return {
        "steps": steps,
        "step_goal": STEP_GOAL,
        "step_percent": percent,
        "sleep_hours": sleep_hours,
        "deep_min": deep_min,
        "resting_hr": resting_value,
        "resting_estimated": resting_estimated,
        "rings": rings,
        "distance_km": distance,
        "flights": flights,
        "laps": laps,
        "streak": streak,
        "remaining_steps": remaining,
        "mood": mood,
        "mood_label": mood_label,
        "mood_hint": mood_hint,
        "playful": playful,
        "last_sync_ts": stats.get("last_sync_ts"),
    }


class MoodFace(QWidget):
    """自绘的小表情：会眨眼、轻微上下浮动。"""

    _COLORS = {
        "calm": COLORS["purple"],
        "active": COLORS["accent"],
        "training": COLORS["orange"],
        "rest": COLORS["blue"],
    }

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(62, 62)
        self._mood = "calm"
        self._phase = 0.0
        self._active = True
        self._timer = QTimer(self)
        self._timer.setInterval(110)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def set_mood(self, mood: str) -> None:
        if mood != self._mood:
            self._mood = mood
            self.update()

    def set_active(self, active: bool) -> None:
        self._active = bool(active)
        if self._active and not self._timer.isActive():
            self._timer.start()
        elif not self._active:
            self._timer.stop()

    def _tick(self) -> None:
        self._phase += 0.12
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        base = QColor(self._COLORS.get(self._mood, COLORS["purple"]))
        center = QPointF(31.0, 31.0)
        bob = math.sin(self._phase * 1.6) * 1.3

        pulse = 0.5 + 0.5 * math.sin(self._phase)
        ring = QColor(base)
        ring.setAlpha(int(28 + 34 * pulse))
        painter.setPen(QPen(ring, 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(center, 27.0 + pulse * 2.0, 27.0 + pulse * 2.0)

        gradient = QRadialGradient(QPointF(23.0, 21.0), 34.0)
        gradient.setColorAt(0.0, base.lighter(135))
        gradient.setColorAt(1.0, base.darker(165))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(gradient)
        painter.drawEllipse(center + QPointF(0, bob), 22.0, 22.0)

        eye_color = QColor("#0A0E14")
        blink = (self._phase % 4.6) < 0.18
        eye_y = center.y() + bob - 5
        eye_pen = QPen(eye_color, 2.0)
        eye_pen.setCapStyle(Qt.PenCapStyle.RoundCap)

        if self._mood == "rest" or blink:
            painter.setPen(eye_pen)
            painter.drawArc(QRectF(17.0, eye_y - 3.0, 8.0, 6.0), 0, -180 * 16)
            painter.drawArc(QRectF(37.0, eye_y - 3.0, 8.0, 6.0), 0, -180 * 16)
        else:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(eye_color)
            painter.drawEllipse(QPointF(22.0, eye_y), 2.2, 3.0)
            painter.drawEllipse(QPointF(40.0, eye_y), 2.2, 3.0)

        mouth_pen = QPen(eye_color, 2.0)
        mouth_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(mouth_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        if self._mood == "rest":
            painter.drawEllipse(QPointF(31.0, center.y() + bob + 8.0), 2.4, 2.4)
        elif self._mood == "training":
            painter.drawArc(QRectF(24.0, center.y() + bob + 3.0, 14.0, 9.0), 200 * 16, 140 * 16)
        elif self._mood == "active":
            painter.drawArc(QRectF(24.0, center.y() + bob + 3.0, 14.0, 9.0), 200 * 16, 140 * 16)
        else:
            painter.drawArc(QRectF(25.0, center.y() + bob + 4.0, 12.0, 7.0), 200 * 16, 140 * 16)

        if self._mood == "rest":
            painter.setPen(base.lighter(160))
            painter.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
            painter.drawText(QRectF(44.0, 4.0, 16.0, 14.0), Qt.AlignmentFlag.AlignCenter, "Z")
        elif self._mood == "training":
            painter.setPen(base.lighter(150))
            painter.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
            painter.drawText(QRectF(44.0, 4.0, 16.0, 14.0), Qt.AlignmentFlag.AlignCenter, "!")


class MiniRings(QWidget):
    """三个紧凑的活动圆环。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._data: list[tuple[str, float, float, str, str, bool]] = []
        self.setMinimumHeight(76)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )

    def set_data(
        self, rings: list[tuple[str, float, float, str, str, bool]]
    ) -> None:
        self._data = rings
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        if not self._data:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        count = len(self._data)
        cell = self.width() / count
        diameter = 38.0
        for index, (label, value, goal, unit, color, estimated) in enumerate(
            self._data
        ):
            center_x = cell * (index + 0.5)
            ring = QRectF(center_x - diameter / 2, 2.0, diameter, diameter)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(
                QPen(
                    QColor("#223140"),
                    6,
                    Qt.PenStyle.SolidLine,
                    Qt.PenCapStyle.RoundCap,
                )
            )
            painter.drawArc(ring, 90 * 16, -360 * 16)
            progress = min(1.0, value / goal) if goal > 0 else 0.0
            if progress > 0:
                painter.setPen(
                    QPen(
                        QColor(color),
                        6,
                        Qt.PenStyle.SolidLine,
                        Qt.PenCapStyle.RoundCap,
                    )
                )
                painter.drawArc(ring, 90 * 16, int(-360 * 16 * progress))
            painter.setPen(QPen(QColor(COLORS["text"])))
            painter.setFont(QFont(self.font().family(), 8, QFont.Weight.Bold))
            percent = f"{progress * 100:.0f}%"
            if estimated:
                percent = "≈" + percent
            painter.drawText(ring, Qt.AlignmentFlag.AlignCenter, percent)
            painter.setPen(QPen(QColor(COLORS["muted"])))
            painter.setFont(QFont(self.font().family(), 8))
            painter.drawText(
                QRectF(center_x - cell / 2, ring.bottom() + 4, cell, 12),
                Qt.AlignmentFlag.AlignCenter,
                label,
            )
            painter.setPen(QPen(QColor(COLORS["text"])))
            painter.setFont(QFont(self.font().family(), 8, QFont.Weight.Bold))
            prefix = "≈" if estimated else ""
            painter.drawText(
                QRectF(center_x - cell / 2, ring.bottom() + 16, cell, 12),
                Qt.AlignmentFlag.AlignCenter,
                f"{prefix}{value:.0f}/{goal:.0f} {unit}".strip(),
            )


def _stat_block(title: str) -> tuple[QWidget, QLabel, QLabel]:
    box = QWidget()
    layout = QVBoxLayout(box)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)
    label = QLabel(title)
    label.setObjectName("floatLabel")
    value = QLabel("--")
    value.setObjectName("floatStat")
    sub = QLabel("")
    sub.setObjectName("floatSub")
    layout.addWidget(label)
    layout.addWidget(value)
    layout.addWidget(sub)
    return box, value, sub


class FloatingCard(QFrame):
    open_dashboard = Signal()
    open_ai = Signal()
    hover_changed = Signal(bool)

    def __init__(self, db: Database, parent: QWidget | None = None) -> None:
        super().__init__(None)
        self.db = db
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFixedWidth(360)
        self.setObjectName("floatingCard")
        self.setStyleSheet(
            """
            QFrame#floatingCard {
                background: transparent;
                border: none;
            }
            QLabel#floatTitle {
                color: #EAF0F7; font-size: 14px; font-weight: 700;
            }
            QLabel#floatMood {
                color: #3DDC97; font-size: 12px; font-weight: 700;
            }
            QLabel#floatLabel {
                color: #8B9CB3; font-size: 10px;
            }
            QLabel#floatStat {
                color: #EAF0F7; font-size: 17px; font-weight: 700;
            }
            QLabel#floatSub {
                color: #61748C; font-size: 10px;
            }
            QLabel#floatTip {
                color: #B18CFF; font-size: 11px;
            }
            QLabel#floatPlayful {
                color: #EAF0F7; font-size: 11px; font-weight: 600;
            }
            QLabel#floatSync {
                color: #61748C; font-size: 10px;
            }
            QProgressBar#floatBar {
                background: #0E151E; border: none; border-radius: 3px;
                max-height: 6px; min-height: 6px;
            }
            QProgressBar#floatBar::chunk {
                background: #3DDC97; border-radius: 3px;
            }
            """
        )

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.setInterval(360)
        self._hide_timer.timeout.connect(self.hide)
        self._last_mood = ""
        self._tip = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 12)
        layout.setSpacing(7)

        header = QHBoxLayout()
        header.setSpacing(10)
        self.face = MoodFace()
        header.addWidget(self.face, 0, Qt.AlignmentFlag.AlignTop)
        header_text = QVBoxLayout()
        header_text.setSpacing(1)
        title = QLabel("PulseBridge")
        title.setObjectName("floatTitle")
        header_text.addWidget(title)
        self.mood_label = QLabel("平稳")
        self.mood_label.setObjectName("floatMood")
        header_text.addWidget(self.mood_label)
        self.mood_hint = QLabel("")
        self.mood_hint.setObjectName("floatSub")
        self.mood_hint.setWordWrap(True)
        header_text.addWidget(self.mood_hint)
        header.addLayout(header_text, 1)
        open_button = QPushButton("打开 ↗")
        open_button.setObjectName("linkButton")
        open_button.setCursor(Qt.CursorShape.PointingHandCursor)
        open_button.clicked.connect(self.open_dashboard.emit)
        header.addWidget(open_button, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(header)

        steps_row = QHBoxLayout()
        steps_row.setSpacing(6)
        self.steps_value = QLabel("--")
        self.steps_value.setObjectName("floatStat")
        steps_row.addWidget(self.steps_value, 0, Qt.AlignmentFlag.AlignBaseline)
        self.steps_unit = QLabel("/ 10,000 步")
        self.steps_unit.setObjectName("floatLabel")
        steps_row.addWidget(self.steps_unit, 0, Qt.AlignmentFlag.AlignBaseline)
        steps_row.addStretch(1)
        self.steps_percent = QLabel("0%")
        self.steps_percent.setObjectName("floatMood")
        steps_row.addWidget(self.steps_percent, 0, Qt.AlignmentFlag.AlignBaseline)
        layout.addLayout(steps_row)

        self.steps_bar = QProgressBar()
        self.steps_bar.setObjectName("floatBar")
        self.steps_bar.setRange(0, 100)
        self.steps_bar.setTextVisible(False)
        self.steps_bar.setFixedHeight(6)
        layout.addWidget(self.steps_bar)

        stats = QHBoxLayout()
        stats.setSpacing(16)
        sleep_box, self.sleep_value, self.sleep_sub = _stat_block("最近睡眠")
        hr_box, self.hr_value, self.hr_sub = _stat_block("静息心率")
        stats.addWidget(sleep_box, 1)
        stats.addWidget(hr_box, 1)
        layout.addLayout(stats)

        self.rings = MiniRings()
        layout.addWidget(self.rings)

        self.playful_label = QLabel("")
        self.playful_label.setObjectName("floatPlayful")
        self.playful_label.setWordWrap(True)
        layout.addWidget(self.playful_label)

        self.tip_label = QLabel("")
        self.tip_label.setObjectName("floatTip")
        self.tip_label.setWordWrap(True)
        layout.addWidget(self.tip_label)

        footer = QHBoxLayout()
        footer.setSpacing(8)
        self.sync_label = QLabel("")
        self.sync_label.setObjectName("floatSync")
        footer.addWidget(self.sync_label, 1)
        ai_button = QPushButton("AI 周报")
        ai_button.setObjectName("linkButton")
        ai_button.setCursor(Qt.CursorShape.PointingHandCursor)
        ai_button.clicked.connect(self.open_ai.emit)
        footer.addWidget(ai_button)
        layout.addLayout(footer)
        self.face.set_active(False)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setBrush(QColor("#121923"))
        painter.setPen(QPen(QColor("#243244"), 1))
        painter.drawRoundedRect(rect, 18.0, 18.0)

    def refresh_data(self) -> None:
        snapshot = build_floating_snapshot(self.db)
        steps = snapshot["steps"]
        self.steps_value.setText(f"{fmt_int(steps)}")
        self.steps_unit.setText(f"/ {fmt_int(snapshot['step_goal'])} 步")
        self.steps_percent.setText(f"{snapshot['step_percent']}%")
        self.steps_bar.setValue(int(snapshot["step_percent"]))

        sleep_hours = snapshot["sleep_hours"]
        if sleep_hours is None:
            self.sleep_value.setText("--")
            self.sleep_sub.setText("没有睡眠记录")
        else:
            self.sleep_value.setText(f"{sleep_hours:.1f} h")
            self.sleep_sub.setText(f"深睡 {int(snapshot['deep_min'] or 0)} 分")

        resting = snapshot["resting_hr"]
        if resting is None:
            self.hr_value.setText("--")
            self.hr_sub.setText("暂无数据")
        elif snapshot["resting_estimated"]:
            self.hr_value.setText(f"≈ {resting:.0f} bpm")
            self.hr_sub.setText("由睡眠心率估算")
        else:
            self.hr_value.setText(f"{resting:.0f} bpm")
            self.hr_sub.setText("最近一次")

        rings = snapshot["rings"]
        exercise_estimated = bool(rings.get("exercise_estimated"))
        self.rings.set_data(
            [
                (
                    "活动",
                    float(rings.get("move") or 0),
                    float(rings.get("move_goal") or 500),
                    "kcal",
                    COLORS["pink"],
                    False,
                ),
                (
                    "锻炼",
                    float(rings.get("exercise") or 0),
                    float(rings.get("exercise_goal") or 30),
                    "min",
                    COLORS["accent"],
                    exercise_estimated,
                ),
                (
                    "站立",
                    float(rings.get("stand") or 0),
                    float(rings.get("stand_goal") or 12),
                    "h",
                    COLORS["blue"],
                    False,
                ),
            ]
        )
        self.rings.setToolTip(
            "锻炼分钟数为估算：心率区间 / 步频 / 活动能量"
            if exercise_estimated
            else ""
        )

        mood = snapshot["mood"]
        self.face.set_mood(mood)
        self.mood_label.setText(snapshot["mood_label"])
        self.mood_hint.setText(snapshot["mood_hint"])
        self.playful_label.setText(snapshot["playful"])
        if mood != self._last_mood:
            self._last_mood = mood
            self._tip = random.choice(_TIPS.get(mood, _TIPS["calm"]))
        self.tip_label.setText(self._tip)

        last_sync = snapshot.get("last_sync_ts")
        self.sync_label.setText(
            f"最近同步 {humanize_ago(last_sync)}" if last_sync else "等待首次同步"
        )
        self.adjustSize()

    def show_near(self, anchor: QRect) -> None:
        self.adjustSize()
        size = self.sizeHint()
        screen = QApplication.screenAt(anchor.center()) or QApplication.primaryScreen()
        available = screen.availableGeometry()
        x = anchor.center().x() - size.width() // 2
        y = anchor.top() - size.height() - 10
        if y < available.top() + 6:
            y = anchor.bottom() + 10
        x = max(available.left() + 8, min(x, available.right() - size.width() - 8))
        y = max(available.top() + 8, min(y, available.bottom() - size.height() - 8))
        self.move(x, y)
        self._hide_timer.stop()
        self.show()
        self.raise_()
        self.face.set_active(True)

    def schedule_hide(self) -> None:
        self._hide_timer.start()

    def enterEvent(self, event) -> None:  # noqa: N802
        self._hide_timer.stop()
        self.hover_changed.emit(True)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self.hover_changed.emit(False)
        self.schedule_hide()
        super().leaveEvent(event)

    def hideEvent(self, event) -> None:  # noqa: N802
        self.face.set_active(False)
        super().hideEvent(event)


class FloatingBall(QWidget):
    hovered = Signal()
    left = Signal()
    clicked = Signal()
    dragged = Signal()
    moved = Signal()

    def __init__(self, config: Config, parent: QWidget | None = None) -> None:
        super().__init__(None)
        self.config = config
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFixedSize(64, 64)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("PulseBridge · 悬停查看今日数据 · 拖动移动")
        self._phase = 0.0
        self._status_ok = True
        self._drag_offset = None
        self._dragging = False
        self._press_pos = None
        self._timer = QTimer(self)
        self._timer.setInterval(90)
        self._timer.timeout.connect(self._tick)
        self.setGeometry(self._initial_position())

    def _initial_position(self) -> QRect:
        try:
            x = int(self.config.get("floating_x", -1))
            y = int(self.config.get("floating_y", -1))
        except (TypeError, ValueError):
            x = y = -1
        screen = None
        if x >= 0 and y >= 0:
            screen = QApplication.screenAt(QPoint(x, y))
        if screen is None:
            screen = QApplication.primaryScreen()
        available = screen.availableGeometry()
        if x < 0 or y < 0:
            x = available.right() - 96
            y = available.bottom() - 190
        x = max(available.left() + 4, min(x, available.right() - self.width() - 4))
        y = max(available.top() + 4, min(y, available.bottom() - self.height() - 4))
        return QRect(x, y, self.width(), self.height())

    def set_status(self, ok: bool) -> None:
        self._status_ok = bool(ok)
        self.update()

    def _tick(self) -> None:
        self._phase += 0.12
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        hover = self.underMouse()
        margin = 5.0 if hover else 7.0
        rect = QRectF(margin, margin, 64 - margin * 2, 64 - margin * 2)

        pulse = 0.5 + 0.5 * math.sin(self._phase)
        ring = QColor(COLORS["accent"])
        ring.setAlpha(int(30 + 40 * pulse))
        painter.setPen(QPen(ring, 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(rect.adjusted(-2, -2, 2, 2))

        gradient = QRadialGradient(rect.center() - QPointF(8, 10), 40)
        gradient.setColorAt(0, QColor("#1B2A3A"))
        gradient.setColorAt(1, QColor("#0C1219"))
        painter.setBrush(gradient)
        painter.setPen(QPen(QColor("#2A3A4D"), 1))
        painter.drawEllipse(rect)

        pen = QPen(QColor(COLORS["accent"]), 2.4)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        cx = rect.center().x()
        cy = rect.center().y()
        points = QPolygonF(
            [
                QPointF(cx - 15, cy + 1),
                QPointF(cx - 8, cy + 1),
                QPointF(cx - 4, cy - 7),
                QPointF(cx + 1, cy + 8),
                QPointF(cx + 5, cy - 2),
                QPointF(cx + 15, cy - 2),
            ]
        )
        painter.drawPolyline(points)

        dot = QColor(COLORS["accent"] if self._status_ok else COLORS["orange"])
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(dot)
        painter.drawEllipse(QPointF(rect.right() - 5, rect.bottom() - 5), 3.2, 3.2)

    def enterEvent(self, event) -> None:  # noqa: N802
        self.update()
        self.hovered.emit()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self.update()
        self.left.emit()
        super().leaveEvent(event)

    def showEvent(self, event) -> None:  # noqa: N802
        if not self._timer.isActive():
            self._timer.start()
        super().showEvent(event)

    def hideEvent(self, event) -> None:  # noqa: N802
        self._timer.stop()
        super().hideEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self._press_pos = event.globalPosition().toPoint()
            self._dragging = False
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._drag_offset is None:
            super().mouseMoveEvent(event)
            return
        if not self._dragging and self._press_pos is not None:
            if (event.globalPosition().toPoint() - self._press_pos).manhattanLength() > 4:
                self._dragging = True
                self.dragged.emit()
        if self._dragging:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            self.moved.emit()
        event.accept()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            if self._dragging:
                screen = QApplication.screenAt(event.globalPosition().toPoint())
                if screen is not None:
                    available = screen.availableGeometry()
                    x = max(available.left() + 4, min(self.x(), available.right() - self.width() - 4))
                    y = max(available.top() + 4, min(self.y(), available.bottom() - self.height() - 4))
                    self.move(x, y)
                    self.config.set("floating_x", x)
                    self.config.set("floating_y", y)
            else:
                self.clicked.emit()
            self._drag_offset = None
            self._press_pos = None
            self._dragging = False
            event.accept()
            return
        super().mouseReleaseEvent(event)


class FloatingWidget:
    """管理悬浮球和悬停卡片。"""

    def __init__(
        self,
        db: Database,
        config: Config,
        open_dashboard,
        open_ai,
        parent: QWidget | None = None,
    ) -> None:
        self.db = db
        self.config = config
        self.open_dashboard = open_dashboard
        self.open_ai = open_ai
        self.ball = FloatingBall(config)
        self.card = FloatingCard(db)
        self._enabled = False
        self._timer = QTimer()
        self._timer.setInterval(60000)
        self._timer.timeout.connect(self.refresh)

        self.ball.hovered.connect(self._show_card)
        self.ball.left.connect(self.card.schedule_hide)
        self.ball.clicked.connect(self._open_dashboard)
        self.ball.dragged.connect(self.card.hide)
        self.ball.moved.connect(self._move_card)
        self.card.open_dashboard.connect(self._open_dashboard)
        self.card.open_ai.connect(self._open_ai)
        self.card.hover_changed.connect(self._on_card_hover)

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = bool(enabled)
        if self._enabled:
            self.refresh()
            self.ball.show()
            self.ball.raise_()
            self._timer.start()
        else:
            self._timer.stop()
            self.card.hide()
            self.ball.hide()

    def refresh(self) -> None:
        if not self._enabled:
            return
        self.card.refresh_data()
        last_sync = self.db.stats().get("last_sync_ts") or 0
        self.ball.set_status(
            not last_sync or time.time() - float(last_sync) < 7200
        )

    def _show_card(self) -> None:
        if not self._enabled:
            return
        self.card.refresh_data()
        self.card.show_near(self.ball.frameGeometry())

    def _move_card(self) -> None:
        if self.card.isVisible():
            self.card.show_near(self.ball.frameGeometry())

    def _on_card_hover(self, inside: bool) -> None:
        if inside:
            self.card._hide_timer.stop()
        else:
            self.card.schedule_hide()

    def _open_dashboard(self) -> None:
        self.card.hide()
        self.open_dashboard()

    def _open_ai(self) -> None:
        self.card.hide()
        self.open_ai()

    def shutdown(self) -> None:
        self._timer.stop()
        self.card.hide()
        self.ball.hide()
        self.card.close()
        self.ball.close()
