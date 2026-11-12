"""生成程序图标 assets/pulsebridge.ico / .png（打包时使用）。

用法：uv run python scripts/make_icon.py
"""

from __future__ import annotations

import os
import struct
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtCore import QBuffer, QByteArray  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402

from pulsebridge.ui.icons import brand_pixmap  # noqa: E402


def main() -> int:
    app = QGuiApplication([])  # noqa: F841
    assets = ROOT / "assets"
    assets.mkdir(exist_ok=True)

    images: list[tuple[int, bytes]] = []
    for size in (16, 24, 32, 48, 64, 128, 256):
        pixmap = brand_pixmap(size)
        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(QBuffer.OpenModeFlag.WriteOnly)
        pixmap.save(buffer, "PNG")
        buffer.close()
        images.append((size, bytes(data)))

    (assets / "pulsebridge.png").write_bytes(images[-1][1])

    offset = 6 + 16 * len(images)
    directory = bytearray()
    payload = bytearray()
    for size, data in images:
        dimension = 0 if size >= 256 else size
        directory += struct.pack(
            "<BBBBHHII", dimension, dimension, 0, 0, 1, 32, len(data), offset
        )
        payload += data
        offset += len(data)

    header = struct.pack("<HHH", 0, 1, len(images))
    (assets / "pulsebridge.ico").write_bytes(header + directory + payload)
    print(f"已生成 {assets / 'pulsebridge.ico'}")
    print(f"已生成 {assets / 'pulsebridge.png'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
