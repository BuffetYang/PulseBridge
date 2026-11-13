"""检查 GitHub Releases 是否有新版本（不自动下载/安装）。"""

from __future__ import annotations

import json
import re
import urllib.request
from dataclasses import dataclass

REPO = "BuffetYang/PulseBridge"
LATEST_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_URL = f"https://github.com/{REPO}/releases"


class UpdateError(RuntimeError):
    pass


@dataclass
class UpdateInfo:
    version: str
    tag: str
    name: str
    page_url: str
    notes: str
    download_url: str
    asset_name: str


def parse_version(text: str) -> tuple[int, int, int]:
    match = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", str(text or ""))
    if not match:
        return (0, 0, 0)
    return (
        int(match.group(1)),
        int(match.group(2)),
        int(match.group(3) or 0),
    )


def _fetch_json(url: str, timeout: int = 10) -> dict:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "PulseBridge-update-check",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.load(response)
    except Exception as exc:  # noqa: BLE001
        raise UpdateError(str(exc)) from exc
    if not isinstance(data, dict):
        raise UpdateError("更新接口返回格式异常")
    return data


def check_for_update(
    current_version: str, timeout: int = 10
) -> UpdateInfo | None:
    """返回比 ``current_version`` 新的版本；没有更新时返回 None。"""
    data = _fetch_json(LATEST_URL, timeout=timeout)
    tag = str(data.get("tag_name") or "")
    latest = parse_version(tag or data.get("name") or "")
    if latest <= parse_version(current_version):
        return None

    assets = data.get("assets") or []
    chosen = None
    # 优先安装包，其次便携 zip
    for asset in assets:
        name = str(asset.get("name") or "")
        if name.lower().endswith(".exe") and "setup" in name.lower():
            chosen = asset
            break
    if chosen is None:
        for asset in assets:
            name = str(asset.get("name") or "")
            if name.lower().endswith(".zip"):
                chosen = asset
                break
    if chosen is not None:
        download = str(chosen.get("browser_download_url") or "")
        asset_name = str(chosen.get("name") or "")
    else:
        download = str(data.get("html_url") or RELEASES_URL)
        asset_name = ""

    return UpdateInfo(
        version=".".join(str(part) for part in latest),
        tag=tag,
        name=str(data.get("name") or tag),
        page_url=str(data.get("html_url") or RELEASES_URL),
        notes=str(data.get("body") or ""),
        download_url=download,
        asset_name=asset_name,
    )
