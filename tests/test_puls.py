from __future__ import annotations

import gzip
import json
import time
import urllib.error
import urllib.request
import uuid

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


def _batch(*, samples=(), deletions=(), reason="manual", batch_id=None) -> bytes:
    lines = [
        {
            "schemaVersion": 1,
            "clientVersion": "pulsebridge-test/1",
            "timeZoneID": "Asia/Shanghai",
            "batchID": batch_id or str(uuid.uuid4()),
            "deviceID": "test-device",
            "type": "HKQuantityTypeIdentifierHeartRate"
            if samples
            else "probe",
            "reason": reason,
            "exportedAt": int(time.time() * 1000),
            "sampleCount": len(samples),
            "deletionCount": len(deletions),
            "routeCount": 0,
            "seriesCount": 0,
            "aggregateCount": 0,
            "activitySummaryCount": 0,
            "profileCount": 0,
        }
    ]
    lines.extend(samples)
    lines.extend({"deleted": deletion} for deletion in deletions)
    text = "\n".join(json.dumps(line, ensure_ascii=False) for line in lines) + "\n"
    return gzip.compress(text.encode("utf-8"))


def _post(url: str, body: bytes, token: str, *, protocol: str = "1") -> tuple[int, dict]:
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/x-ndjson",
            "Content-Encoding": "gzip",
            "X-Puls-Protocol": protocol,
            "X-User-ID": str(uuid.uuid4()),
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def _get(url: str, token: str) -> tuple[int, dict]:
    request = urllib.request.Request(
        url, headers={"Authorization": f"Bearer {token}"}, method="GET"
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def test_capabilities_and_bearer_auth(tmp_path) -> None:
    config, db, controller, _ = _start(tmp_path)
    base = f"http://127.0.0.1:{controller.port}"
    try:
        status, body = _get(f"{base}/v1/capabilities", config.token)
        assert status == 200
        assert body["protocolVersions"] == [1]
        assert "batches" in body["features"]

        status, _ = _get(f"{base}/v1/capabilities", "wrong-token")
        assert status == 401
    finally:
        controller.stop()
        db.close()


def test_puls_samples_sleep_and_workouts(tmp_path) -> None:
    config, db, controller, received = _start(tmp_path)
    base = f"http://127.0.0.1:{controller.port}"
    now = int(time.time() * 1000)
    hr_uuid = str(uuid.uuid4())
    workout_uuid = str(uuid.uuid4())
    samples = [
        {
            "uuid": hr_uuid,
            "type": "HKQuantityTypeIdentifierHeartRate",
            "kind": "quantity",
            "start": now - 60000,
            "end": now - 55000,
            "value": 72.5,
            "unit": "count/min",
            "sourceName": "Apple Watch",
        },
        {
            "uuid": str(uuid.uuid4()),
            "type": "HKCategoryTypeIdentifierSleepAnalysis",
            "kind": "category",
            "start": now - 8 * 3600 * 1000,
            "end": now - 7 * 3600 * 1000,
            "category": 3,
            "sourceName": "Apple Watch",
        },
        {
            "uuid": workout_uuid,
            "type": "HKWorkoutTypeIdentifier",
            "kind": "workout",
            "start": now - 2 * 3600 * 1000,
            "end": now - 90 * 60 * 1000,
            "sourceName": "Apple Watch",
            "workout": {
                "activityType": "running",
                "duration": 1800,
                "totalEnergyKcal": 320,
                "totalDistanceMeters": 5020,
                "statisticsDetail": {
                    "HKQuantityTypeIdentifierHeartRate": {"avg": 152, "max": 171}
                },
            },
        },
    ]
    try:
        status, body = _post(f"{base}/v1/batches", _batch(samples=samples), config.token)
        assert status == 200, body
        assert body["accepted"] == 3
        assert db.stats()["samples"] == 2
        assert db.stats()["workouts"] == 1

        hr = db.latest_sample("heart_rate")
        assert hr is not None and hr["value"] == 72.5
        sleep = db.sleep_samples(now // 1000 - 9 * 3600)
        assert sleep and sleep[0]["value_text"] == "core"

        workout = db.workout_rows(now // 1000 - 9 * 3600)[0]
        assert workout["activity_type"] == "running"
        assert workout["distance_m"] == 5020
        assert workout["avg_hr"] == 152
        assert workout["max_hr"] == 171

        # 重放同一批数据：UUID 幂等，全部算重复
        status, body = _post(f"{base}/v1/batches", _batch(samples=samples), config.token)
        assert status == 200
        assert body["accepted"] == 0
        assert body["duplicates"] == 3
        assert db.stats()["samples"] == 2

        # 删除行
        status, body = _post(
            f"{base}/v1/batches",
            _batch(deletions=[{"uuid": hr_uuid, "type": "HKQuantityTypeIdentifierHeartRate"}]),
            config.token,
        )
        assert status == 200
        assert body["deleted"] == 1
        assert db.stats()["samples"] == 1

        deadline = time.time() + 2
        while not received and time.time() < deadline:
            time.sleep(0.02)
        assert received and received[0]["device"] == "PulsHealth"
    finally:
        controller.stop()
        db.close()


def test_probe_batch_and_unsupported_protocol(tmp_path) -> None:
    config, db, controller, _ = _start(tmp_path)
    base = f"http://127.0.0.1:{controller.port}"
    try:
        status, body = _post(f"{base}/v1/batches", _batch(), config.token)
        assert status == 200
        assert body["accepted"] == 0

        status, body = _post(
            f"{base}/v1/batches", _batch(), config.token, protocol="2"
        )
        assert status == 400
        assert body["error"] == "unsupported protocol version"
    finally:
        controller.stop()
        db.close()


def test_puls_activity_summary(tmp_path) -> None:
    config, db, controller, _ = _start(tmp_path)
    base = f"http://127.0.0.1:{controller.port}"
    header = {
        "schemaVersion": 1,
        "clientVersion": "pulsebridge-test/1",
        "batchID": str(uuid.uuid4()),
        "deviceID": "test-device",
        "type": "HKActivitySummaryTypeIdentifier",
        "reason": "incremental",
        "exportedAt": int(time.time() * 1000),
        "sampleCount": 0,
        "deletionCount": 0,
        "routeCount": 0,
        "seriesCount": 0,
        "aggregateCount": 0,
        "activitySummaryCount": 1,
        "profileCount": 0,
    }
    line = {
        "activitySummary": {
            "localDate": "2026-11-12",
            "moveKcal": 420.5,
            "moveGoalKcal": 650,
            "exerciseMin": 25,
            "exerciseGoalMin": 30,
            "standHours": 9,
            "standGoalHours": 12,
        }
    }
    body = gzip.compress(
        ("\n".join(json.dumps(item) for item in (header, line)) + "\n").encode()
    )
    try:
        status, response = _post(f"{base}/v1/batches", body, config.token)
        assert status == 200, response
        assert response["activitySummaries"] == 1
        summary = db.latest_activity_summary()
        assert summary is not None
        assert summary["date"] == "2026-11-12"
        assert summary["move_kcal"] == 420.5
        assert summary["stand_hours"] == 9
    finally:
        controller.stop()
        db.close()
