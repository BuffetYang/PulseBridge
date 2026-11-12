"""可复用的 UI 组件。"""

from __future__ import annotations


from PySide6.QtCore import QRectF, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .charts import Sparkline
from .theme import COLORS


def card_header(title: str, subtitle: str | None = None, right: QWidget | None = None) -> QHBoxLayout:
    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(8)
    left = QVBoxLayout()
    left.setContentsMargins(0, 0, 0, 0)
    left.setSpacing(2)
    title_label = QLabel(title)
    title_label.setObjectName("cardTitle")
    left.addWidget(title_label)
    if subtitle:
        sub_label = QLabel(subtitle)
        sub_label.setObjectName("cardSub")
        left.addWidget(sub_label)
    row.addLayout(left)
    row.addStretch(1)
    if right is not None:
        row.addWidget(right, 0, Qt.AlignmentFlag.AlignTop)
    return row


class Card(QFrame):
    def __init__(self, parent: QWidget | None = None, margins: tuple[int, int, int, int] = (20, 18, 20, 18)) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(*margins)
        self.body.setSpacing(12)


class MetricCard(QFrame):
    def __init__(
        self,
        emoji: str,
        title: str,
        color: str,
        unit: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        self.setMinimumHeight(156)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 15, 18, 13)
        layout.setSpacing(6)

        top = QHBoxLayout()
        top.setSpacing(7)
        icon = QLabel(emoji)
        icon.setStyleSheet("font-size: 15px;")
        top.addWidget(icon)
        label = QLabel(title)
        label.setObjectName("metricLabel")
        top.addWidget(label)
        top.addStretch(1)
        self.badge = QLabel("")
        self.badge.setObjectName("chip")
        self.badge.hide()
        top.addWidget(self.badge)
        layout.addLayout(top)

        value_row = QHBoxLayout()
        value_row.setSpacing(6)
        self.value = QLabel("--")
        self.value.setObjectName("metricValue")
        value_row.addWidget(self.value, 0, Qt.AlignmentFlag.AlignBaseline)
        self.unit = QLabel(unit)
        self.unit.setObjectName("metricUnit")
        value_row.addWidget(self.unit, 0, Qt.AlignmentFlag.AlignBaseline)
        value_row.addStretch(1)
        layout.addLayout(value_row)

        self.sub = QLabel("等待同步")
        self.sub.setObjectName("metricSub")
        self.sub.setWordWrap(True)
        layout.addWidget(self.sub)

        self.spark = Sparkline(color)
        layout.addWidget(self.spark)
        layout.addStretch(1)

    def set_value(
        self,
        value: str,
        unit: str | None = None,
        sub: str | None = None,
        spark: list[float | None] | None = None,
        badge: str | None = None,
    ) -> None:
        self.value.setText(value)
        if unit is not None:
            self.unit.setText(unit)
        if sub is not None:
            self.sub.setText(sub)
        if spark is not None:
            self.spark.set_values(spark)
        if badge is not None:
            if badge:
                self.badge.setText(badge)
                self.badge.show()
            else:
                self.badge.hide()


class StatusPill(QLabel):
    def set_state(self, state: str, text: str) -> None:
        name = {"good": "pillGood", "warn": "pillWarn", "bad": "pillBad"}.get(
            state, "pillWarn"
        )
        self.setObjectName(name)
        self.setText(text)
        self.style().unpolish(self)
        self.style().polish(self)


