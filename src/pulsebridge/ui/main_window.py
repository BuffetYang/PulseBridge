"""主窗口：侧边栏 + 页面栈 + 系统托盘。"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QPushButton,
    QStackedWidget,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from ..bus import IngestBus
from ..config import APP_NAME, APP_VERSION, Config
from ..db import Database
from ..server import ServerController
from ..util import humanize_ago, primary_lan_ip
from .icons import app_icon, brand_pixmap
from .pages import (
    AiPage,
    DashboardPage,
    SettingsPage,
    SyncPage,
    TrendsPage,
    WorkoutsPage,
    export_data,
    open_guide_dialog,
)
from .theme import COLORS

NAV_ITEMS = [
    ("📊", "仪表盘"),
    ("📈", "趋势"),
    ("🏃", "运动记录"),
    ("📡", "同步与配对"),
    ("✨", "AI 洞察"),
    ("⚙️", "设置"),
]


class MainWindow(QMainWindow):
    def __init__(
        self,
        config: Config,
        db: Database,
        controller: ServerController,
        bus: IngestBus,
    ) -> None:
        super().__init__()
        self.config = config
        self.db = db
        self.controller = controller
        self.bus = bus
        self._quitting = False
        self._tray_hint_shown = False

        self.setWindowTitle(f"{APP_NAME} · 健康看板")
        self.setWindowIcon(app_icon())
        self.resize(1260, 840)
        self.setMinimumSize(1040, 680)

        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        root_layout.addWidget(self._build_sidebar())

        self.stack = QStackedWidget()
        root_layout.addWidget(self.stack, 1)

        self.dashboard = DashboardPage(
            db, controller, self._open_guide, lambda: self.navigate(2)
        )
        self.trends = TrendsPage(db)
        self.workouts = WorkoutsPage(db)
        self.sync = SyncPage(db, config, controller, self._open_guide)
        self.ai = AiPage(db, lambda: export_data(self.ai, 30))
        self.settings = SettingsPage(db, config, controller, self.refresh_all)
        self.pages = [
            self.dashboard,
            self.trends,
            self.workouts,
            self.sync,
            self.ai,
            self.settings,
        ]
        for page in self.pages:
            self.stack.addWidget(page)

        self._build_tray()
        self.nav_buttons[0].setChecked(True)
        self.stack.setCurrentIndex(0)

        self.bus.ingested.connect(self._on_ingested)

        self.timer = QTimer(self)
        self.timer.setInterval(15000)
        self.timer.timeout.connect(self._tick)
        self.timer.start()
        self._update_sidebar_status()

    # ------------------------------------------------------------------
    def _build_sidebar(self) -> QFrame:
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(238)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(16, 22, 16, 16)
        layout.setSpacing(6)

        brand_row = QHBoxLayout()
        brand_row.setSpacing(10)
        logo = QLabel()
        logo.setPixmap(brand_pixmap(40))
        logo.setFixedSize(40, 40)
        brand_row.addWidget(logo)
        brand_text = QVBoxLayout()
        brand_text.setSpacing(0)
        name = QLabel(APP_NAME)
        name.setObjectName("brand")
        sub = QLabel("HEALTH DESK")
        sub.setObjectName("brandSub")
        brand_text.addWidget(name)
        brand_text.addWidget(sub)
        brand_row.addLayout(brand_text)
        brand_row.addStretch(1)
        layout.addLayout(brand_row)
        layout.addSpacing(22)

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        self.nav_buttons: list[QPushButton] = []
        for index, (emoji, label) in enumerate(NAV_ITEMS):
            button = QPushButton(f"{emoji}   {label}")
            button.setObjectName("navButton")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _=False, i=index: self.navigate(i))
            self.nav_group.addButton(button, index)
            layout.addWidget(button)
            self.nav_buttons.append(button)

        layout.addStretch(1)

        footer = QFrame()
        footer.setObjectName("softCard")
        footer_layout = QVBoxLayout(footer)
        footer_layout.setContentsMargins(13, 11, 13, 11)
        footer_layout.setSpacing(4)
        self.side_status = QLabel("● 接收服务")
        self.side_status.setTextFormat(Qt.TextFormat.RichText)
        self.side_status.setStyleSheet("font-size: 12px;")
        self.side_last = QLabel("最近同步 --")
        self.side_last.setObjectName("subtle")
        self.side_last.setWordWrap(True)
        footer_layout.addWidget(self.side_status)
        footer_layout.addWidget(self.side_last)
        layout.addWidget(footer)

        version = QLabel(f"v{APP_VERSION} · 本地优先")
        version.setObjectName("subtle")
        version.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(version)
        return sidebar

    # ------------------------------------------------------------------
    def _build_tray(self) -> None:
        self.tray = QSystemTrayIcon(app_icon(), self)
        self.tray.setToolTip(f"{APP_NAME} · 健康数据接收中")

        menu = QMenu()
        open_action = QAction("打开健康看板", self)
        open_action.triggered.connect(self._show_window)
        menu.addAction(open_action)
        sync_action = QAction("同步与配对", self)
        sync_action.triggered.connect(lambda: self._show_page(3))
        menu.addAction(sync_action)
        menu.addSeparator()
        quit_action = QAction("退出", self)
        quit_action.triggered.connect(self._quit)
        menu.addAction(quit_action)

        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self._show_window()

    def _show_page(self, index: int) -> None:
        self.navigate(index)
        self._show_window()

    def _show_window(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _quit(self) -> None:
        self._quitting = True
        self.tray.hide()
        QApplication.quit()

    # ------------------------------------------------------------------
    def navigate(self, index: int) -> None:
        if 0 <= index < len(self.pages):
            self.stack.setCurrentIndex(index)
            if 0 <= index < len(self.nav_buttons):
                self.nav_buttons[index].setChecked(True)
            page = self.pages[index]
            refresh = getattr(page, "refresh", None)
            if callable(refresh):
                refresh()

    def refresh_all(self) -> None:
        for page in self.pages:
            refresh = getattr(page, "refresh", None)
            if callable(refresh):
                refresh()
        self._update_sidebar_status()

    def _tick(self) -> None:
        if self.isVisible():
            page = self.pages[self.stack.currentIndex()]
            refresh = getattr(page, "refresh", None)
            if callable(refresh):
                refresh()
        self._update_sidebar_status()

    def _on_ingested(self, summary: dict[str, Any]) -> None:
        self._update_sidebar_status()
        if self.isVisible():
            page = self.pages[self.stack.currentIndex()]
            refresh = getattr(page, "refresh", None)
            if callable(refresh):
                refresh()
        else:
            total = int(summary.get("samples_new", 0)) + int(
                summary.get("workouts_new", 0)
            )
            if total > 0:
                self.tray.showMessage(
                    APP_NAME,
                    f"已接收 {total} 条新健康数据",
                    QSystemTrayIcon.MessageIcon.Information,
                    2500,
                )

    def _update_sidebar_status(self) -> None:
        if self.controller.running:
            self.side_status.setText(
                f"<span style='color:{COLORS['accent']}'>●</span> 接收服务运行中"
            )
        else:
            self.side_status.setText(
                f"<span style='color:{COLORS['red']}'>●</span> 接收服务未启动"
            )
        stats = self.db.stats()
        port = self.controller.port
        if stats.get("last_sync_ts"):
            self.side_last.setText(
                f"端口 {port} · 最近同步 {humanize_ago(stats['last_sync_ts'])}"
            )
        else:
            self.side_last.setText(
                f"端口 {port} · {primary_lan_ip()} · 等待首次同步"
            )

    # ------------------------------------------------------------------
    def _open_guide(self) -> None:
        from ..util import app_base_url

        open_guide_dialog(self, app_base_url(self.controller.port), self.config.token)

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._quitting or not bool(self.config.get("close_to_tray", True)):
            event.accept()
            return
        event.ignore()
        self.hide()
        if not self._tray_hint_shown:
            self._tray_hint_shown = True
            self.tray.showMessage(
                APP_NAME,
                "程序已最小化到托盘，仍在后台每小时接收 iPhone 数据。",
                QSystemTrayIcon.MessageIcon.Information,
                3000,
            )
