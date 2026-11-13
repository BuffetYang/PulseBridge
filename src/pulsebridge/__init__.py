"""PulseBridge —— 本地优先的 Apple 健康数据看板。"""

from __future__ import annotations

__version__ = "2.1.3"


def main() -> int:
    from .app import main as _main

    return _main()


__all__ = ["main", "__version__"]
