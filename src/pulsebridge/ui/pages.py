"""应用各个页面。"""

from __future__ import annotations

import json
import threading
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import (
    QDateTime,
    QEvent,
    QObject,
    QSize,
    Qt,
    QTime,
    QTimer,
    QUrl,
    Signal,
)
from PySide6.QtGui import QDesktopServices, QIntValidator, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QTextBrowser,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from .. import analytics, startup
from ..config import APP_NAME, APP_VERSION, Config
from ..db import Database
from ..firewall import add_firewall_rule_elevated
from ..guide import build_guide_html, build_puls_guide_html, shortcut_payload_template
from ..health_export import import_health_export
from ..reminders import due_occurrence, next_for_config
from ..server import ServerController
from ..util import (
    activity_emoji,
    app_base_url,
    display_activity,
    fmt_distance,
    fmt_duration,
    fmt_float,
    fmt_int,
    humanize_ago,
    local_date_label,
    local_time_label,
    local_ipv4_addresses,
    primary_lan_ip,
    weekday_label,
)
from .charts import BarChart, LineChart, StageBar
from .theme import COLORS
from .widgets import (
    Card,
    CopyRow,
    Divider,
    EmptyState,
    MetricCard,
    StatusPill,
    ToggleSwitch,
    card_header,
)

RefreshAll = Callable[[], None]

SLEEP_COLORS = {
    "deep": COLORS["blue"],
    "core": COLORS["purple"],
    "rem": COLORS["cyan"],
    "light": "#61748C",
    "awake": COLORS["orange"],
}


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------

