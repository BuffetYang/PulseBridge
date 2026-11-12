"""跨线程事件总线：服务线程收到数据后通知 UI 线程。"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal


class IngestBus(QObject):
    ingested = Signal(dict)
