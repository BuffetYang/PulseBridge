from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pulsebridge.bus import IngestBus  # noqa: E402
from pulsebridge.config import Config  # noqa: E402
from pulsebridge.db import Database  # noqa: E402
from pulsebridge.server import ServerController  # noqa: E402


def test_main_window_builds(tmp_path) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    from pulsebridge.ui.main_window import MainWindow
    from pulsebridge.ui.theme import apply_theme

    app = QApplication.instance() or QApplication([])
    apply_theme(app)

    config = Config(tmp_path / "config.json")
    config.set("mdns_enabled", False)
    config.set("onboarding_done", True)
    config.set("update_check_enabled", False)
    db = Database(tmp_path / "test.db")
    controller = ServerController(config, db)
    window = MainWindow(config, db, controller, IngestBus())
    window.resize(1200, 800)
    window.show()
    app.processEvents()

    assert window.stack.count() == 8
    for index in range(8):
        window.navigate(index)
        app.processEvents()

    # 仪表盘指标卡点击 -> 趋势页对应指标
    window.navigate(0)
    app.processEvents()
    QTest.mouseClick(window.dashboard.card_steps, Qt.MouseButton.LeftButton)
    app.processEvents()
    assert window.stack.currentIndex() == 1
    assert window.trends.metric_combo.currentData() == "steps"

    # 图表区域点击也可以跳转
    window.navigate(0)
    app.processEvents()
    QTest.mouseClick(window.dashboard.hr_chart, Qt.MouseButton.LeftButton)
    app.processEvents()
    assert window.stack.currentIndex() == 1
    assert window.trends.metric_combo.currentData() == "heart_rate"

    window.floating.set_enabled(True)
    app.processEvents()
    assert window.floating.ball.isVisible()
    window.floating.set_enabled(False)
    app.processEvents()
    assert not window.floating.ball.isVisible()

    window._quitting = True
    window.close()
    db.close()


def test_onboarding_dialog_builds(tmp_path) -> None:
    from PySide6.QtWidgets import QApplication

    from pulsebridge.config import Config
    from pulsebridge.server import ServerController
    from pulsebridge.ui.onboarding import OnboardingDialog

    app = QApplication.instance() or QApplication([])
    config = Config(tmp_path / "config.json")
    config.set("port", 0)
    db = Database(tmp_path / "test.db")
    controller = ServerController(config, db)
    controller.start()
    try:
        dialog = OnboardingDialog(config, controller)
        assert dialog.address_copy.value().startswith("http://")
        assert dialog.qr_label.text() or dialog.qr_label.pixmap() is not None
        dialog.close()
    finally:
        controller.stop()
        db.close()
        app.processEvents()


def test_ai_model_profiles_keep_keys(tmp_path) -> None:
    from PySide6.QtWidgets import QApplication

    from pulsebridge.ai import (
        DEEPSEEK_BASE_URL,
        DEEPSEEK_MODEL,
        GLM_BASE_URL,
        GLM_MODEL,
    )
    from pulsebridge.ui.pages import _AIModelDialog

    app = QApplication.instance() or QApplication([])
    config = Config(tmp_path / "config.json")
    config.set("ai_provider", "openai")
    config.set("ai_base_url", GLM_BASE_URL)
    config.set("ai_api_key", "glm-key")
    config.set("ai_model", GLM_MODEL)

    dialog = _AIModelDialog(config)
    assert dialog.key_edit.text() == "glm-key"
    dialog._apply_deepseek()
    assert dialog.base_edit.text() == DEEPSEEK_BASE_URL
    assert dialog.key_edit.text() == ""  # DeepSeek 还没有保存过
    dialog.key_edit.setText("deep-key")
    dialog._apply_glm(GLM_MODEL)
    assert dialog.key_edit.text() == "glm-key"
    dialog._apply_deepseek()
    assert dialog.key_edit.text() == "deep-key"
    dialog._save()

    reopened = _AIModelDialog(config)
    reopened._apply_deepseek()
    assert reopened.key_edit.text() == "deep-key"
    assert reopened.model_edit.text() == DEEPSEEK_MODEL
    reopened._apply_glm(GLM_MODEL)
    assert reopened.key_edit.text() == "glm-key"
    app.processEvents()