def _clear_layout(layout: QVBoxLayout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.deleteLater()
        child = item.layout()
        if child is not None:
            _clear_layout(child)  # type: ignore[arg-type]
            child.deleteLater()


def _make_scroll(parent_layout: QVBoxLayout) -> QVBoxLayout:
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    content = QWidget()
    content.setObjectName("pageContent")
    content.setMinimumWidth(0)
    layout = QVBoxLayout(content)
    layout.setContentsMargins(30, 26, 30, 30)
    layout.setSpacing(18)
    scroll.setWidget(content)
    parent_layout.addWidget(scroll)
    return layout


def _header(title: str, subtitle: str = "", right: QWidget | None = None) -> QHBoxLayout:
    row = QHBoxLayout()
    row.setSpacing(12)
    column = QVBoxLayout()
    column.setSpacing(3)
    title_label = QLabel(title)
    title_label.setObjectName("pageTitle")
    column.addWidget(title_label)
    if subtitle:
        sub = QLabel(subtitle)
        sub.setObjectName("pageSub")
        column.addWidget(sub)
    row.addLayout(column)
    row.addStretch(1)
    if right is not None:
        row.addWidget(right, 0, Qt.AlignmentFlag.AlignVCenter)
    return row


def _stat_tile(label: str, unit: str = "") -> tuple[QFrame, QLabel]:
    frame = QFrame()
    frame.setObjectName("softCard")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(16, 12, 16, 12)
    layout.setSpacing(4)
    title = QLabel(label)
    title.setObjectName("subtle")
    value = QLabel("--")
    value.setObjectName("statValue")
    layout.addWidget(title)
    layout.addWidget(value)
    return frame, value


class ChartCard(Card):
    def __init__(self, title: str, subtitle: str, chart: QWidget) -> None:
        super().__init__()
        self.chart = chart
        head = QHBoxLayout()
        head.setSpacing(8)
        column = QVBoxLayout()
        column.setSpacing(2)
        title_label = QLabel(title)
        title_label.setObjectName("cardTitle")
        self.subtitle = QLabel(subtitle)
        self.subtitle.setObjectName("cardSub")
        column.addWidget(title_label)
        column.addWidget(self.subtitle)
        head.addLayout(column)
        head.addStretch(1)
        self.body.addLayout(head)
        self.body.addWidget(chart, 1)

    def set_subtitle(self, text: str) -> None:
        self.subtitle.setText(text)

    def set_click_handler(self, callback, tooltip: str = "点击查看趋势") -> None:
        super().set_click_handler(callback, tooltip)
        if callback:
            self.chart.setCursor(Qt.CursorShape.PointingHandCursor)
            self.chart.installEventFilter(self)

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        if (
            watched is self.chart
            and self._on_click
            and event.type() == QEvent.Type.MouseButtonRelease
            and event.button() == Qt.MouseButton.LeftButton
        ):
            self._on_click()
            return True
        return super().eventFilter(watched, event)


class WorkoutRow(QFrame):
    def __init__(self, workout: dict[str, Any], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("row")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(12)

        accent = {
            "running": COLORS["orange"],
            "cycling": COLORS["blue"],
            "swimming": COLORS["cyan"],
            "strength": COLORS["purple"],
            "yoga": COLORS["accent"],
        }.get(str(workout.get("activity_type")), COLORS["muted"])
        icon = QLabel(activity_emoji(str(workout.get("activity_type"))))
        icon.setFixedSize(40, 40)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setStyleSheet(
            "background: rgba(255,255,255,0.04); border-radius: 12px; font-size: 19px;"
        )
        layout.addWidget(icon)

        info = QVBoxLayout()
        info.setSpacing(3)
        name = QLabel(display_activity(str(workout.get("activity_type"))))
        name.setStyleSheet("font-size: 13px; font-weight: 600;")
        when = QLabel(
            f"{local_date_label(_date_of(workout['start_ts']))} "
            f"{local_time_label(workout['start_ts'])}"
            + (f" · {workout['source']}" if workout.get("source") else "")
        )
        when.setObjectName("subtle")
        when.setWordWrap(True)
        when.setToolTip(when.text())
        info.addWidget(name)
        info.addWidget(when)
        layout.addLayout(info, 1)

        details: list[str] = []
        duration = workout.get("duration_s")
        if duration:
            details.append(fmt_duration(duration / 60.0, compact=True))
        if workout.get("distance_m"):
            details.append(fmt_distance(workout.get("distance_m")))
        if workout.get("energy_kcal"):
            details.append(f"{workout['energy_kcal']:.0f} kcal")
        if workout.get("avg_hr"):
            details.append(f"♥ {workout['avg_hr']:.0f}")
        detail_label = QLabel("  ·  ".join(details) if details else "")
        detail_label.setStyleSheet(f"color: {accent}; font-size: 12px;")
        detail_label.setToolTip(detail_label.text())
        detail_label.setWordWrap(True)
        detail_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        detail_label.setMaximumWidth(300)
        layout.addWidget(detail_label)
        self._on_click = None

    def set_click_handler(self, callback, tooltip: str = "查看运动记录") -> None:
        self._on_click = callback
        if callback:
            self.setToolTip(tooltip)
            self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if (
            self._on_click
            and event.button() == Qt.MouseButton.LeftButton
            and self.rect().contains(event.position().toPoint())
        ):
            self._on_click()
            event.accept()
            return
        super().mouseReleaseEvent(event)


def _date_of(ts: int) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# 仪表盘
# ---------------------------------------------------------------------------

class DashboardPage(QWidget):
    def __init__(
        self,
        db: Database,
        controller: ServerController,
        open_guide: Callable[[], None],
        open_workouts: Callable[[], None],
        open_trend: Callable[[str], None] | None = None,
        open_sync: Callable[[], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.db = db
        self.controller = controller
        self.open_guide = open_guide
        self.open_workouts = open_workouts
        self.open_trend = open_trend
        self.open_sync = open_sync

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        layout = _make_scroll(outer)

        self.status = StatusPill()
        self.status.set_state("warn", "等待首次同步")
        if self.open_sync:
            self.status.set_click_handler(self.open_sync)
        today = datetime.now()
        subtitle = f"{today.year}年{today.month}月{today.day}日 · {weekday_label(today.strftime('%Y-%m-%d'))}"
        layout.addLayout(_header("仪表盘", subtitle, self.status))

        metrics = QHBoxLayout()
        metrics.setSpacing(14)
        self.card_steps = MetricCard("👟", "今日步数", COLORS["accent"], "步")
        self.card_resting = MetricCard("❤️", "静息心率", COLORS["pink"], "bpm")
        self.card_sleep = MetricCard("🌙", "最近睡眠", COLORS["purple"], "小时")
        self.card_energy = MetricCard("🔥", "活动能量", COLORS["orange"], "kcal")
        for card in (self.card_steps, self.card_resting, self.card_sleep, self.card_energy):
            metrics.addWidget(card, 1)
        if self.open_trend:
            self.card_steps.set_click_handler(
                lambda: self.open_trend("steps"), "查看步数趋势"
            )
            self.card_resting.set_click_handler(
                lambda: self.open_trend("resting_heart_rate"), "查看静息心率趋势"
            )
            self.card_sleep.set_click_handler(
                lambda: self.open_trend("sleep"), "查看睡眠趋势"
            )
            self.card_energy.set_click_handler(
                lambda: self.open_trend("active_energy"), "查看活动能量趋势"
            )
        layout.addLayout(metrics)

        charts = QHBoxLayout()
        charts.setSpacing(14)
        self.hr_chart = LineChart(COLORS["pink"], "bpm")
        self.hr_chart.setMinimumHeight(210)
        self.hr_card = ChartCard("心率 · 最近 24 小时", "等待心率数据", self.hr_chart)
        charts.addWidget(self.hr_card, 3)

        self.steps_chart = BarChart(COLORS["accent"], "步")
        self.steps_chart.setMinimumHeight(210)
        self.steps_card = ChartCard("步数 · 近 7 天", "每日步数", self.steps_chart)
        charts.addWidget(self.steps_card, 2)
        layout.addLayout(charts)

        bottom = QHBoxLayout()
        bottom.setSpacing(14)

        workouts_card = Card()
        workouts_card.body.addLayout(
            card_header(
                "最近运动",
                "近 7 天",
                _link_button("查看全部", self.open_workouts),
            )
        )
        self.workout_list = QVBoxLayout()
        self.workout_list.setSpacing(8)
        workouts_card.body.addLayout(self.workout_list)
        workouts_card.body.addStretch(1)
        bottom.addWidget(workouts_card, 1)

        self.sleep_card = Card()
        self.sleep_card.body.addLayout(card_header("最近睡眠", "醒来后的首个同步"))
        self.sleep_value_row = QHBoxLayout()
        self.sleep_value_row.setSpacing(6)
        self.sleep_value = QLabel("--")
        self.sleep_value.setObjectName("bigValue")
        self.sleep_unit = QLabel("小时")
        self.sleep_unit.setObjectName("metricUnit")
        self.sleep_efficiency = QLabel("")
        self.sleep_efficiency.setObjectName("chip")
        self.sleep_value_row.addWidget(self.sleep_value)
        self.sleep_value_row.addWidget(self.sleep_unit, 0, Qt.AlignmentFlag.AlignBottom)
        self.sleep_value_row.addStretch(1)
        self.sleep_value_row.addWidget(self.sleep_efficiency)
        self.sleep_card.body.addLayout(self.sleep_value_row)

        self.stage_bar = StageBar()
        self.sleep_card.body.addWidget(self.stage_bar)
        self.sleep_legend = QLabel("")
        self.sleep_legend.setWordWrap(True)
        self.sleep_legend.setStyleSheet(f"color: {COLORS['muted']}; font-size: 12px;")
        self.sleep_card.body.addWidget(self.sleep_legend)
        self.sleep_meta = QLabel("")
        self.sleep_meta.setObjectName("subtle")
        self.sleep_meta.setWordWrap(True)
        self.sleep_card.body.addWidget(self.sleep_meta)
        self.sleep_card.body.addStretch(1)
        bottom.addWidget(self.sleep_card, 1)
        layout.addLayout(bottom)
        layout.addStretch(1)

        if self.open_trend:
            self.hr_card.set_click_handler(
                lambda: self.open_trend("heart_rate"), "查看心率趋势"
            )
            self.steps_card.set_click_handler(
                lambda: self.open_trend("steps"), "查看步数趋势"
            )
            self.sleep_card.set_click_handler(
                lambda: self.open_trend("sleep"), "查看睡眠趋势"
            )

        self.refresh()

    # ------------------------------------------------------------------
    def refresh(self) -> None:
        stats = self.db.stats()
        has_data = stats["samples"] > 0
        self._refresh_status(stats)

        # 步数
        steps = analytics.today_cumulative(self.db, "steps") if has_data else None
        step_series = analytics.daily_series(self.db, "steps", 7)
        if has_data and steps is not None:
            percent = min(100, int(steps / 10000 * 100))
            self.card_steps.set_value(
                fmt_int(steps),
                "步",
                f"目标 10,000 · {percent}%",
                [p["value"] for p in step_series],
            )
        else:
            self.card_steps.set_value("--", "步", "等待 iPhone 首次同步", [None])

        # 静息心率
        resting = analytics.latest_sample(self.db, "resting_heart_rate")
        resting_series = analytics.daily_series(self.db, "resting_heart_rate", 7)
        if resting and resting.get("value") is not None:
            self.card_resting.set_value(
                fmt_int(resting["value"]),
                "bpm",
                f"{humanize_ago(resting['start_ts'])} · {resting.get('source') or 'Apple Watch'}",
                [p["value"] for p in resting_series],
            )
        else:
            self.card_resting.set_value(
                "--", "bpm", "暂无静息心率数据", [p["value"] for p in resting_series]
            )

        # 睡眠
        night = analytics.last_night(self.db)
        sleep_series = [
            (p["value"] if p["value"] is not None else None)
            for p in analytics.daily_series(self.db, "sleep", 7)
        ]
        if night and night["asleep_min"] > 0:
            hours = night["asleep_min"] / 60.0
            self.card_sleep.set_value(
                f"{hours:.1f}",
                "小时",
                f"深睡 {night['deep_min']:.0f} 分 · REM {night['rem_min']:.0f} 分",
                sleep_series,
            )
        else:
            self.card_sleep.set_value("--", "小时", "等待睡眠数据", sleep_series)

        # 活动能量
        energy = analytics.today_cumulative(self.db, "active_energy") if has_data else None
        energy_series = analytics.daily_series(self.db, "active_energy", 7)
        if has_data and energy is not None:
            percent = min(100, int(energy / 500 * 100)) if energy else 0
            self.card_energy.set_value(
                fmt_int(energy),
                "kcal",
                f"目标 500 · {percent}%",
                [p["value"] for p in energy_series],
            )
        else:
            self.card_energy.set_value("--", "kcal", "等待 iPhone 首次同步", [None])

        # 心率图
        points = analytics.heart_rate_points(self.db, 24)
        self.hr_chart.set_data(points, "bpm")
        if points:
            values = [v for _, v in points]
            self.hr_card.set_subtitle(
                f"平均 {sum(values) / len(values):.0f} bpm · 最高 {max(values):.0f} bpm"
            )
        else:
            self.hr_card.set_subtitle("最近 24 小时暂无心率数据")
            self.hr_chart.set_empty_text("在 iPhone 上运行同步快捷指令后显示")

        # 步数柱状图
        labels = []
        series = analytics.daily_series(self.db, "steps", 7)
        for index, point in enumerate(series):
            labels.append("今天" if index == len(series) - 1 else weekday_label(point["date"])[1:])
        self.steps_chart.set_data(labels, [p["value"] for p in series], "步")
        self.steps_chart.set_empty_text("近 7 天暂无步数")

        # 最近运动
        _clear_layout(self.workout_list)
        workouts = analytics.recent_workouts(self.db, days=7, limit=3)
        if workouts:
            for workout in workouts:
                row = WorkoutRow(workout)
                if self.open_workouts:
                    row.set_click_handler(self.open_workouts)
                self.workout_list.addWidget(row)
        else:
            self.workout_list.addWidget(
                EmptyState("🏃", "暂无运动记录", "Apple Watch 记录的训练会显示在这里")
            )

        # 睡眠卡
        self._refresh_sleep_card(night)

    def _refresh_status(self, stats: dict[str, Any]) -> None:
        if not self.controller.running:
            self.status.set_state("bad", "接收服务未启动")
        elif not stats.get("last_sync_ts"):
            self.status.set_state("warn", "等待首次同步")
        else:
            self.status.set_state("good", f"已同步 · {humanize_ago(stats['last_sync_ts'])}")

    def _refresh_sleep_card(self, night: dict[str, Any] | None) -> None:
        if not night or night["asleep_min"] <= 0:
            self.sleep_value.setText("--")
            self.sleep_efficiency.hide()
            self.stage_bar.set_segments([])
            self.sleep_legend.setText("同步睡眠数据后，这里会显示深睡 / 核心 / REM 分布。")
            self.sleep_meta.setText("")
            return

        self.sleep_value.setText(f"{night['asleep_min'] / 60.0:.1f}")
        self.sleep_efficiency.setText(f"睡眠效率 {night['efficiency']:.0f}%")
        self.sleep_efficiency.show()

        segments = [
            (night["deep_min"], SLEEP_COLORS["deep"]),
            (night["core_min"], SLEEP_COLORS["core"]),
            (night["rem_min"], SLEEP_COLORS["rem"]),
            (night["unspecified_min"], SLEEP_COLORS["light"]),
            (night["awake_min"], SLEEP_COLORS["awake"]),
        ]
        self.stage_bar.set_segments(segments)

        legend_parts = []
        for key, label, color in (
            ("deep_min", "深睡", SLEEP_COLORS["deep"]),
            ("core_min", "核心", SLEEP_COLORS["core"]),
            ("rem_min", "REM", SLEEP_COLORS["rem"]),
            ("awake_min", "清醒", SLEEP_COLORS["awake"]),
        ):
            minutes = night.get(key) or 0
            if minutes > 0:
                legend_parts.append(
                    f"<span style='color:{color}'>●</span> {label} {minutes:.0f} 分"
                )
        self.sleep_legend.setText("&nbsp;&nbsp;&nbsp;".join(legend_parts))
        self.sleep_meta.setText(
            f"{local_date_label(night['date'])} · "
            f"{local_time_label(night['start_ts'])} 入睡 · "
            f"{local_time_label(night['end_ts'])} 起床 · 卧床 {night['in_bed_min'] / 60:.1f} 小时"
        )


def _link_button(text: str, callback: Callable[[], None]) -> QPushButton:
    button = QPushButton(text)
    button.setObjectName("linkButton")
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.clicked.connect(callback)
    return button


# ---------------------------------------------------------------------------
# 趋势
# ---------------------------------------------------------------------------

_TREND_METRICS = [
    ("steps", "步数"),
    ("heart_rate", "心率（日均）"),
    ("resting_heart_rate", "静息心率"),
    ("hrv", "心率变异性"),
    ("sleep", "睡眠时长"),
    ("active_energy", "活动能量"),
    ("oxygen_saturation", "血氧"),
    ("respiratory_rate", "呼吸频率"),
    ("body_mass", "体重"),
]


class TrendsPage(QWidget):
    def __init__(self, db: Database, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.db = db
        self.days = 7

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        layout = _make_scroll(outer)
        layout.addLayout(_header("趋势", "把每天的健康数据连起来看"))

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        self.metric_combo = QComboBox()
        for key, label in _TREND_METRICS:
            self.metric_combo.addItem(label, key)
        self.metric_combo.setFixedWidth(170)
        self.metric_combo.currentIndexChanged.connect(self.refresh)
        toolbar.addWidget(self.metric_combo)
        toolbar.addSpacing(8)

        self.range_group = QButtonGroup(self)
        self.range_group.setExclusive(True)
        for index, (days, label) in enumerate(((7, "7 天"), (30, "30 天"), (90, "90 天"))):
            button = QPushButton(label)
            button.setObjectName("chipButton")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setChecked(days == 7)
            button.clicked.connect(lambda _=False, d=days: self._set_range(d))
            self.range_group.addButton(button, index)
            toolbar.addWidget(button)
        toolbar.addStretch(1)
        layout.addLayout(toolbar)

        stats_row = QHBoxLayout()
        stats_row.setSpacing(12)
        self.stat_1, self.stat_1_value = _stat_tile("平均")
        self.stat_2, self.stat_2_value = _stat_tile("最高")
        self.stat_3, self.stat_3_value = _stat_tile("最低")
        for tile in (self.stat_1, self.stat_2, self.stat_3):
            stats_row.addWidget(tile, 1)
        layout.addLayout(stats_row)

        self.line = LineChart(COLORS["accent"], "")
        self.line.setMinimumHeight(300)
        self.bar = BarChart(COLORS["accent"], "")
        self.bar.setMinimumHeight(300)
        self.stack = QStackedWidget()
        self.stack.addWidget(self.line)
        self.stack.addWidget(self.bar)
        self.chart_card = ChartCard("趋势", "近 7 天", self.stack)
        self.chart_card.setMinimumHeight(400)
        layout.addWidget(self.chart_card)
        layout.addStretch(1)

        QTimer.singleShot(0, self.refresh)

    def _set_range(self, days: int) -> None:
        self.days = days
        self.refresh()

    def select_metric(self, metric: str) -> None:
        """供仪表盘卡片跳转：切到指定指标并刷新。"""
        index = self.metric_combo.findData(metric)
        if index >= 0:
            self.metric_combo.setCurrentIndex(index)
            self.refresh()

    def refresh(self) -> None:
        metric = self.metric_combo.currentData()
        meta = analytics.METRIC_META.get(metric, {"label": metric, "unit": "", "digits": 1})
        points = analytics.daily_series(self.db, metric, self.days)
        values = [p["value"] for p in points]
        unit = meta["unit"]
        digits = int(meta["digits"])
        is_sleep = metric == "sleep"
        use_bar = is_sleep or metric in analytics.CUMULATIVE_TYPES

        self.chart_card.findChild(QLabel, "cardTitle").setText(f"{meta['label']} · 趋势")
        self.chart_card.set_subtitle(f"近 {self.days} 天")

        if use_bar:
            labels = []
            for index, point in enumerate(points):
                if self.days <= 7:
                    labels.append("今天" if index == len(points) - 1 else weekday_label(point["date"])[1:])
                else:
                    parts = point["date"].split("-")
                    labels.append(f"{int(parts[1])}/{int(parts[2])}")
            chart = self.bar
            chart.set_data(labels, values, unit)
            chart.set_empty_text(f"近 {self.days} 天暂无{meta['label']}数据")
        else:
            chart = self.line
            chart.set_data(_to_timestamp_points(points), unit)
            chart.set_empty_text(f"近 {self.days} 天暂无{meta['label']}数据")
        self.stack.setCurrentWidget(chart)

        stats_values = [v for v in values if v is not None]
        if not stats_values:
            self.stat_1_value.setText("--")
            self.stat_2_value.setText("--")
            self.stat_3_value.setText("--")
            return
        average = sum(stats_values) / len(stats_values)
        if metric in analytics.CUMULATIVE_TYPES:
            self.stat_1_value.setText(f"{fmt_float(sum(stats_values), digits)} {unit}")
            self.stat_2_value.setText(f"{fmt_float(max(stats_values), digits)} {unit}")
            self.stat_3_value.setText(f"{fmt_float(min(stats_values), digits)} {unit}")
            self.stat_1.findChild(QLabel, "subtle").setText("总计")
            self.stat_2.findChild(QLabel, "subtle").setText("单日最高")
            self.stat_3.findChild(QLabel, "subtle").setText("单日最低")
        else:
            self.stat_1_value.setText(f"{fmt_float(average, digits)} {unit}")
            self.stat_2_value.setText(f"{fmt_float(max(stats_values), digits)} {unit}")
            self.stat_3_value.setText(f"{fmt_float(min(stats_values), digits)} {unit}")
            self.stat_1.findChild(QLabel, "subtle").setText("平均")
            self.stat_2.findChild(QLabel, "subtle").setText("最高")
            self.stat_3.findChild(QLabel, "subtle").setText("最低")


def _to_timestamp_points(points: list[dict[str, Any]]) -> list[tuple[float, float]]:
    result: list[tuple[float, float]] = []
    for point in points:
        value = point.get("value")
        if value is None:
            continue
        try:
            ts = datetime.strptime(point["date"], "%Y-%m-%d").timestamp()
        except (KeyError, ValueError):
            continue
        result.append((ts, float(value)))
    return result


# ---------------------------------------------------------------------------
# 运动记录
# ---------------------------------------------------------------------------

class WorkoutsPage(QWidget):
    def __init__(self, db: Database, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.db = db
        self.days = 30

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        layout = _make_scroll(outer)
        layout.addLayout(_header("运动记录", "来自 Apple Watch / iPhone 的体能训练"))

        filter_row = QHBoxLayout()
        filter_row.setSpacing(8)
        self.filter_group = QButtonGroup(self)
        self.filter_group.setExclusive(True)
        for index, (days, label) in enumerate(
            ((7, "近 7 天"), (30, "近 30 天"), (90, "近 90 天"))
        ):
            button = QPushButton(label)
            button.setObjectName("chipButton")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setChecked(days == 30)
            button.clicked.connect(lambda _=False, d=days: self._set_days(d))
            self.filter_group.addButton(button, index)
            filter_row.addWidget(button)
        filter_row.addStretch(1)
        layout.addLayout(filter_row)

        summary_row = QHBoxLayout()
        summary_row.setSpacing(12)
        self.sum_count, self.sum_count_value = _stat_tile("运动次数")
        self.sum_time, self.sum_time_value = _stat_tile("总时长")
        self.sum_energy, self.sum_energy_value = _stat_tile("总消耗")
        for tile in (self.sum_count, self.sum_time, self.sum_energy):
            summary_row.addWidget(tile, 1)
        layout.addLayout(summary_row)

        self.list_card = Card()
        self.list_card.body.addLayout(card_header("训练列表", "点击上方时间范围筛选"))
        self.workout_list = QVBoxLayout()
        self.workout_list.setSpacing(8)
        self.list_card.body.addLayout(self.workout_list)
        self.list_card.body.addStretch(1)
        layout.addWidget(self.list_card)
        layout.addStretch(1)

    def _set_days(self, days: int) -> None:
        self.days = days
        self.refresh()

    def refresh(self) -> None:
        workouts = analytics.recent_workouts(self.db, days=self.days, limit=500)
        _clear_layout(self.workout_list)
        if not workouts:
            self.workout_list.addWidget(
                EmptyState(
                    "🏃",
                    "这段时间没有运动记录",
                    "在 iPhone 快捷指令中加入「查找体能训练」后，训练会自动同步到这里",
                )
            )
        else:
            for workout in workouts:
                self.workout_list.addWidget(WorkoutRow(workout))

        total_seconds = sum(float(w.get("duration_s") or 0) for w in workouts)
        total_energy = sum(float(w.get("energy_kcal") or 0) for w in workouts)
        self.sum_count_value.setText(f"{len(workouts)} 次")
        self.sum_time_value.setText(fmt_duration(total_seconds / 60, compact=True))
        self.sum_energy_value.setText(f"{total_energy:.0f} kcal")


# ---------------------------------------------------------------------------
# 同步与配对
# ---------------------------------------------------------------------------

class SyncPage(QWidget):
    def __init__(
        self,
        db: Database,
        config: Config,
        controller: ServerController,
        open_guide: Callable[[], None],
        open_puls_guide: Callable[[], None] | None = None,
        on_address_changed: Callable[[], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.db = db
        self.config = config
        self.controller = controller
        self.open_guide = open_guide
        self.open_puls_guide = open_puls_guide
        self.on_address_changed = on_address_changed
        self._qr_url = ""
        self.selected_ip = str(config.get("lan_ip") or primary_lan_ip())

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        layout = _make_scroll(outer)

        self.status = StatusPill()
        layout.addLayout(_header("同步与配对", "让 iPhone 通过同一 Wi-Fi 把数据送到这里", self.status))

        columns = QHBoxLayout()
        columns.setSpacing(14)

        left = QVBoxLayout()
        left.setSpacing(14)

        service_card = Card()
        service_card.body.addLayout(card_header("接收服务", "内嵌 HTTP 服务 · 局域网可见"))
        self.pill_row = QHBoxLayout()
        self.state_label = QLabel("● 启动中…")
        self.state_label.setStyleSheet(f"color: {COLORS['accent']}; font-size: 13px;")
        self.port_label = QLabel("")
        self.port_label.setObjectName("subtle")
        self.pill_row.addWidget(self.state_label)
        self.pill_row.addSpacing(8)
        self.pill_row.addWidget(self.port_label)
        self.pill_row.addStretch(1)
        service_card.body.addLayout(self.pill_row)

        ip_row = QHBoxLayout()
        ip_row.setSpacing(10)
        ip_label = QLabel("网络地址（点击切换）")
        ip_label.setObjectName("subtle")
        ip_row.addWidget(ip_label)
        self.ip_combo = QComboBox()
        self.ip_combo.setMinimumWidth(190)
        self.ip_combo.setToolTip(
            "选择手机能访问的电脑地址。VMware / VirtualBox 等虚拟网卡地址手机无法访问。"
        )
        self.ip_combo.currentTextChanged.connect(self._on_ip_changed)
        ip_row.addWidget(self.ip_combo)
        arrow = QLabel("▾")
        arrow.setStyleSheet(f"color: {COLORS['muted']}; font-size: 13px;")
        ip_row.addWidget(arrow)
        ip_row.addStretch(1)
        service_card.body.addLayout(ip_row)

        self.url_row = CopyRow("局域网地址（在 iPhone 上打开可验证连接）")
        self.endpoint_row = CopyRow("同步接口 URL")
        self.ping_row = CopyRow("连接测试 URL（GET，无需 Token）")
        self.token_row = CopyRow("访问令牌（Token）", secret=True)
        service_card.body.addWidget(self.url_row)
        service_card.body.addWidget(self.endpoint_row)
        service_card.body.addWidget(self.ping_row)
        service_card.body.addWidget(self.token_row)
        service_card.body.addWidget(Divider())

        hint = QLabel(
            "iPhone 与电脑需连接同一个 Wi-Fi。如果手机打不开且电脑没有弹防火墙提示，"
            "点击「修复防火墙」并同意管理员授权；地址请选择 Wi-Fi 网卡对应的那一项。"
        )
        hint.setWordWrap(True)
        hint.setObjectName("subtle")
        service_card.body.addWidget(hint)

        buttons = QHBoxLayout()
        guide_button = QPushButton("快捷指令配置指南")
        guide_button.setObjectName("ghostButton")
        guide_button.setCursor(Qt.CursorShape.PointingHandCursor)
        guide_button.clicked.connect(self.open_guide)
        buttons.addWidget(guide_button)
        test_button = QPushButton("检查服务")
        test_button.setObjectName("ghostButton")
        test_button.setCursor(Qt.CursorShape.PointingHandCursor)
        test_button.clicked.connect(self._check_service)
        buttons.addWidget(test_button)
        firewall_button = QPushButton("修复防火墙")
        firewall_button.setObjectName("ghostButton")
        firewall_button.setCursor(Qt.CursorShape.PointingHandCursor)
        firewall_button.setToolTip("需要管理员权限，会弹出 UAC 确认框")
        firewall_button.clicked.connect(self._fix_firewall)
        buttons.addWidget(firewall_button)
        buttons.addStretch(1)
        service_card.body.addLayout(buttons)
        left.addWidget(service_card)

        puls_card = Card()
        puls_card.body.addLayout(
            card_header(
                "PulsHealth 自动同步（推荐）",
                "免费 App · 最多 5 类数据 · 不需要快捷指令",
            )
        )
        puls_desc = QLabel(
            "在 iPhone 上安装免费的 PulsHealth，把 Database URL 填成上方的局域网地址、"
            "Token 填成上方的访问令牌，开启自动同步即可。免费版支持最近 30 天、最多 5 类数据。"
        )
        puls_desc.setWordWrap(True)
        puls_desc.setObjectName("subtle")
        puls_card.body.addWidget(puls_desc)
        puls_steps = QLabel(
            "1. App Store 搜索并安装 PulsHealth\n"
            "2. Sync → Database → Your Own Database：填入地址与 Token，Test Connection\n"
            "3. 选择 5 类数据并允许健康权限，开启自动同步"
        )
        puls_steps.setWordWrap(True)
        puls_steps.setStyleSheet(f"color: {COLORS['muted']}; font-size: 12px;")
        puls_card.body.addWidget(puls_steps)
        puls_buttons = QHBoxLayout()
        puls_guide_button = QPushButton("打开 PulsHealth 配置指南")
        puls_guide_button.setObjectName("primaryButton")
        puls_guide_button.setCursor(Qt.CursorShape.PointingHandCursor)
        puls_guide_button.clicked.connect(self.open_puls_guide or self.open_guide)
        puls_buttons.addWidget(puls_guide_button)
        puls_buttons.addStretch(1)
        puls_card.body.addLayout(puls_buttons)
        left.addWidget(puls_card)

        metrics_card = Card()
        metrics_card.body.addLayout(card_header("已接收的指标", "按样本数量排序"))
        self.metrics_label = QLabel("还没有收到数据")
        self.metrics_label.setWordWrap(True)
        self.metrics_label.setStyleSheet(f"color: {COLORS['muted']}; font-size: 12px; line-height: 1.9;")
        metrics_card.body.addWidget(self.metrics_label)
        left.addWidget(metrics_card)
        left.addStretch(1)

        right = QVBoxLayout()
        right.setSpacing(14)

        qr_card = Card()
        qr_card.body.addLayout(card_header("扫码验证", "iPhone 相机扫码打开"))
        self.qr_label = QLabel()
        self.qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.qr_label.setFixedHeight(190)
        qr_card.body.addWidget(self.qr_label)
        qr_hint = QLabel(
            "能看到「接收服务运行中」页面，说明手机与电脑已连通。\n"
            "iOS 18.2+ 若提示「无法建立安全连接」，请关闭 Safari 的「不安全连接警告」。"
        )
        qr_hint.setWordWrap(True)
        qr_hint.setObjectName("subtle")
        qr_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        qr_card.body.addWidget(qr_hint)
        right.addWidget(qr_card)

        events_card = Card()
        events_card.body.addLayout(card_header("最近同步", "最新 6 条"))
        self.events_list = QVBoxLayout()
        self.events_list.setSpacing(8)
        events_card.body.addLayout(self.events_list)
        events_card.body.addStretch(1)
        right.addWidget(events_card, 1)

        columns.addLayout(left, 3)
        columns.addLayout(right, 2)
        layout.addLayout(columns)
        layout.addStretch(1)

        self.refresh()

    # ------------------------------------------------------------------
    def _sync_ip_options(self) -> None:
        addresses = local_ipv4_addresses() or ["127.0.0.1"]
        configured = str(self.config.get("lan_ip") or "").strip()
        if configured and configured in addresses:
            current = configured
        else:
            current = addresses[0]
            if configured != current:
                self.config.set("lan_ip", current)

        existing = [
            self.ip_combo.itemText(index) for index in range(self.ip_combo.count())
        ]
        if existing != addresses or self.ip_combo.currentText() != current:
            self.ip_combo.blockSignals(True)
            self.ip_combo.clear()
            self.ip_combo.addItems(addresses)
            index = self.ip_combo.findText(current)
            self.ip_combo.setCurrentIndex(max(0, index))
            self.ip_combo.blockSignals(False)
        self.selected_ip = current

    def _on_ip_changed(self, ip: str) -> None:
        if not ip:
            return
        self.config.set("lan_ip", ip)
        self.selected_ip = ip
        self._qr_url = ""
        self.refresh()
        if self.on_address_changed:
            self.on_address_changed()

    def _fix_firewall(self) -> None:
        port = self.controller.port
        answer = QMessageBox.question(
            self,
            "修复 Windows 防火墙",
            f"Windows 将当前 Wi-Fi 识别为公用网络，默认会拦截手机的入站连接。\n\n"
            f"接下来会请求管理员权限，为 TCP 端口 {port} 添加入站规则"
            f"（仅允许同一局域网访问）。出现 UAC 弹窗时请点击「是」。\n\n继续吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        launched, error = add_firewall_rule_elevated(port)
        if launched:
            QMessageBox.information(
                self,
                "已发起修复",
                f"防火墙规则正在添加。请等待几秒后，用 iPhone Safari 打开：\n\n"
                f"{self._base_url()}\n\n"
                "如果仍然打不开，请确认手机与电脑在同一 Wi-Fi，且路由器未开启 AP 隔离。",
            )
        else:
            QMessageBox.warning(
                self,
                "未能自动修复",
                f"{error}\n\n"
                "请右键「终端（管理员）」并执行：\n\n"
                f'netsh advfirewall firewall add rule name="PulseBridge Health Receiver" '
                f"dir=in action=allow protocol=TCP localport={port} "
                f"profile=any remoteip=localsubnet",
            )

    def _base_url(self) -> str:
        return app_base_url(self.controller.port, self.selected_ip)

    def refresh(self) -> None:
        self._sync_ip_options()
        base = self._base_url()
        endpoint = f"{base}/api/ingest"
        self.url_row.set_value(base)
        self.endpoint_row.set_value(endpoint)
        self.ping_row.set_value(f"{base}/api/ping")
        self.token_row.set_value(self.config.token)
        self.port_label.setText(f"端口 {self.controller.port} · 监听 0.0.0.0")

        if self.controller.running:
            self.state_label.setText("● 运行中")
            self.state_label.setStyleSheet(f"color: {COLORS['accent']}; font-size: 13px;")
            self.status.set_state("good", "接收服务运行中")
        else:
            self.state_label.setText("● 未启动")
            self.state_label.setStyleSheet(f"color: {COLORS['red']}; font-size: 13px;")
            self.status.set_state("bad", self.controller.error or "接收服务未启动")

        if base != self._qr_url:
            self._qr_url = base
            self._set_qr(base)

        self._refresh_events()
        self._refresh_metrics()

    def _set_qr(self, text: str) -> None:
        try:
            import io

            import segno

            qr = segno.make(text, error="m")
            buffer = io.BytesIO()
            qr.save(buffer, kind="png", scale=8, border=2, dark="#0A0E14", light="#FFFFFF")
            pixmap = QPixmap()
            pixmap.loadFromData(buffer.getvalue())
            self.qr_label.setPixmap(
                pixmap.scaled(
                    QSize(178, 178),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        except Exception:
            self.qr_label.setText("无法生成二维码")

    def _refresh_events(self) -> None:
        _clear_layout(self.events_list)
        events = self.db.recent_events(6)
        if not events:
            self.events_list.addWidget(
                EmptyState("📡", "还没有同步记录", "配置好快捷指令并运行一次即可看到")
            )
            return
        for event in events:
            row = QFrame()
            row.setObjectName("row")
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(12, 10, 12, 10)
            row_layout.setSpacing(10)
            ok = event.get("status") == "ok"
            dot = QLabel("●")
            dot.setStyleSheet(
                f"color: {COLORS['accent'] if ok else COLORS['red']}; font-size: 11px;"
            )
            row_layout.addWidget(dot)
            info = QVBoxLayout()
            info.setSpacing(2)
            if ok:
                title = (
                    f"+{event.get('samples_new', 0)} 样本"
                    f" · +{event.get('workouts_new', 0)} 运动"
                )
                subtitle = (
                    f"{humanize_ago(event['received_at'])} · "
                    f"{event.get('device') or event.get('remote') or 'iPhone'}"
                )
                if event.get("samples_dupe"):
                    subtitle += f" · 去重 {event['samples_dupe']}"
            else:
                title = "同步失败"
                subtitle = (event.get("message") or "未知错误")[:80]
            title_label = QLabel(title)
            title_label.setStyleSheet("font-size: 12px; font-weight: 600;")
            sub_label = QLabel(subtitle)
            sub_label.setObjectName("subtle")
            sub_label.setWordWrap(True)
            info.addWidget(title_label)
            info.addWidget(sub_label)
            row_layout.addLayout(info, 1)
            self.events_list.addWidget(row)

    def _refresh_metrics(self) -> None:
        counts = self.db.sample_type_counts()
        if not counts:
            self.metrics_label.setText("还没有收到数据")
            return
        labels = {
            "heart_rate": "心率",
            "resting_heart_rate": "静息心率",
            "hrv": "HRV",
            "steps": "步数",
            "active_energy": "活动能量",
            "sleep_analysis": "睡眠",
            "oxygen_saturation": "血氧",
            "respiratory_rate": "呼吸频率",
            "body_mass": "体重",
            "vo2max": "最大摄氧量",
        }
        parts = [
            f"<span style='color:{COLORS['text']}'>{labels.get(key, key)}</span>"
            f" <span style='color:{COLORS['subtle']}'>{count:,}</span>"
            for key, count in list(counts.items())[:10]
        ]
        self.metrics_label.setText("&nbsp;&nbsp;·&nbsp;&nbsp;".join(parts))

    def _check_service(self) -> None:
        url = f"http://127.0.0.1:{self.controller.port}/api/ping"
        try:
            with urllib.request.urlopen(url, timeout=2.5) as response:  # noqa: S310
                payload = json.loads(response.read().decode("utf-8"))
            QMessageBox.information(
                self,
                "服务正常",
                f"PulseBridge 接收服务在线。\n\n最近同步："
                f"{humanize_ago(payload.get('last_sync_ts'))}",
            )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(
                self,
                "无法连接服务",
                f"本机访问 {url} 失败：{exc}\n\n可在「设置」中换一个端口后重试。",
            )


# ---------------------------------------------------------------------------
# AI 洞察（预留）
# ---------------------------------------------------------------------------

class AiPage(QWidget):
    def __init__(self, db: Database, export_callback: Callable[[], None], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.db = db
        self.export_callback = export_callback

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        layout = _make_scroll(outer)

        badge = QLabel("规划中")
        badge.setObjectName("chip")
        layout.addLayout(_header("AI 洞察", "数据已经准备好，分析能力即将接入", badge))

        hero = Card()
        hero.body.addLayout(
            card_header(
                "为 AI 分析打底",
                "结构化存储 · 可导出 · 可按时间窗读取",
            )
        )
        description = QLabel(
            "PulseBridge 会把所有数据归一化后存进本地 SQLite，包括心率、静息心率、HRV、"
            "睡眠阶段、步数、活动能量和运动记录。后续版本会加入大模型分析：\n\n"
            "· 睡眠质量与恢复状态解读\n"
            "· 训练负荷与心率区间趋势\n"
            "· 每周健康摘要与可执行建议\n"
            "· 异常波动提醒（需要你主动开启）\n\n"
            "所有数据默认只保存在这台电脑上，接入云端模型前会明确征得你的同意。"
        )
        description.setWordWrap(True)
        description.setStyleSheet(f"color: {COLORS['muted']}; font-size: 13px; line-height: 1.75;")
        hero.body.addWidget(description)
        layout.addWidget(hero)

        summary_card = Card()
        summary_card.body.addLayout(card_header("近 7 天数据概览", "用于 AI 提示词的数据摘要"))
        self.summary_label = QLabel("")
        self.summary_label.setWordWrap(True)
        self.summary_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.summary_label.setStyleSheet(
            f"color: {COLORS['muted']}; font-size: 12px; line-height: 1.9;"
        )
        summary_card.body.addWidget(self.summary_label)

        buttons = QHBoxLayout()
        export_button = QPushButton("导出最近 30 天 JSON")
        export_button.setObjectName("primaryButton")
        export_button.setCursor(Qt.CursorShape.PointingHandCursor)
        export_button.clicked.connect(self.export_callback)
        buttons.addWidget(export_button)

        copy_button = QPushButton("复制数据摘要")
        copy_button.setObjectName("ghostButton")
        copy_button.setCursor(Qt.CursorShape.PointingHandCursor)
        copy_button.clicked.connect(self._copy_summary)
        buttons.addWidget(copy_button)

        upcoming = QPushButton("AI 分析（即将上线）")
        upcoming.setObjectName("ghostButton")
        upcoming.setEnabled(False)
        buttons.addWidget(upcoming)
        buttons.addStretch(1)
        summary_card.body.addLayout(buttons)
        layout.addWidget(summary_card)
        layout.addStretch(1)

        self.refresh()

    def refresh(self) -> None:
        lines = []
        for metric, label, unit, digits in (
            ("steps", "步数", "步", 0),
            ("resting_heart_rate", "静息心率", "bpm", 0),
            ("hrv", "HRV", "ms", 0),
            ("sleep", "睡眠", "小时", 1),
            ("active_energy", "活动能量", "kcal", 0),
        ):
            points = analytics.daily_series(self.db, metric, 7)
            stats = analytics.series_stats(points, metric in analytics.CUMULATIVE_TYPES)
            if stats["count"] == 0:
                continue
            if metric == "sleep":
                text = f"平均 {fmt_float(stats['avg'], digits)} {unit}"
            elif metric in analytics.CUMULATIVE_TYPES:
                text = f"日均 {fmt_float(stats['avg'], digits)} {unit} · 最高 {fmt_float(stats['max'], digits)}"
            else:
                text = f"平均 {fmt_float(stats['avg'], digits)} {unit} · 区间 {fmt_float(stats['min'], digits)}–{fmt_float(stats['max'], digits)}"
            lines.append(f"{label}：{text}")
        self.summary_label.setText("　　".join(lines) if lines else "还没有足够的数据，先在 iPhone 上运行一次同步。")

    def _copy_summary(self) -> None:
        from PySide6.QtWidgets import QApplication

        QApplication.clipboard().setText(self.summary_label.text())


# ---------------------------------------------------------------------------
# 设置
# ---------------------------------------------------------------------------

class _HealthImportWorker(QObject):
    progress = Signal(int, int, int, int)
    finished = Signal(dict)
    failed = Signal(str)

    def __init__(self, path: Path, db: Database, stop_event: threading.Event) -> None:
        super().__init__()
        self.path = path
        self.db = db
        self.stop_event = stop_event

    def run(self) -> None:
        try:
            summary = import_health_export(
                self.path,
                self.db,
                progress=lambda *args: self.progress.emit(*args),
                stop_event=self.stop_event,
            )
            self.finished.emit(summary.as_dict())
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


class SettingsPage(QWidget):
    def __init__(
        self,
        db: Database,
        config: Config,
        controller: ServerController,
        refresh_all: RefreshAll,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.db = db
        self.config = config
        self.controller = controller
        self.refresh_all = refresh_all
        self._loading = False
        self._import_thread: threading.Thread | None = None
        self._import_worker: _HealthImportWorker | None = None
        self._import_dialog: QProgressDialog | None = None
        self._import_stop: threading.Event | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        layout = _make_scroll(outer)
        layout.addLayout(_header("设置", "启动方式、接收端口、数据导入与提醒"))

        # 通用
        general = Card()
        general.body.addLayout(card_header("常规", "只影响这台电脑上的程序"))
        self.startup_toggle = ToggleSwitch()
        self.minimized_toggle = ToggleSwitch()
        self.tray_toggle = ToggleSwitch()
        general.body.addLayout(
            _toggle_row("开机自动启动 PulseBridge", self.startup_toggle)
        )
        general.body.addLayout(
            _toggle_row("启动后最小化到系统托盘", self.minimized_toggle)
        )
        general.body.addLayout(
            _toggle_row("关闭窗口时最小化到托盘（不退出）", self.tray_toggle)
        )
        self.startup_toggle.toggled.connect(self._on_startup_changed)
        self.minimized_toggle.toggled.connect(
            lambda checked: self.config.set("start_minimized", checked)
        )
        self.tray_toggle.toggled.connect(
            lambda checked: self.config.set("close_to_tray", checked)
        )
        layout.addWidget(general)

        # 接收服务
        service = Card()
        service.body.addLayout(card_header("接收服务", "iPhone 快捷指令连接此端口"))
        port_row = QHBoxLayout()
        port_row.setSpacing(10)
        port_label = QLabel("监听端口")
        port_label.setObjectName("subtle")
        port_row.addWidget(port_label)
        self.port_edit = QLineEdit(str(self.config.port))
        self.port_edit.setValidator(QIntValidator(1024, 65535, self))
        self.port_edit.setFixedWidth(120)
        port_row.addWidget(self.port_edit)
        apply_button = QPushButton("应用端口")
        apply_button.setObjectName("ghostButton")
        apply_button.setCursor(Qt.CursorShape.PointingHandCursor)
        apply_button.clicked.connect(self._apply_port)
        port_row.addWidget(apply_button)
        port_row.addStretch(1)
        service.body.addLayout(port_row)

        self.token_row = CopyRow("访问令牌（修改后需同步更新快捷指令）", self.config.token, secret=True)
        service.body.addWidget(self.token_row)
        token_button = QPushButton("重新生成 Token")
        token_button.setObjectName("ghostButton")
        token_button.setCursor(Qt.CursorShape.PointingHandCursor)
        token_button.clicked.connect(self._regenerate_token)
        service.body.addWidget(token_button, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(service)

        # 数据
        data_card = Card()
        data_card.body.addLayout(card_header("数据", "存储在本地 SQLite，不上传云端"))
        data_path = str(self.db.path.parent)
        path_row = QHBoxLayout()
        path_row.setSpacing(10)
        path_label = QLabel(data_path)
        path_label.setObjectName("mono")
        path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        path_label.setWordWrap(True)
        path_row.addWidget(path_label, 1)
        open_button = QPushButton("打开目录")
        open_button.setObjectName("ghostButton")
        open_button.setCursor(Qt.CursorShape.PointingHandCursor)
        open_button.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(data_path))
        )
        path_row.addWidget(open_button)
        data_card.body.addLayout(path_row)

        retention_row = QHBoxLayout()
        retention_row.setSpacing(10)
        retention_label = QLabel("数据保留")
        retention_label.setObjectName("subtle")
        retention_row.addWidget(retention_label)
        self.retention_combo = QComboBox()
        self.retention_combo.addItem("永久保存", 0)
        self.retention_combo.addItem("保留 365 天", 365)
        self.retention_combo.addItem("保留 90 天", 90)
        index = self.retention_combo.findData(int(self.config.get("retention_days", 0)))
        self.retention_combo.setCurrentIndex(max(0, index))
        self.retention_combo.setFixedWidth(150)
        self.retention_combo.currentIndexChanged.connect(self._on_retention_changed)
        retention_row.addWidget(self.retention_combo)
        retention_row.addStretch(1)
        data_card.body.addLayout(retention_row)

        buttons = QHBoxLayout()
        export_button = QPushButton("导出 JSON")
        export_button.setObjectName("ghostButton")
        export_button.setCursor(Qt.CursorShape.PointingHandCursor)
        export_button.clicked.connect(lambda: export_data(self))
        buttons.addWidget(export_button)
        clear_button = QPushButton("清空所有数据")
        clear_button.setObjectName("ghostButton")
        clear_button.setCursor(Qt.CursorShape.PointingHandCursor)
        clear_button.setStyleSheet(f"color: {COLORS['red']};")
        clear_button.clicked.connect(self._clear_data)
        buttons.addWidget(clear_button)
        buttons.addStretch(1)
        data_card.body.addLayout(buttons)
        layout.addWidget(data_card)

        # Apple Health 导出导入 + 提醒
        import_card = Card()
        import_card.body.addLayout(
            card_header(
                "Apple Health 导出导入",
                "全量历史 · 不受 PulsHealth 5 类限制",
            )
        )
        import_hint = QLabel(
            "iPhone 健康 App → 右上角头像 → 导出所有健康数据 → 把 export.zip 传到电脑，"
            "在这里导入。所有指标和全部历史都会合并进本地数据库；重复导入会自动去重。"
        )
        import_hint.setWordWrap(True)
        import_hint.setObjectName("subtle")
        import_card.body.addWidget(import_hint)

        import_row = QHBoxLayout()
        import_row.setSpacing(12)
        self.import_button = QPushButton("选择 export.zip 导入")
        self.import_button.setObjectName("primaryButton")
        self.import_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.import_button.clicked.connect(self._start_health_import)
        import_row.addWidget(self.import_button)
        self.import_last_label = QLabel("上次导入：从未")
        self.import_last_label.setObjectName("subtle")
        import_row.addWidget(self.import_last_label, 1)
        import_card.body.addLayout(import_row)

        reminder_header = QHBoxLayout()
        reminder_title = QLabel("定时导入提醒")
        reminder_title.setObjectName("subtle")
        reminder_header.addWidget(reminder_title)
        reminder_header.addStretch(1)
        self.reminder_toggle = ToggleSwitch()
        reminder_header.addWidget(self.reminder_toggle)
        import_card.body.addLayout(reminder_header)

        schedule_row = QHBoxLayout()
        schedule_row.setSpacing(10)
        self.reminder_freq = QComboBox()
        self.reminder_freq.addItem("每周", "weekly")
        self.reminder_freq.addItem("每月", "monthly")
        self.reminder_freq.setFixedWidth(92)
        schedule_row.addWidget(self.reminder_freq)

        self.reminder_weekday = QComboBox()
        for index, label in enumerate(("周一", "周二", "周三", "周四", "周五", "周六", "周日")):
            self.reminder_weekday.addItem(label, index)
        self.reminder_weekday.setFixedWidth(92)
        schedule_row.addWidget(self.reminder_weekday)

        self.reminder_day = QComboBox()
        for day in range(1, 29):
            self.reminder_day.addItem(f"{day} 号", day)
        self.reminder_day.setFixedWidth(92)
        schedule_row.addWidget(self.reminder_day)

        self.reminder_time = QTimeEdit()
        self.reminder_time.setDisplayFormat("HH:mm")
        self.reminder_time.setFixedWidth(92)
        schedule_row.addWidget(self.reminder_time)
        schedule_row.addStretch(1)
        import_card.body.addLayout(schedule_row)

        self.reminder_next_label = QLabel("提醒未开启")
        self.reminder_next_label.setObjectName("subtle")
        import_card.body.addWidget(self.reminder_next_label)
        self.import_due_label = QLabel("")
        self.import_due_label.setObjectName("warn")
        self.import_due_label.setWordWrap(True)
        self.import_due_label.hide()
        import_card.body.addWidget(self.import_due_label)

        reminder_note = QLabel(
            "提醒只在 PulseBridge 运行时触发（可开机自启 / 最小化到托盘）；"
            "如果到点时电脑关机，下次启动后会补提醒。"
        )
        reminder_note.setWordWrap(True)
        reminder_note.setObjectName("subtle")
        import_card.body.addWidget(reminder_note)

        self.reminder_toggle.toggled.connect(lambda _checked: self._save_reminder_settings())
        self.reminder_freq.currentIndexChanged.connect(
            lambda _index: self._save_reminder_settings()
        )
        self.reminder_weekday.currentIndexChanged.connect(
            lambda _index: self._save_reminder_settings()
        )
        self.reminder_day.currentIndexChanged.connect(
            lambda _index: self._save_reminder_settings()
        )
        self.reminder_time.timeChanged.connect(
            lambda _value: self._save_reminder_settings()
        )
        layout.addWidget(import_card)

        # 关于
        about = Card()
        about.body.addLayout(card_header(f"{APP_NAME} v{APP_VERSION}", "本地优先的 Apple 健康数据看板"))
        about_text = QLabel(
            "数据来源：PulsHealth 自动同步、Apple Health 导出导入、iOS 快捷指令。\n\n"
            "隐私：所有数据保存在本机，Token 仅用于局域网写入鉴权。请勿将端口暴露到公网。"
        )
        about_text.setWordWrap(True)
        about_text.setObjectName("subtle")
        about.body.addWidget(about_text)
        layout.addWidget(about)
        layout.addStretch(1)

        self._load()

    def _load(self) -> None:
        self._loading = True
        self.startup_toggle.setChecked(startup.is_launch_at_startup())
        self.minimized_toggle.setChecked(bool(self.config.get("start_minimized")))
        self.tray_toggle.setChecked(bool(self.config.get("close_to_tray")))
        self._load_import_settings()
        self._loading = False

    def _load_import_settings(self) -> None:
        was_loading = self._loading
        self._loading = True
        self.reminder_toggle.setChecked(
            bool(self.config.get("import_reminder_enabled"))
        )
        frequency = str(self.config.get("import_reminder_frequency") or "monthly")
        index = self.reminder_freq.findData(frequency)
        self.reminder_freq.setCurrentIndex(max(0, index))
        weekday = int(self.config.get("import_reminder_weekday") or 0)
        index = self.reminder_weekday.findData(weekday)
        self.reminder_weekday.setCurrentIndex(max(0, index))
        day = int(self.config.get("import_reminder_day") or 1)
        index = self.reminder_day.findData(day)
        self.reminder_day.setCurrentIndex(max(0, index))
        clock = QTime.fromString(
            str(self.config.get("import_reminder_time") or "09:00"), "HH:mm"
        )
        self.reminder_time.setTime(clock if clock.isValid() else QTime(9, 0))
        self._loading = was_loading
        self._update_reminder_visibility()
        self._refresh_import_labels()

    def _update_reminder_visibility(self) -> None:
        enabled = self.reminder_toggle.isChecked()
        for control in (
            self.reminder_freq,
            self.reminder_weekday,
            self.reminder_day,
            self.reminder_time,
        ):
            control.setEnabled(enabled)
        weekly = self.reminder_freq.currentData() == "weekly"
        self.reminder_weekday.setVisible(weekly)
        self.reminder_day.setVisible(not weekly)

    def _save_reminder_settings(self) -> None:
        if self._loading:
            return
        self.config.set(
            "import_reminder_enabled", self.reminder_toggle.isChecked()
        )
        self.config.set(
            "import_reminder_frequency", self.reminder_freq.currentData() or "monthly"
        )
        self.config.set(
            "import_reminder_weekday", int(self.reminder_weekday.currentData() or 0)
        )
        self.config.set("import_reminder_day", int(self.reminder_day.currentData() or 1))
        self.config.set(
            "import_reminder_time", self.reminder_time.time().toString("HH:mm")
        )
        self._update_reminder_visibility()
        self._refresh_import_labels()

    def refresh_import_status(self) -> None:
        self._refresh_import_labels()

    def _refresh_import_labels(self) -> None:
        last = int(self.config.get("last_health_import_ts") or 0)
        self.import_last_label.setText(
            f"上次导入：{humanize_ago(last) if last else '从未'}"
        )
        if not bool(self.config.get("import_reminder_enabled")):
            self.reminder_next_label.setText("提醒未开启")
            self.import_due_label.hide()
            return
        now = datetime.now()
        upcoming = next_for_config(self.config, now)
        self.reminder_next_label.setText(
            f"下次提醒：{upcoming:%Y-%m-%d %H:%M}" if upcoming else "下次提醒：--"
        )
        due = due_occurrence(self.config, now)
        if due:
            self.import_due_label.setText(
                f"已到导入时间（{due:%Y-%m-%d %H:%M}），请选择最新的 export.zip"
            )
            self.import_due_label.show()
        else:
            self.import_due_label.hide()

    # ------------------------------------------------------------------
    def _start_health_import(self) -> None:
        if self._import_thread is not None and self._import_thread.is_alive():
            return
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择 Apple Health 导出文件",
            str(Path.home()),
            "Apple Health 导出 (*.zip *.xml);;所有文件 (*)",
        )
        if not path:
            return

        self._import_stop = threading.Event()
        worker = _HealthImportWorker(Path(path), self.db, self._import_stop)
        dialog = QProgressDialog("正在读取 export.xml…", "取消", 0, 0, self)
        dialog.setWindowTitle("导入 Apple Health")
        dialog.setWindowModality(Qt.WindowModality.WindowModal)
        dialog.setMinimumDuration(0)
        dialog.setAutoClose(False)
        dialog.setAutoReset(False)
        dialog.canceled.connect(self._cancel_health_import)
        dialog.show()
        self._import_dialog = dialog
        self._import_worker = worker
        self.import_button.setEnabled(False)

        worker.progress.connect(self._on_import_progress)
        worker.finished.connect(self._on_import_finished)
        worker.failed.connect(self._on_import_failed)

        thread = threading.Thread(target=worker.run, daemon=True)
        self._import_thread = thread
        thread.start()

    def _cancel_health_import(self) -> None:
        if self._import_stop is not None:
            self._import_stop.set()
        if self._import_dialog is not None:
            self._import_dialog.setLabelText("正在停止…")
            self._import_dialog.setCancelButton(None)

    def _on_import_progress(
        self, records: int, workouts: int, samples_new: int, workouts_new: int
    ) -> None:
        if self._import_dialog is not None:
            self._import_dialog.setLabelText(
                f"已处理 {records:,} 条记录 / {workouts:,} 个训练\n"
                f"新增样本 {samples_new:,} · 新增运动 {workouts_new:,}"
            )

    def _close_import_dialog(self) -> None:
        if self._import_dialog is not None:
            self._import_dialog.close()
            self._import_dialog = None
        self.import_button.setEnabled(True)

    def _on_import_finished(self, summary: dict) -> None:
        self._close_import_dialog()
        self._import_thread = None
        self._import_worker = None
        if summary.get("cancelled"):
            QMessageBox.information(
                self,
                "导入已取消",
                f"已取消。已处理 {summary.get('records', 0):,} 条记录，"
                f"新增样本 {summary.get('samples_new', 0):,}，"
                f"新增运动 {summary.get('workouts_new', 0):,}。",
            )
        else:
            self.config.set(
                "last_health_import_ts", int(datetime.now().timestamp())
            )
            self.config.set("import_reminder_last_shown", "")
            self.refresh_all()
            QMessageBox.information(
                self,
                "导入完成",
                f"处理记录：{summary.get('records', 0):,} 条\n"
                f"新增样本：{summary.get('samples_new', 0):,} 条"
                f"（重复 {summary.get('samples_dupe', 0):,}）\n"
                f"新增运动：{summary.get('workouts_new', 0):,} 条"
                f"（重复 {summary.get('workouts_dupe', 0):,}）\n"
                f"耗时：{summary.get('duration_s', 0)} 秒",
            )
        self._refresh_import_labels()

    def _on_import_failed(self, message: str) -> None:
        self._close_import_dialog()
        self._import_thread = None
        self._import_worker = None
        QMessageBox.warning(self, "导入失败", message)

    def _on_startup_changed(self, enabled: bool) -> None:
        if self._loading:
            return
        ok = startup.set_launch_at_startup(enabled)
        if ok:
            self.config.set("launch_at_startup", enabled)
        else:
            self.startup_toggle.setChecked(not enabled)

    def _apply_port(self) -> None:
        text = self.port_edit.text().strip()
        if not text.isdigit() or not (1024 <= int(text) <= 65535):
            QMessageBox.warning(self, "端口无效", "端口必须在 1024–65535 之间。")
            return
        new_port = int(text)
        old_port = self.config.port
        if new_port == old_port:
            return
        self.config.set("port", new_port)
        if self.controller.start():
            QMessageBox.information(
                self,
                "端口已切换",
                f"接收服务已在端口 {new_port} 运行。\n\n"
                "请在 iPhone 快捷指令中把 URL 里的端口改成新端口，并同步更新 Token。",
            )
            self.refresh_all()
        else:
            self.config.set("port", old_port)
            self.controller.start()
            QMessageBox.warning(
                self,
                "端口切换失败",
                self.controller.error or f"无法在端口 {new_port} 启动服务，已恢复原端口。",
            )
            self.port_edit.setText(str(old_port))

    def _regenerate_token(self) -> None:
        answer = QMessageBox.question(
            self,
            "重新生成 Token",
            "生成新 Token 后，iPhone 快捷指令中的旧 Token 会立即失效，需要手动替换。\n\n继续吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        token = self.config.regenerate_token()
        self.token_row.set_value(token)
        self.refresh_all()
        QMessageBox.information(self, "已生成", "请复制新 Token 并更新快捷指令。")

    def _on_retention_changed(self) -> None:
        days = int(self.retention_combo.currentData() or 0)
        self.config.set("retention_days", days)
        if days > 0:
            removed = self.db.purge_older_than(days)
            self.refresh_all()
            QMessageBox.information(self, "已清理", f"已删除 {removed:,} 条超过 {days} 天的记录。")

    def _clear_data(self) -> None:
        answer = QMessageBox.question(
            self,
            "清空所有数据",
            "这会删除所有健康样本、运动记录和同步日志，且无法撤销。\n\n确定继续吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.db.clear_data()
        self.refresh_all()
        QMessageBox.information(self, "已清空", "本地数据已全部删除。")

    def refresh(self) -> None:
        self._load()


def export_data(parent: QWidget, days: int = 30) -> None:
    default_name = f"pulsebridge-{datetime.now():%Y%m%d}-{days}d.json"
    path, _ = QFileDialog.getSaveFileName(
        parent, "导出健康数据", str(Path.home() / default_name), "JSON (*.json)"
    )
    if not path:
        return
    db = getattr(parent, "db", None)
    if db is None:
        return
    payload = db.export_payload(QDateTime.currentSecsSinceEpoch() - days * 86400)
    try:
        Path(path).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        QMessageBox.information(parent, "导出成功", f"已导出到：\n{path}")
    except OSError as exc:
        QMessageBox.warning(parent, "导出失败", str(exc))


def open_guide_dialog(parent: QWidget, base_url: str, token: str) -> None:
    _open_guide_dialog(
        parent,
        "快捷指令配置指南",
        build_guide_html(base_url, token),
        base_url,
        token,
        copy_value=f"{base_url}/api/ingest",
        copy_label="复制接口地址",
        template=shortcut_payload_template(base_url),
    )


def open_puls_guide_dialog(parent: QWidget, base_url: str, token: str) -> None:
    _open_guide_dialog(
        parent,
        "PulsHealth 自动同步配置",
        build_puls_guide_html(base_url, token),
        base_url,
        token,
        copy_value=base_url,
        copy_label="复制数据库地址",
    )


def _open_guide_dialog(
    parent: QWidget,
    title: str,
    html_text: str,
    base_url: str,
    token: str,
    copy_value: str | None = None,
    copy_label: str = "复制接口地址",
    template: dict | None = None,
) -> None:
    dialog = QDialog(parent)
    dialog.setWindowTitle(title)
    dialog.resize(820, 720)
    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(18, 18, 18, 16)
    layout.setSpacing(12)

    browser = QTextBrowser()
    browser.setOpenExternalLinks(True)
    browser.setHtml(html_text)
    layout.addWidget(browser, 1)

    buttons = QHBoxLayout()
    copy_url = QPushButton(copy_label)
    copy_url.setObjectName("ghostButton")
    copy_url.setCursor(Qt.CursorShape.PointingHandCursor)
    copy_url.clicked.connect(
        lambda: _copy_and_flash(copy_url, copy_value or base_url)
    )
    buttons.addWidget(copy_url)

    copy_token = QPushButton("复制 Token")
    copy_token.setObjectName("ghostButton")
    copy_token.setCursor(Qt.CursorShape.PointingHandCursor)
    copy_token.clicked.connect(lambda: _copy_and_flash(copy_token, token))
    buttons.addWidget(copy_token)

    if template is not None:
        copy_json = QPushButton("复制 JSON 示例")
        copy_json.setObjectName("ghostButton")
        copy_json.setCursor(Qt.CursorShape.PointingHandCursor)
        copy_json.clicked.connect(
            lambda: _copy_and_flash(
                copy_json,
                json.dumps(template, ensure_ascii=False, indent=2),
            )
        )
        buttons.addWidget(copy_json)
    buttons.addStretch(1)

    close_button = QPushButton("关闭")
    close_button.setObjectName("primaryButton")
    close_button.clicked.connect(dialog.accept)
    buttons.addWidget(close_button)
    layout.addLayout(buttons)
    dialog.exec()


def _copy_and_flash(button: QPushButton, text: str) -> None:
    from PySide6.QtWidgets import QApplication

    QApplication.clipboard().setText(text)
    original = button.text()
    button.setText("已复制")
    QTimer.singleShot(1200, lambda: button.setText(original))


def _toggle_row(text: str, toggle: ToggleSwitch) -> QHBoxLayout:
    row = QHBoxLayout()
    row.setSpacing(12)
    label = QLabel(text)
    label.setStyleSheet(f"color: {COLORS['text']};")
    row.addWidget(label)
    row.addStretch(1)
    row.addWidget(toggle)
    return row
