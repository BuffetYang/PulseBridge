"""首次启动向导：防火墙、连接 iPhone、导入历史数据。"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..config import Config
from ..discovery import stable_url
from ..firewall import add_firewall_rule_elevated
from ..server import ServerController
from ..util import app_base_url, primary_lan_ip, puls_pairing_link
from .theme import COLORS
from .widgets import Card, CopyRow


def _qr_pixmap(text: str, size: int = 210) -> QPixmap | None:
    try:
        import io

        import segno

        qr = segno.make(text, error="m")
        buffer = io.BytesIO()
        qr.save(
            buffer,
            kind="png",
            scale=8,
            border=2,
            dark="#0A0E14",
            light="#FFFFFF",
        )
        pixmap = QPixmap()
        if not pixmap.loadFromData(buffer.getvalue()):
            return None
        return pixmap.scaled(
            QSize(size, size),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
    except Exception:  # noqa: BLE001
        return None


class OnboardingDialog(QDialog):
    def __init__(
        self,
        config: Config,
        controller: ServerController,
        on_open_settings: Callable[[], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.config = config
        self.controller = controller
        self.on_open_settings = on_open_settings
        self.setWindowTitle("PulseBridge 首次设置")
        self.setMinimumSize(620, 720)
        self.setModal(True)
        self.setStyleSheet("QDialog { background-color: #0A0E14; }")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        content.setObjectName("onboardingContent")
        content.setStyleSheet(
            "#onboardingContent { background-color: #0A0E14; }"
        )
        layout = QVBoxLayout(content)
        layout.setContentsMargins(24, 22, 24, 18)
        layout.setSpacing(14)
        scroll.setWidget(content)
        outer.addWidget(scroll, 1)

        title = QLabel("欢迎使用 PulseBridge")
        title.setStyleSheet(
            "font-size: 24px; font-weight: 700; color: #EAF0F7;"
        )
        layout.addWidget(title)
        intro = QLabel(
            "三步把 iPhone 健康数据接入这台电脑。设置随时可以在「设置」里重新查看。"
        )
        intro.setObjectName("subtle")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        # 1. 防火墙
        firewall_card = Card()
        firewall_card.body.addLayout(
            self._step_header("① 放行防火墙", "Windows 常把 Wi-Fi 识别为公用网络，默认拦截手机。")
        )
        firewall_row = QHBoxLayout()
        self.firewall_button = QPushButton("修复防火墙")
        self.firewall_button.setObjectName("primaryButton")
        self.firewall_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.firewall_button.clicked.connect(self._fix_firewall)
        firewall_row.addWidget(self.firewall_button)
        self.firewall_status = QLabel("需要管理员权限，会弹出 UAC。")
        self.firewall_status.setObjectName("subtle")
        self.firewall_status.setWordWrap(True)
        firewall_row.addWidget(self.firewall_status, 1)
        firewall_card.body.addLayout(firewall_row)
        layout.addWidget(firewall_card)

        # 2. 连接 iPhone
        phone_card = Card()
        phone_card.body.addLayout(
            self._step_header(
                "② 连接 iPhone",
                "安装免费的 PulsHealth，扫描下面的配对二维码。",
            )
        )
        steps = QLabel(
            "1. App Store 搜索并安装 PulsHealth（iOS 17+）\n"
            "2. 打开 Sync → Database → Scan Pairing Code\n"
            "3. 扫描下面的二维码，点 Add Database\n"
            "4. 选择 5 类数据并允许健康权限"
        )
        steps.setWordWrap(True)
        steps.setStyleSheet(f"color: {COLORS['muted']}; line-height: 1.7;")
        phone_card.body.addWidget(steps)

        address_row = QHBoxLayout()
        address_label = QLabel("配对地址")
        address_label.setObjectName("subtle")
        address_row.addWidget(address_label)
        self.address_combo = QComboBox()
        self.address_combo.addItem("固定地址（mDNS，换 Wi-Fi 也不用改）", "fixed")
        self.address_combo.addItem("局域网地址（如果固定地址打不开）", "ip")
        self.address_combo.currentIndexChanged.connect(self._refresh_qr)
        address_row.addWidget(self.address_combo, 1)
        phone_card.body.addLayout(address_row)

        self.qr_label = QLabel()
        self.qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.qr_label.setMinimumHeight(220)
        phone_card.body.addWidget(self.qr_label)

        self.address_copy = CopyRow("当前配对地址", "")
        phone_card.body.addWidget(self.address_copy)
        hint = QLabel(
            "固定地址依赖 mDNS；如果手机提示无法连接，请改用「局域网地址」再扫一次。"
        )
        hint.setObjectName("subtle")
        hint.setWordWrap(True)
        phone_card.body.addWidget(hint)
        layout.addWidget(phone_card)

        # 3. 导入历史
        import_card = Card()
        import_card.body.addLayout(
            self._step_header(
                "③ 导入历史数据（可选）",
                "PulsHealth 免费版只有 5 类 / 30 天，可以导入 Apple 导出的 zip 补齐历史。",
            )
        )
        import_row = QHBoxLayout()
        import_button = QPushButton("打开导入设置")
        import_button.setObjectName("ghostButton")
        import_button.setCursor(Qt.CursorShape.PointingHandCursor)
        import_button.clicked.connect(self._open_settings)
        import_row.addWidget(import_button)
        import_hint = QLabel("也可以稍后在「设置 → Apple Health 导出导入」里操作。")
        import_hint.setObjectName("subtle")
        import_hint.setWordWrap(True)
        import_row.addWidget(import_hint, 1)
        import_card.body.addLayout(import_row)
        layout.addWidget(import_card)
        layout.addStretch(1)

        footer = QHBoxLayout()
        footer.addStretch(1)
        skip_button = QPushButton("跳过")
        skip_button.setObjectName("ghostButton")
        skip_button.setCursor(Qt.CursorShape.PointingHandCursor)
        skip_button.clicked.connect(self.reject)
        footer.addWidget(skip_button)
        finish_button = QPushButton("开始使用")
        finish_button.setObjectName("primaryButton")
        finish_button.setCursor(Qt.CursorShape.PointingHandCursor)
        finish_button.clicked.connect(self.accept)
        footer.addWidget(finish_button)
        outer.addLayout(footer)

        self._refresh_qr()

    @staticmethod
    def _step_header(title: str, subtitle: str) -> QVBoxLayout:
        layout = QVBoxLayout()
        layout.setSpacing(2)
        title_label = QLabel(title)
        title_label.setObjectName("cardTitle")
        layout.addWidget(title_label)
        sub = QLabel(subtitle)
        sub.setObjectName("cardSub")
        sub.setWordWrap(True)
        layout.addWidget(sub)
        return layout

    def _base_url(self) -> str:
        if self.address_combo.currentData() == "fixed":
            return stable_url(self.config, self.controller.port)
        return app_base_url(
            self.controller.port,
            str(self.config.get("lan_ip") or primary_lan_ip()),
        )

    def _refresh_qr(self, _index: int = 0) -> None:
        base = self._base_url()
        self.address_copy.set_value(base)
        pixmap = _qr_pixmap(puls_pairing_link(base, self.config.token))
        if pixmap is None:
            self.qr_label.setText("无法生成二维码，请到「同步与配对」页查看")
        else:
            self.qr_label.setPixmap(pixmap)

    def _fix_firewall(self) -> None:
        launched, error = add_firewall_rule_elevated(self.controller.port)
        if launched:
            self.firewall_status.setText(
                "已发起修复。请在 UAC 弹窗点「是」，完成后继续下一步。"
            )
            self.firewall_status.setStyleSheet(f"color: {COLORS['accent']};")
        else:
            self.firewall_status.setText(f"未能修复：{error}")
            self.firewall_status.setStyleSheet(f"color: {COLORS['red']};")
            QMessageBox.warning(self, "防火墙", error)

    def _open_settings(self) -> None:
        if self.on_open_settings is not None:
            self.on_open_settings()
        self.accept()
