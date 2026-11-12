"""桌面应用入口。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import APP_NAME, APP_VERSION, Config, app_data_dir
from .db import Database


def _set_windows_app_id() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "PulseBridge.Desktop.1"
        )
    except Exception:
        pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pulsebridge", description="PulseBridge 健康看板")
    parser.add_argument("--minimized", action="store_true", help="启动后直接进入托盘")
    parser.add_argument("--data-dir", type=Path, default=None, help="覆盖数据目录")
    parser.add_argument("--port", type=int, default=None, help="覆盖接收端口")
    parser.add_argument("--version", action="version", version=f"PulseBridge {APP_VERSION}")
    args, qt_args = parser.parse_known_args(argv)

    # 延迟导入 Qt，保证核心模块可以在无界面环境下测试
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QApplication

    from .bus import IngestBus
    from .server import ServerController
    from .ui.icons import app_icon
    from .ui.main_window import MainWindow
    from .ui.theme import apply_theme

    _set_windows_app_id()

    app = QApplication([sys.argv[0], *qt_args])
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setOrganizationName("PulseBridge")
    app.setWindowIcon(app_icon())
    app.setFont(QFont("Microsoft YaHei UI", 10))
    apply_theme(app)

    if args.data_dir is not None:
        data_dir = Path(args.data_dir)
        data_dir.mkdir(parents=True, exist_ok=True)
        config = Config(data_dir / "config.json")
    else:
        config = Config()
        data_dir = app_data_dir()

    if args.port:
        config.set("port", args.port)

    db = Database(data_dir / "pulsebridge.db")
    retention = int(config.get("retention_days", 0) or 0)
    if retention > 0:
        db.purge_older_than(retention)

    bus = IngestBus()
    controller = ServerController(config, db, bus.ingested.emit)
    controller.start()

    window = MainWindow(config, db, controller, bus)
    if args.minimized or bool(config.get("start_minimized")):
        window.hide()
    else:
        window.show()

    def _shutdown() -> None:
        controller.stop()
        db.close()

    app.aboutToQuit.connect(_shutdown)
    return app.exec()
