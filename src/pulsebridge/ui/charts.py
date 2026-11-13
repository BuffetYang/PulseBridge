"""轻量自绘图表：折线、柱状、迷你图、睡眠阶段条。

不依赖 pyqtgraph / matplotlib，保持打包体积小，并让配色与整体 UI 一致。
"""

from __future__ import annotations

from datetime import datetime
from typing import Iterable, Sequence

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import QWidget

from .theme import COLORS

_AXIS = QColor("#6F8198")
_GRID = QColor("#1E2A38")


def _axis_font(widget: QWidget, size: int = 10, bold: bool = False) -> QFont:
    font = QFont(widget.font())
    font.setPixelSize(size)
    font.setBold(bold)
    return font


def _nice_max(value: float) -> float:
    if value <= 0:
        return 1.0
    import math

    magnitude = 10 ** math.floor(math.log10(value))
    normalized = value / magnitude
    for step in (1.0, 1.2, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0):
        if normalized <= step:
            return step * magnitude
    return 10 * magnitude


def _axis_format(value: float) -> str:
    if abs(value) >= 1000:
        return f"{value:,.0f}"
    if abs(value) >= 100:
        return f"{value:.0f}"
    if abs(value) >= 10:
        return f"{value:.0f}"
    return f"{value:.1f}"


