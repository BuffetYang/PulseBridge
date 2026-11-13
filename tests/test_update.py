from __future__ import annotations

from pulsebridge import update


def test_parse_version() -> None:
    assert update.parse_version("v2.4.0") == (2, 4, 0)
    assert update.parse_version("2.5") == (2, 5, 0)
    assert update.parse_version("nonsense") == (0, 0, 0)
    assert update.parse_version("v2.5.0") > update.parse_version("2.4.9")


def test_check_for_update_prefers_installer(monkeypatch) -> None:
    payload = {
        "tag_name": "v2.5.0",
        "name": "PulseBridge v2.5.0",
        "html_url": "https://github.com/example/releases/tag/v2.5.0",
        "body": "notes",
        "assets": [
            {
                "name": "PulseBridge-v2.5.0-windows-x64.zip",
                "browser_download_url": "https://example/zip",
            },
            {
                "name": "PulseBridge-Setup-2.5.0.exe",
                "browser_download_url": "https://example/setup",
            },
        ],
    }
    monkeypatch.setattr(
        update, "_fetch_json", lambda url, timeout=10: payload
    )
    info = update.check_for_update("2.4.0")
    assert info is not None
    assert info.version == "2.5.0"
    assert info.download_url == "https://example/setup"
    assert info.asset_name == "PulseBridge-Setup-2.5.0.exe"


def test_check_for_update_none_when_current(monkeypatch) -> None:
    monkeypatch.setattr(
        update,
        "_fetch_json",
        lambda url, timeout=10: {"tag_name": "v2.4.0", "assets": []},
    )
    assert update.check_for_update("2.4.0") is None
