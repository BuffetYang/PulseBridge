"""程序图标：用 QPainter 画一个渐变心跳标志，避免额外的图片资源。"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QIcon,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)


def brand_pixmap(size: int = 64) -> QPixmap:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    rect = QRectF(size * 0.04, size * 0.04, size * 0.92, size * 0.92)
    gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
    gradient.setColorAt(0.0, QColor("#3DDC97"))
    gradient.setColorAt(0.55, QColor("#2FD3B4"))
    gradient.setColorAt(1.0, QColor("#27B4D8"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(gradient)
    painter.drawRoundedRect(rect, size * 0.28, size * 0.28)

    # 心跳折线
    path = QPainterPath()
    points = [
        (0.18, 0.53),
        (0.32, 0.53),
        (0.40, 0.33),
        (0.50, 0.71),
        (0.59, 0.47),
        (0.66, 0.53),
        (0.82, 0.53),
    ]
    path.moveTo(QPointF(points[0][0] * size, points[0][1] * size))
    for px, py in points[1:]:
        path.lineTo(QPointF(px * size, py * size))
    pen = QPen(QColor("#05241A"), max(2.0, size * 0.058))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawPath(path)
    painter.end()
    return pixmap


def app_icon() -> QIcon:
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(brand_pixmap(size))
    return icon
