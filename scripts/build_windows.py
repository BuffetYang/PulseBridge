"""构建 Windows 便携包、安装包和 SHA256 校验文件。

用法（会临时提供 PyInstaller）：
    uv run --with pyinstaller python scripts/build_windows.py

输出：
    dist/PulseBridge/                       PyInstaller 目录
    dist/PulseBridge-v<version>-windows-x64.zip
    dist/installer/PulseBridge-Setup-<version>.exe   （检测到 Inno Setup 时）
    dist/SHA256SUMS.txt
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
APP_DIR = DIST / "PulseBridge"
BUILD_DIR = ROOT / "build" / "PulseBridge"


def app_version() -> str:
    text = (ROOT / "src" / "pulsebridge" / "__init__.py").read_text("utf-8")
    match = re.search(r'__version__\s*=\s*"([^"]+)"', text)
    if not match:
        raise SystemExit("无法读取版本号")
    return match.group(1)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_exe() -> None:
    print("== PyInstaller ==")
    shutil.rmtree(BUILD_DIR, ignore_errors=True)
    shutil.rmtree(APP_DIR, ignore_errors=True)
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--windowed",
        "--name",
        "PulseBridge",
        "--icon",
        str(ROOT / "assets" / "pulsebridge.ico"),
        "--collect-submodules",
        "PySide6",
        "--collect-submodules",
        "zeroconf",
        "--collect-submodules",
        "ifaddr",
        str(ROOT / "scripts" / "run_app.py"),
    ]
    subprocess.run(command, cwd=ROOT, check=True)


def copy_notices() -> None:
    print("== notices ==")
    shutil.copy2(ROOT / "LICENSE", APP_DIR / "LICENSE")
    shutil.copy2(ROOT / "THIRD_PARTY_NOTICES.md", APP_DIR / "THIRD_PARTY_NOTICES.md")
    target = APP_DIR / "licenses"
    shutil.copytree(ROOT / "licenses", target, dirs_exist_ok=True)


def make_zip(version: str) -> Path:
    print("== zip ==")
    archive = DIST / f"PulseBridge-v{version}-windows-x64.zip"
    if archive.exists():
        archive.unlink()
    with zipfile.ZipFile(
        archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as handle:
        for path in sorted(APP_DIR.rglob("*")):
            if path.is_file():
                handle.write(path, path.relative_to(APP_DIR))
    return archive


def find_iscc() -> Path | None:
    candidates = [
        os.environ.get("ISCC"),
        r"C:\Program Files\Inno Setup 6\ISCC.exe",
        r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return Path(candidate)
    return None


def make_installer(version: str) -> Path | None:
    iscc = find_iscc()
    if iscc is None:
        print("== installer: 未找到 Inno Setup ISCC.exe，跳过 ==")
        return None
    print("== installer ==")
    (DIST / "installer").mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            str(iscc),
            f"/DMyAppVersion={version}",
            str(ROOT / "installer" / "PulseBridge.iss"),
        ],
        cwd=ROOT,
        check=True,
    )
    installer = DIST / "installer" / f"PulseBridge-Setup-{version}.exe"
    if not installer.is_file():
        raise SystemExit(f"安装包未生成：{installer}")
    return installer


def main() -> int:
    version = app_version()
    print(f"PulseBridge {version}")
    build_exe()
    copy_notices()
    archive = make_zip(version)
    installer = make_installer(version)
    files = [archive]
    if installer is not None:
        files.append(installer)
    sums = []
    for path in files:
        digest = sha256(path)
        sums.append(f"{digest}  {path.name}")
        print(f"{path}  {path.stat().st_size:,} bytes  sha256={digest}")
    (DIST / "SHA256SUMS.txt").write_text("\n".join(sums) + "\n", "utf-8")
    print(f"== done: {DIST / 'SHA256SUMS.txt'} ==")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
