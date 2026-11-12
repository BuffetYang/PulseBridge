from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pulsebridge.bus import IngestBus  # noqa: E402
from pulsebridge.config import Config  # noqa: E402
from pulsebridge.db import Database  # noqa: E402
from pulsebridge.server import ServerController  # noqa: E402


def test_main_window_builds(tmp_path) -> None:
    from PySide6.QtWidgets import QApplication

    from pulsebridge.ui.main_window import MainWindow
    from pulsebridge.ui.theme import apply_theme

    app = QApplication.instance() or QApplication([])
    apply_theme(app)

    config = Config(tmp_path / "config.json")
    db = Database(tmp_path / "test.db")
    controller = ServerController(config, db)
    window = MainWindow(config, db, controller, IngestBus())
    window.resize(1200, 800)
    window.show()
    app.processEvents()

    assert window.stack.count() == 6
    for index in range(6):
        window.navigate(index)
        app.processEvents()

    window._quitting = True
    window.close()
    db.close()
