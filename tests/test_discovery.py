from __future__ import annotations

from pulsebridge.config import Config
from pulsebridge.discovery import MdnsAdvertiser, stable_hostname, stable_url


def test_stable_hostname_and_url(tmp_path) -> None:
    config = Config(tmp_path / "config.json")
    config.set("token", "token-a")
    hostname = stable_hostname(config)
    assert hostname.startswith("pulsebridge-")
    assert hostname.endswith(".local.")
    assert stable_url(config, 8765) == f"http://{hostname.rstrip('.')}:8765"
    assert stable_hostname(config) == hostname

    config.set("token", "token-b")
    assert stable_hostname(config) != hostname


def test_advertiser_rejects_loopback() -> None:
    advertiser = MdnsAdvertiser("pulsebridge-test.local.", 8765)
    assert advertiser.start("127.0.0.1") is False
    assert advertiser.active is False
    assert "局域网" in advertiser.error
