from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

from pulsebridge.config import Config
from pulsebridge.db import Database
from pulsebridge.server import ServerController


def _start(tmp_path):
    config = Config(tmp_path / "config.json")
    config.set("port", 0)
    db = Database(tmp_path / "test.db")
    received: list[dict] = []
    controller = ServerController(config, db, received.append)
    assert controller.start(), controller.error
    return config, db, controller, received


def _post(url: str, payload: dict, token: str | None) -> tuple[int, dict]:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-PulseBridge-Token"] = token
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=3) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def test_ping_and_ingest_flow(tmp_path) -> None:
    config, db, controller, received = _start(tmp_path)
    port = controller.port
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/ping", timeout=3) as response:
            assert response.status == 200
            payload = json.loads(response.read().decode("utf-8"))
            assert payload["ok"] is True
            assert payload["app"] == "PulseBridge"

        payload = {
            "device": "iPhone",
            "samples": [
                {
                    "type": "heart_rate",
                    "start": "2026-11-12T08:00:00+08:00",
                    "end": "2026-11-12T08:01:00+08:00",
                    "value": 72,
                    "source": "Apple Watch",
                }
            ],
        }
        url = f"http://127.0.0.1:{port}/api/ingest"

        status, body = _post(url, payload, None)
        assert status == 401

        status, body = _post(url, payload, config.token)
        assert status == 200
        assert body["samples_new"] == 1
        assert body["samples_duplicate"] == 0
        assert db.stats()["samples"] == 1

        status, body = _post(url, payload, config.token)
        assert status == 200
        assert body["samples_new"] == 0
        assert body["samples_duplicate"] == 1

        # 回调由服务线程触发，稍等
        deadline = time.time() + 2
        while not received and time.time() < deadline:
            time.sleep(0.02)
        assert received and received[0]["samples_new"] == 1

        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=3) as response:
            html = response.read().decode("utf-8")
            assert "接收服务运行中" in html
    finally:
        controller.stop()
        db.close()


def test_invalid_json_is_logged(tmp_path) -> None:
    config, db, controller, _ = _start(tmp_path)
    port = controller.port
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/ingest",
            data=b"not json",
            headers={
                "Content-Type": "application/json",
                "X-PulseBridge-Token": config.token,
            },
            method="POST",
        )
        try:
            urllib.request.urlopen(request, timeout=3)
            raise AssertionError("应当返回 400")
        except urllib.error.HTTPError as exc:
            assert exc.code == 400
        events = db.recent_events(1)
        assert events and events[0]["status"] == "error"
    finally:
        controller.stop()
        db.close()
