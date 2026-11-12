"""PulseBridge 配置管理。

配置保存在 ``%APPDATA%\\PulseBridge\\config.json``；设置 ``PULSEBRIDGE_HOME``
环境变量可以覆盖数据目录（测试或便携模式使用）。
"""

from __future__ import annotations

import json
import os
import secrets
from pathlib import Path
from typing import Any

APP_NAME = "PulseBridge"
APP_VERSION = "0.1.0"
DEFAULT_PORT = 8765

DEFAULTS: dict[str, Any] = {
    "port": DEFAULT_PORT,
    "token": "",
    "launch_at_startup": False,
    "start_minimized": False,
    "close_to_tray": True,
    "theme": "dark",
    "retention_days": 0,
}


def app_data_dir() -> Path:
    """返回应用数据目录（默认 ``%APPDATA%\\PulseBridge``）。"""
    override = os.environ.get("PULSEBRIDGE_HOME")
    if override:
        base = Path(override)
    else:
        appdata = os.environ.get("APPDATA")
        base = (Path(appdata) if appdata else Path.home()) / APP_NAME
    base.mkdir(parents=True, exist_ok=True)
    return base


class Config:
    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path else app_data_dir() / "config.json"
        self._data: dict[str, Any] = dict(DEFAULTS)
        self.load()

    def load(self) -> None:
        raw: dict[str, Any] = {}
        try:
            parsed = json.loads(self.path.read_text("utf-8"))
            if isinstance(parsed, dict):
                raw = parsed
        except (OSError, ValueError):
            raw = {}
        for key in DEFAULTS:
            if key in raw:
                self._data[key] = raw[key]
        if not self._data.get("token"):
            self._data["token"] = secrets.token_urlsafe(18)
        self.save()

    def save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), "utf-8")
            tmp.replace(self.path)
        except OSError:
            pass

    # -- 便捷访问 ---------------------------------------------------------
    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value
        self.save()

    @property
    def token(self) -> str:
        return str(self._data["token"])

    @property
    def port(self) -> int:
        value = self._data.get("port")
        if value is None:
            return DEFAULT_PORT
        try:
            return int(value)
        except (TypeError, ValueError):
            return DEFAULT_PORT

    def regenerate_token(self) -> str:
        token = secrets.token_urlsafe(18)
        self._data["token"] = token
        self.save()
        return token
