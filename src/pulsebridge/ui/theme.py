"""深色主题与全局样式。"""

from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

COLORS: dict[str, str] = {
    "bg": "#0A0E14",
    "sidebar": "#0C1118",
    "surface": "#121923",
    "surface_alt": "#162030",
    "surface_hover": "#1A2634",
    "border": "#1F2B39",
    "border_soft": "#19232F",
    "text": "#EAF0F7",
    "muted": "#8B9CB3",
    "subtle": "#61748C",
    "accent": "#3DDC97",
    "accent_soft": "#173A2B",
    "blue": "#5B9DFF",
    "pink": "#FF6B8A",
    "purple": "#B18CFF",
    "orange": "#FFB347",
    "yellow": "#FFD166",
    "red": "#FF5C7A",
    "cyan": "#4CC9F0",
}


def color(name: str) -> QColor:
    return QColor(COLORS[name])


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(COLORS["bg"]))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(COLORS["text"]))
    palette.setColor(QPalette.ColorRole.Base, QColor("#0E151E"))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(COLORS["surface"]))
    palette.setColor(QPalette.ColorRole.Text, QColor(COLORS["text"]))
    palette.setColor(QPalette.ColorRole.Button, QColor(COLORS["surface_alt"]))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(COLORS["text"]))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(COLORS["accent"]))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#062016"))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(COLORS["surface_alt"]))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(COLORS["text"]))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(COLORS["subtle"]))
    palette.setColor(QPalette.ColorRole.Mid, QColor(COLORS["border"]))
    app.setPalette(palette)
    app.setStyleSheet(_QSS)


