"""打包 / 直接运行用的入口脚本。

uv run python scripts/run_app.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pulsebridge import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