class CopyRow(QWidget):
    """一行可复制的值，支持隐藏敏感内容。"""

    def __init__(
        self,
        title: str,
        value: str = "",
        secret: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._value = value
        self._secret = secret
        self._revealed = not secret

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)

        top = QHBoxLayout()
        top.setSpacing(8)
        title_label = QLabel(title)
        title_label.setObjectName("subtle")
        top.addWidget(title_label)
        top.addStretch(1)

        if secret:
            self.reveal_button = QPushButton("显示")
            self.reveal_button.setObjectName("linkButton")
            self.reveal_button.setCursor(Qt.CursorShape.PointingHandCursor)
            self.reveal_button.clicked.connect(self._toggle_reveal)
            top.addWidget(self.reveal_button)

        self.copy_button = QPushButton("复制")
        self.copy_button.setObjectName("iconButton")
        self.copy_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.copy_button.clicked.connect(self._copy)
        top.addWidget(self.copy_button)
        layout.addLayout(top)

        self.value_label = QLabel()
        self.value_label.setObjectName("mono")
        self.value_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.value_label.setWordWrap(True)
        layout.addWidget(self.value_label)
        self._render()

    def set_value(self, value: str) -> None:
        self._value = value
        self._render()

    def value(self) -> str:
        return self._value

    def _render(self) -> None:
        if not self._value:
            self.value_label.setText("--")
        elif self._secret and not self._revealed:
            visible = 4
            self.value_label.setText(
                self._value[:visible] + "•" * max(6, len(self._value) - visible * 2) + self._value[-visible:]
            )
        else:
            self.value_label.setText(self._value)

    def _toggle_reveal(self) -> None:
        self._revealed = not self._revealed
        self.reveal_button.setText("隐藏" if self._revealed else "显示")
        self._render()

    def _copy(self) -> None:
        QApplication.clipboard().setText(self._value)
        self.copy_button.setText("已复制")
        QTimer.singleShot(1200, lambda: self.copy_button.setText("复制"))


class ToggleSwitch(QWidget):
    """深色主题下的开关控件，替代默认 QCheckBox。"""

    toggled = Signal(bool)

    def __init__(self, checked: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._checked = checked
        self.setFixedSize(46, 26)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, checked: bool, emit: bool = False) -> None:
        checked = bool(checked)
        if checked != self._checked:
            self._checked = checked
            self.update()
            if emit:
                self.toggled.emit(checked)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(
            event.position().toPoint()
        ):
            self.setChecked(not self._checked, emit=True)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        track = QRectF(1, 4, self.width() - 2, self.height() - 8)
        if self._checked:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(COLORS["accent"]))
        else:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#263545"))
        painter.drawRoundedRect(track, track.height() / 2, track.height() / 2)

        knob_size = 16.0
        knob_x = (
            track.right() - knob_size - 3
            if self._checked
            else track.left() + 3
        )
        knob = QRectF(knob_x, track.center().y() - knob_size / 2, knob_size, knob_size)
        painter.setBrush(QColor("#F4F8FC" if not self._checked else "#062016"))
        painter.drawEllipse(knob)


class EmptyState(QWidget):
    def __init__(
        self,
        emoji: str,
        title: str,
        subtitle: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 26, 12, 26)
        layout.setSpacing(8)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        icon = QLabel(emoji)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setStyleSheet("font-size: 30px;")
        layout.addWidget(icon)

        title_label = QLabel(title)
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_label.setStyleSheet(f"color: {COLORS['text']}; font-size: 14px; font-weight: 600;")
        layout.addWidget(title_label)

        if subtitle:
            sub = QLabel(subtitle)
            sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
            sub.setWordWrap(True)
            sub.setObjectName("subtle")
            layout.addWidget(sub)


class Divider(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(1)
        self.setStyleSheet(f"background: {COLORS['border_soft']};")


def value_pair(value: str, unit: str = "", color: str | None = None) -> QLabel:
    label = QLabel(f"{value} <span style='color:{COLORS['subtle']};font-size:11px'>{unit}</span>")
    if color:
        label.setStyleSheet(f"color:{color}; font-size:13px;")
    label.setTextFormat(Qt.TextFormat.RichText)
    return label


def bold_font(size: int, weight: int = 600) -> QFont:
    font = QFont()
    font.setPixelSize(size)
    font.setWeight(QFont.Weight(weight))
    return font