class LineChart(QWidget):
    def __init__(
        self,
        color: str = COLORS["accent"],
        unit: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setMinimumHeight(170)
        self.setMouseTracking(True)
        self._color = QColor(color)
        self._unit = unit
        self._points: list[tuple[float, float]] = []
        self._empty = "暂无数据"
        self._hover: int | None = None
        self._plot = QRectF()
        self._xy: list[QPointF] = []

    def set_empty_text(self, text: str) -> None:
        self._empty = text
        self.update()

    def set_data(
        self, points: Iterable[tuple[float, float]], unit: str | None = None
    ) -> None:
        cleaned: list[tuple[float, float]] = []
        for x, y in points:
            try:
                if y is None:
                    continue
                cleaned.append((float(x), float(y)))
            except (TypeError, ValueError):
                continue
        cleaned.sort(key=lambda item: item[0])
        self._points = self._downsample(cleaned)
        if unit is not None:
            self._unit = unit
        self._hover = None
        self.update()

    @staticmethod
    def _downsample(
        points: Sequence[tuple[float, float]], target: int = 700
    ) -> list[tuple[float, float]]:
        if len(points) <= target:
            return list(points)
        bucket_count = max(1, target // 2)
        step = len(points) / bucket_count
        result: set[tuple[float, float]] = set()
        for index in range(bucket_count):
            chunk = points[int(index * step) : int((index + 1) * step)]
            if not chunk:
                continue
            result.add(min(chunk, key=lambda p: p[1]))
            result.add(max(chunk, key=lambda p: p[1]))
        return sorted(result)

    # -- 绘制 -----------------------------------------------------------
    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        rect = QRectF(self.rect()).adjusted(50, 14, -16, -30)
        self._plot = rect
        self._xy = []

        if not self._points or rect.width() <= 10:
            self._draw_empty(painter)
            return

        xs = [p[0] for p in self._points]
        ys = [p[1] for p in self._points]
        x_min, x_max = min(xs), max(xs)
        if x_max <= x_min:
            x_max = x_min + 1
        y_min, y_max = min(ys), max(ys)
        pad = (y_max - y_min) * 0.14 or (abs(y_max) * 0.1 or 1.0)
        y_min -= pad
        y_max += pad
        if y_max <= y_min:
            y_max = y_min + 1

        # 网格与 Y 轴
        painter.setFont(_axis_font(self, 10))
        painter.setPen(QPen(_GRID, 1, Qt.PenStyle.DashLine))
        for index in range(5):
            y = rect.top() + rect.height() * index / 4
            painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
        painter.setPen(QPen(_AXIS))
        for index in range(5):
            y = rect.top() + rect.height() * index / 4
            value = y_max - (y_max - y_min) * index / 4
            painter.drawText(
                QRectF(0, y - 8, rect.left() - 8, 16),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                _axis_format(value),
            )

        def map_point(x: float, y: float) -> QPointF:
            px = rect.left() + (x - x_min) / (x_max - x_min) * rect.width()
            py = rect.bottom() - (y - y_min) / (y_max - y_min) * rect.height()
            return QPointF(px, py)

        points = [map_point(x, y) for x, y in self._points]
        self._xy = points

        painter.save()
        clip = QPainterPath()
        clip.addRoundedRect(rect.adjusted(-2, -4, 2, 4), 8, 8)
        painter.setClipPath(clip)

        line_path = QPainterPath()
        line_path.moveTo(points[0])
        for index in range(1, len(points) - 1):
            mid = QPointF(
                (points[index].x() + points[index + 1].x()) / 2,
                (points[index].y() + points[index + 1].y()) / 2,
            )
            line_path.quadTo(points[index], mid)
        line_path.lineTo(points[-1])

        fill_path = QPainterPath(line_path)
        fill_path.lineTo(points[-1].x(), rect.bottom())
        fill_path.lineTo(points[0].x(), rect.bottom())
        fill_path.closeSubpath()

        gradient = QLinearGradient(0, rect.top(), 0, rect.bottom())
        top_color = QColor(self._color)
        top_color.setAlpha(90)
        bottom_color = QColor(self._color)
        bottom_color.setAlpha(0)
        gradient.setColorAt(0.0, top_color)
        gradient.setColorAt(1.0, bottom_color)
        painter.fillPath(fill_path, gradient)

        if len(points) == 1:
            painter.setPen(Qt.PenStyle.NoPen)
        painter.setPen(
            QPen(self._color, 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        )
        painter.drawPath(line_path)
        painter.restore()

        # 最后一个点
        last = points[-1]
        glow = QColor(self._color)
        glow.setAlpha(60)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(glow)
        painter.drawEllipse(last, 7, 7)
        painter.setBrush(self._color)
        painter.drawEllipse(last, 3.5, 3.5)

        # X 轴时间标签
        painter.setPen(QPen(_AXIS))
        painter.setFont(_axis_font(self, 10))
        span = x_max - x_min
        for index in range(5):
            fraction = index / 4
            x = rect.left() + rect.width() * fraction
            ts = x_min + span * fraction
            label = self._time_label(ts, span)
            align = Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop
            painter.drawText(QRectF(x - 38, rect.bottom() + 7, 76, 18), align, label)

        # 悬停十字线
        if self._hover is not None and 0 <= self._hover < len(points):
            hover_point = points[self._hover]
            pen = QPen(QColor("#3A4C60"), 1, Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.drawLine(
                QPointF(hover_point.x(), rect.top()),
                QPointF(hover_point.x(), rect.bottom()),
            )
            painter.setPen(QPen(QColor(COLORS["surface"]), 2))
            painter.setBrush(self._color)
            painter.drawEllipse(hover_point, 4.5, 4.5)
            self._draw_tooltip(painter, hover_point)

    @staticmethod
    def _time_label(ts: float, span: float) -> str:
        try:
            dt = datetime.fromtimestamp(ts)
        except (OverflowError, OSError, ValueError):
            return ""
        if span <= 36 * 3600:
            return dt.strftime("%H:%M")
        if span <= 10 * 86400:
            return f"{dt.month}/{dt.day}"
        return f"{dt.month}/{dt.day}"

    def _draw_tooltip(self, painter: QPainter, point: QPointF) -> None:
        if self._hover is None:
            return
        ts, value = self._points[self._hover]
        time_text = datetime.fromtimestamp(ts).strftime("%m月%d日 %H:%M")
        value_text = f"{_axis_format(value)} {self._unit}".strip()
        painter.setFont(_axis_font(self, 11, bold=True))
        text_width = max(
            painter.fontMetrics().horizontalAdvance(time_text),
            painter.fontMetrics().horizontalAdvance(value_text),
        )
        width = text_width + 22
        height = 46
        x = min(max(point.x() - width / 2, self._plot.left()), self._plot.right() - width)
        y = point.y() - height - 12
        if y < 2:
            y = point.y() + 14
        box = QRectF(x, y, width, height)
        painter.setPen(QPen(QColor("#2A3A4D"), 1))
        painter.setBrush(QColor("#182333"))
        painter.drawRoundedRect(box, 9, 9)
        painter.setPen(QPen(QColor(COLORS["muted"])))
        painter.setFont(_axis_font(self, 10))
        painter.drawText(
            box.adjusted(11, 6, -11, -24),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            time_text,
        )
        painter.setPen(QPen(QColor(COLORS["text"])))
        painter.setFont(_axis_font(self, 12, bold=True))
        painter.drawText(
            box.adjusted(11, 22, -11, -5),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            value_text,
        )

    def _draw_empty(self, painter: QPainter) -> None:
        rect = QRectF(self.rect()).adjusted(18, 14, -18, -14)
        pen = QPen(QColor("#223140"), 1, Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(rect, 14, 14)
        painter.setPen(QPen(QColor(COLORS["subtle"])))
        painter.setFont(_axis_font(self, 12))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, self._empty)

    # -- 交互 -----------------------------------------------------------
    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if not self._xy:
            return
        x = event.position().x()
        nearest = min(range(len(self._xy)), key=lambda i: abs(self._xy[i].x() - x))
        if abs(self._xy[nearest].x() - x) < 24:
            if nearest != self._hover:
                self._hover = nearest
                self.update()
        elif self._hover is not None:
            self._hover = None
            self.update()

    def leaveEvent(self, event) -> None:  # noqa: N802
        if self._hover is not None:
            self._hover = None
            self.update()


class BarChart(QWidget):
    def __init__(
        self,
        color: str = COLORS["accent"],
        unit: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setMinimumHeight(150)
        self._color = QColor(color)
        self._unit = unit
        self._labels: list[str] = []
        self._values: list[float | None] = []
        self._empty = "暂无数据"
        self._hover: int | None = None
        self.setMouseTracking(True)

    def set_empty_text(self, text: str) -> None:
        self._empty = text
        self.update()

    def set_data(
        self,
        labels: Sequence[str],
        values: Sequence[float | None],
        unit: str | None = None,
    ) -> None:
        self._labels = list(labels)
        self._values = list(values)
        if unit is not None:
            self._unit = unit
        self._hover = None
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        valid = [v for v in self._values if v is not None]
        if not valid:
            LineChart._draw_empty(self, painter)  # type: ignore[arg-type]
            return

        rect = QRectF(self.rect()).adjusted(44, 22, -14, -30)
        y_max = _nice_max(max(valid) * 1.08)
        y_min = 0.0

        painter.setFont(_axis_font(self, 10))
        painter.setPen(QPen(_GRID, 1, Qt.PenStyle.DashLine))
        for index in range(4):
            y = rect.top() + rect.height() * index / 3
            painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
        painter.setPen(QPen(_AXIS))
        for index in range(4):
            y = rect.top() + rect.height() * index / 3
            value = y_max - (y_max - y_min) * index / 3
            painter.drawText(
                QRectF(0, y - 8, rect.left() - 8, 16),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                _axis_format(value),
            )

        count = max(1, len(self._values))
        slot = rect.width() / count
        bar_width = min(46.0, max(10.0, slot * 0.5))
        chart_font = _axis_font(self, 10)

        for index, value in enumerate(self._values):
            center_x = rect.left() + slot * (index + 0.5)
            if value is None:
                continue
            height = (max(0.0, value) / y_max) * rect.height()
            top = rect.bottom() - height
            bar_rect = QRectF(center_x - bar_width / 2, top, bar_width, height)
            path = QPainterPath()
            radius = min(7.0, bar_width / 2, max(2.0, height))
            path.addRoundedRect(bar_rect, radius, radius)

            is_last = index == len(self._values) - 1
            color = QColor(self._color)
            if not is_last:
                color.setAlpha(110 if not self._hover == index else 180)
            if self._hover == index:
                color = QColor(self._color)
            gradient = QLinearGradient(0, top, 0, rect.bottom())
            gradient.setColorAt(0.0, color)
            faded = QColor(color)
            faded.setAlpha(max(45, color.alpha() // 2))
            gradient.setColorAt(1.0, faded)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(gradient)
            painter.drawPath(path)

            if slot >= 34:
                painter.setPen(QPen(QColor(COLORS["muted"] if not is_last else COLORS["text"])))
                painter.setFont(_axis_font(self, 10, bold=is_last))
                label = _axis_format(value)
                painter.drawText(
                    QRectF(center_x - slot / 2, top - 17, slot, 15),
                    Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom,
                    label,
                )

            painter.setPen(
                QPen(QColor(COLORS["muted"] if not is_last else COLORS["text"]))
            )
            painter.setFont(chart_font)
            if index < len(self._labels):
                painter.drawText(
                    QRectF(center_x - slot / 2, rect.bottom() + 6, slot, 18),
                    Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                    self._labels[index],
                )

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if not self._values:
            return
        rect = QRectF(self.rect()).adjusted(44, 22, -14, -30)
        if rect.width() <= 0:
            return
        slot = rect.width() / max(1, len(self._values))
        index = int((event.position().x() - rect.left()) // slot)
        index = max(0, min(len(self._values) - 1, index))
        if self._hover != index:
            self._hover = index
            value = self._values[index]
            if value is not None and index < len(self._labels):
                self.setToolTip(f"{self._labels[index]}：{_axis_format(value)} {self._unit}")
            else:
                self.setToolTip("")
            self.update()

    def leaveEvent(self, event) -> None:  # noqa: N802
        if self._hover is not None:
            self._hover = None
            self.setToolTip("")
            self.update()


class Sparkline(QWidget):
    """指标卡底部的迷你柱状图。"""

    def __init__(
        self, color: str = COLORS["accent"], parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setFixedHeight(34)
        self._color = QColor(color)
        self._values: list[float | None] = []

    def set_values(self, values: Sequence[float | None]) -> None:
        self._values = list(values[-14:])
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        values = [v for v in self._values if v is not None]
        if not values:
            painter = QPainter(self)
            painter.setPen(QPen(QColor("#223140"), 1, Qt.PenStyle.DashLine))
            painter.drawLine(2, self.height() - 6, self.width() - 2, self.height() - 6)
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(0, 2, 0, 0)
        maximum = max(values) or 1.0
        count = len(self._values)
        slot = rect.width() / max(1, count)
        bar_width = min(10.0, max(4.0, slot * 0.45))
        for index, value in enumerate(self._values):
            if value is None:
                continue
            height = max(2.0, (max(0.0, value) / maximum) * (rect.height() - 3))
            x = rect.left() + slot * (index + 0.5) - bar_width / 2
            bar = QRectF(x, rect.bottom() - height, bar_width, height)
            color = QColor(self._color)
            color.setAlpha(255 if index == count - 1 else 70)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            painter.drawRoundedRect(bar, min(3.0, bar_width / 2), min(3.0, bar_width / 2))


class StageBar(QWidget):
    """睡眠阶段堆叠条。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(14)
        self._segments: list[tuple[float, QColor]] = []

    def set_segments(self, segments: Iterable[tuple[float, str]]) -> None:
        self._segments = [
            (max(0.0, float(minutes)), QColor(color))
            for minutes, color in segments
            if minutes and minutes > 0
        ]
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        total = sum(minutes for minutes, _ in self._segments)
        rect = QRectF(self.rect()).adjusted(0, 2, 0, -2)
        if total <= 0:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#1B2735"))
            painter.drawRoundedRect(rect, 5, 5)
            return
        x = rect.left()
        gap = 2.0
        for index, (minutes, color) in enumerate(self._segments):
            width = rect.width() * minutes / total
            width = max(0.0, width - (gap if index < len(self._segments) - 1 else 0))
            if width <= 0:
                continue
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            painter.drawRoundedRect(QRectF(x, rect.top(), width, rect.height()), 5, 5)
            x += width + gap


class RingMetric(QWidget):
    """单个活动圆环：Move / Exercise / Stand。"""

    def __init__(
        self,
        label: str,
        unit: str,
        color: str,
        digits: int = 0,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.label = label
        self.unit = unit
        self.digits = digits
        self._color = QColor(color)
        self._value = 0.0
        self._goal = 0.0
        self._estimated = False
        self.setMinimumSize(120, 150)

    def set_data(
        self, value: float | None, goal: float | None, estimated: bool = False
    ) -> None:
        self._value = max(0.0, float(value or 0))
        self._goal = max(0.0, float(goal or 0))
        self._estimated = bool(estimated)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        diameter = 76.0
        center_x = self.width() / 2
        ring = QRectF(center_x - diameter / 2, 8, diameter, diameter)

        painter.setPen(
            QPen(QColor("#223140"), 9, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        )
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawArc(ring, 90 * 16, -360 * 16)

        progress = min(1.0, self._value / self._goal) if self._goal > 0 else 0.0
        if progress > 0:
            painter.setPen(
                QPen(
                    self._color,
                    9,
                    Qt.PenStyle.SolidLine,
                    Qt.PenCapStyle.RoundCap,
                )
            )
            painter.drawArc(ring, 90 * 16, int(-360 * 16 * progress))

        painter.setPen(QPen(QColor(COLORS["text"])))
        painter.setFont(_axis_font(self, 15, bold=True))
        percent = f"{progress * 100:.0f}%" if self._goal > 0 else "--"
        if self._estimated:
            percent = "≈" + percent
        painter.drawText(ring, Qt.AlignmentFlag.AlignCenter, percent)

        painter.setPen(QPen(QColor(COLORS["muted"])))
        painter.setFont(_axis_font(self, 11))
        painter.drawText(
            QRectF(0, ring.bottom() + 8, self.width(), 18),
            Qt.AlignmentFlag.AlignCenter,
            self.label,
        )
        value_text = f"{self._value:.{self.digits}f}"
        goal_text = f"{self._goal:.{self.digits}f}"
        prefix = "≈ " if self._estimated else ""
        painter.setPen(QPen(QColor(COLORS["text"])))
        painter.setFont(_axis_font(self, 11, bold=True))
        painter.drawText(
            QRectF(0, ring.bottom() + 26, self.width(), 18),
            Qt.AlignmentFlag.AlignCenter,
            f"{prefix}{value_text} / {goal_text} {self.unit}".strip(),
        )


class Hypnogram(QWidget):
    """睡眠阶段时间轴。"""

    _ROWS = (
        ("awake", "清醒", "#FFB347"),
        ("rem", "REM", "#4CC9F0"),
        ("core", "核心", "#B18CFF"),
        ("deep", "深睡", "#5B9DFF"),
    )

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(210)
        self._segments: list[tuple[int, int, str]] = []
        self._start = 0
        self._end = 0

    def set_data(
        self, segments: Iterable[tuple[int, int, str]], start_ts: int, end_ts: int
    ) -> None:
        self._segments = list(segments)
        self._start = start_ts
        self._end = end_ts
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if not self._segments or self._end <= self._start:
            painter.setPen(QPen(QColor(COLORS["subtle"])))
            painter.setFont(_axis_font(self, 12))
            painter.drawText(
                self.rect(), Qt.AlignmentFlag.AlignCenter, "最近一夜没有睡眠阶段数据"
            )
            return

        rect = QRectF(self.rect()).adjusted(52, 16, -14, -30)
        row_names = [row[0] for row in self._ROWS]
        row_height = rect.height() / len(self._ROWS)

        painter.setFont(_axis_font(self, 10))
        for index, (stage, label, color) in enumerate(self._ROWS):
            y = rect.top() + row_height * index
            painter.setPen(QPen(_GRID, 1, Qt.PenStyle.DashLine))
            painter.drawLine(QPointF(rect.left(), y + row_height / 2),
                             QPointF(rect.right(), y + row_height / 2))
            painter.setPen(QPen(QColor(COLORS["muted"])))
            painter.drawText(
                QRectF(0, y, rect.left() - 8, row_height),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                label,
            )

        span = self._end - self._start
        for start, end, stage in self._segments:
            if stage == "in_bed":
                continue
            row_stage = "core" if stage in ("asleep_unspecified", "light") else stage
            if row_stage not in row_names:
                continue
            row_index = row_names.index(row_stage)
            x1 = rect.left() + (start - self._start) / span * rect.width()
            x2 = rect.left() + (end - self._start) / span * rect.width()
            width = max(1.5, x2 - x1 - 1)
            y = rect.top() + row_height * row_index + row_height / 2 - 5
            color = QColor(dict((row[0], row[2]) for row in self._ROWS)[row_stage])
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            painter.drawRoundedRect(QRectF(x1, y, width, 10), 4, 4)

        painter.setPen(QPen(_AXIS))
        painter.setFont(_axis_font(self, 10))
        for index in range(5):
            fraction = index / 4
            ts = self._start + span * fraction
            x = rect.left() + rect.width() * fraction
            label = datetime.fromtimestamp(ts).strftime("%H:%M")
            painter.drawText(
                QRectF(x - 30, rect.bottom() + 7, 60, 18),
                Qt.AlignmentFlag.AlignHCenter,
                label,
            )


class SleepStagesChart(QWidget):
    """多夜睡眠阶段堆叠柱。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(230)
        self._nights: list[dict] = []

    def set_data(self, nights: Iterable[dict]) -> None:
        self._nights = list(nights)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if not self._nights:
            painter.setPen(QPen(QColor(COLORS["subtle"])))
            painter.setFont(_axis_font(self, 12))
            painter.drawText(
                self.rect(), Qt.AlignmentFlag.AlignCenter, "这段时间没有睡眠数据"
            )
            return

        rect = QRectF(self.rect()).adjusted(44, 16, -14, -30)
        max_hours = max(
            (n["deep_min"] + n["core_min"] + n["rem_min"] + n["awake_min"]) / 60
            for n in self._nights
        )
        max_hours = max(1.0, max_hours * 1.1)
        painter.setFont(_axis_font(self, 10))
        for index in range(4):
            y = rect.top() + rect.height() * index / 3
            painter.setPen(QPen(_GRID, 1, Qt.PenStyle.DashLine))
            painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
            painter.setPen(QPen(_AXIS))
            painter.drawText(
                QRectF(0, y - 8, rect.left() - 8, 16),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                f"{max_hours * (1 - index / 3):.0f}",
            )

        slot = rect.width() / max(1, len(self._nights))
        bar_width = min(30.0, max(6.0, slot * 0.55))
        stages = (
            ("deep_min", "#5B9DFF"),
            ("core_min", "#B18CFF"),
            ("rem_min", "#4CC9F0"),
            ("awake_min", "#FFB347"),
        )
        for index, night in enumerate(self._nights):
            x = rect.left() + slot * (index + 0.5) - bar_width / 2
            bottom = rect.bottom()
            for key, color in stages:
                hours = (night.get(key) or 0) / 60
                height = hours / max_hours * rect.height()
                if height <= 0:
                    continue
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(color))
                painter.drawRect(QRectF(x, bottom - height, bar_width, height))
                bottom -= height
            if len(self._nights) <= 14 or index % max(1, len(self._nights) // 8) == 0:
                painter.setPen(QPen(QColor(COLORS["muted"])))
                painter.setFont(_axis_font(self, 10))
                date_text = night["date"][5:].replace("-", "/")
                painter.drawText(
                    QRectF(x + bar_width / 2 - 24, rect.bottom() + 6, 48, 18),
                    Qt.AlignmentFlag.AlignHCenter,
                    date_text,
                )