_QSS = """
QWidget {
    color: #EAF0F7;
    background: transparent;
    font-family: "Segoe UI Variable Text", "Microsoft YaHei UI", "Segoe UI", sans-serif;
    font-size: 13px;
}
QMainWindow, QWidget#root { background: #0A0E14; }

QFrame#sidebar {
    background: #0C1118;
    border-right: 1px solid #1A2532;
}
QFrame#card {
    background: #121923;
    border: 1px solid #1F2B39;
    border-radius: 18px;
}
QFrame#card[clickable="true"]:hover {
    background: #141E29;
    border-color: #2E6A4C;
}
QFrame#row {
    background: #0F1620;
    border: 1px solid #1A2635;
    border-radius: 14px;
}
QFrame#row:hover { background: #121C28; border-color: #243446; }
QFrame#softCard {
    background: #0E151E;
    border: 1px solid #1B2735;
    border-radius: 14px;
}

QLabel#brand { font-size: 18px; font-weight: 700; letter-spacing: .4px; }
QLabel#brandSub { color: #61748C; font-size: 11px; letter-spacing: 1.6px; }
QLabel#pageTitle { font-size: 25px; font-weight: 700; }
QLabel#pageSub { color: #8B9CB3; font-size: 13px; }
QLabel#cardTitle { font-size: 14px; font-weight: 600; }
QLabel#cardSub { color: #6F8198; font-size: 12px; }
QLabel#metricLabel { color: #8B9CB3; font-size: 12px; }
QLabel#metricValue { font-size: 30px; font-weight: 700; }
QLabel#metricUnit { color: #6F8198; font-size: 12px; }
QLabel#metricSub { color: #6F8198; font-size: 12px; }
QLabel#bigValue { font-size: 34px; font-weight: 700; }
QLabel#muted { color: #8B9CB3; }
QLabel#subtle { color: #61748C; font-size: 12px; }
QLabel#mono { font-family: "Cascadia Mono", "Consolas", monospace; font-size: 12px; }
QLabel#good { color: #3DDC97; }
QLabel#warn { color: #FFB347; }
QLabel#bad { color: #FF5C7A; }
QLabel#statValue { font-size: 21px; font-weight: 600; }
QLabel#chip { background: #16202B; color: #9FB0C4; border-radius: 999px;
              padding: 3px 10px; font-size: 11px; }
QLabel#pillGood { background: #14291F; color: #3DDC97; border-radius: 999px;
                  padding: 5px 12px; font-size: 12px; }
QLabel#pillWarn { background: #2C2415; color: #FFB347; border-radius: 999px;
                  padding: 5px 12px; font-size: 12px; }
QLabel#pillBad { background: #2E1720; color: #FF5C7A; border-radius: 999px;
                 padding: 5px 12px; font-size: 12px; }

QPushButton#navButton {
    text-align: left;
    padding: 10px 14px;
    border: none;
    border-radius: 11px;
    color: #8B9CB3;
    font-size: 13px;
    background: transparent;
}
QPushButton#navButton:hover { background: #141E29; color: #EAF0F7; }
QPushButton#navButton:checked {
    background: #15291F;
    color: #3DDC97;
    font-weight: 600;
}
QPushButton#primaryButton {
    background: #3DDC97; color: #062016; border: none; border-radius: 10px;
    padding: 9px 18px; font-weight: 600;
}
QPushButton#primaryButton:hover { background: #57E8A8; }
QPushButton#primaryButton:pressed { background: #2FC488; }
QPushButton#ghostButton {
    background: #16202B; border: 1px solid #243244; border-radius: 10px;
    padding: 8px 14px; color: #C8D5E4;
}
QPushButton#ghostButton:hover { background: #1B2836; border-color: #33465C; }
QPushButton#ghostButton:pressed { background: #14202C; }
QPushButton#chipButton {
    background: transparent; border: 1px solid #243244; border-radius: 999px;
    padding: 6px 15px; color: #92A4B9;
}
QPushButton#chipButton:hover { border-color: #33465C; color: #C8D5E4; }
QPushButton#chipButton:checked {
    background: #163225; border-color: #2E6A4C; color: #3DDC97;
}
QPushButton#iconButton {
    background: #16202B; border: 1px solid #243244; border-radius: 9px;
    padding: 6px 10px; color: #9FB0C4;
}
QPushButton#iconButton:hover { background: #1B2836; color: #EAF0F7; }
QPushButton#linkButton {
    background: transparent; border: none; color: #3DDC97; padding: 4px 2px;
    text-align: left;
}
QPushButton#linkButton:hover { color: #7CF0BF; }

QLineEdit, QSpinBox, QComboBox {
    background: #0E151E;
    border: 1px solid #22303F;
    border-radius: 10px;
    padding: 7px 11px;
    selection-background-color: #264C3A;
}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus { border-color: #35664F; }
QComboBox::drop-down { border: none; width: 26px; }
QComboBox QAbstractItemView {
    background: #121923; border: 1px solid #22303F;
    selection-background-color: #1C3830; outline: 0;
}
QSpinBox::up-button, QSpinBox::down-button { width: 18px; background: #16202B; border: none; }
QCheckBox { spacing: 9px; color: #C8D5E4; }
QCheckBox::indicator { width: 17px; height: 17px; }
QToolTip {
    background: #182333; color: #EAF0F7; border: 1px solid #2A3A4D;
    padding: 6px 8px; border-radius: 6px;
}
QScrollArea { border: none; background: transparent; }
QScrollArea > QWidget > QWidget { background: transparent; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: #253345; border-radius: 5px; min-height: 32px; }
QScrollBar::handle:vertical:hover { background: #31445A; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px; }
QScrollBar::handle:horizontal { background: #253345; border-radius: 5px; min-width: 32px; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QTextBrowser {
    background: #0E151E; border: 1px solid #22303F; border-radius: 12px;
    padding: 12px;
}
QTextBrowser h2 { color: #EAF0F7; }
QTextBrowser code { color: #7CF0BF; background: #0B1A14; }
QMenu {
    background: #121923; border: 1px solid #22303F; border-radius: 10px; padding: 6px;
}
QMenu::item { padding: 7px 22px; border-radius: 6px; }
QMenu::item:selected { background: #1B2836; }
QSplitter::handle { background: transparent; }
"""
