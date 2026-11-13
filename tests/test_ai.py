from __future__ import annotations

import time

from pulsebridge import ai
from pulsebridge.ai import AIConfig
from pulsebridge.config import Config
from pulsebridge.db import Database
from pulsebridge.util import start_of_local_day


def _sample(
    uuid: str,
    type_: str,
    start_ts: int,
    value: float | None,
    unit: str = "count",
    value_text: str | None = None,
    source: str = "Apple Watch",
    duration: int = 60,
) -> dict:
    return {
        "uuid": uuid,
        "type": type_,
        "start_ts": start_ts,
        "end_ts": start_ts + duration,
        "value": value,
        "value_text": value_text,
        "unit": unit,
        "source": source,
        "device": "Apple Watch",
        "metadata": None,
    }


def _seed(db: Database, days: int = 7) -> None:
    samples = []
    for offset in range(days):
        day_start = start_of_local_day(offset_days=-offset)
        samples.extend(
            [
                _sample(
                    f"steps-{offset}",
                    "steps",
                    day_start + 8 * 3600,
                    8000.0,
                    "count",
                ),
                _sample(
                    f"resting-{offset}",
                    "resting_heart_rate",
                    day_start + 60,
                    60.0,
                    "count/min",
                ),
                _sample(f"hrv-{offset}", "hrv", day_start + 120, 50.0, "ms"),
            ]
        )
        samples.append(
            {
                **_sample(
                    f"sleep-{offset}",
                    "sleep_analysis",
                    day_start - 3600,
                    None,
                    value_text="core",
                ),
                "end_ts": day_start + 7 * 3600,
            }
        )
    db.insert_samples(samples)
    now = int(time.time())
    db.insert_workouts(
        [
            {
                "uuid": "workout-ai",
                "activity_type": "running",
                "start_ts": start_of_local_day() + 8 * 3600,
                "end_ts": start_of_local_day() + 8 * 3600 + 1800,
                "duration_s": 1800,
                "distance_m": 5000,
                "energy_kcal": 200,
                "avg_hr": 140,
                "max_hr": 160,
                "source": "Apple Watch",
                "metadata": None,
            }
        ]
    )
    db.record_ingest(
        remote="192.168.1.2",
        device="PulsHealth",
        samples_new=len(samples),
        samples_dupe=0,
        workouts_new=1,
        workouts_dupe=0,
    )
    db.save_ai_report(
        {
            "created_at": now,
            "period_start": "2026-11-07",
            "period_end": "2026-11-13",
            "provider": "openai",
            "model": "glm-4.6v-flash",
            "mode": "llm",
            "content": "# 测试周报",
            "context": {"period": {"start": "2026-11-07"}},
        }
    )


def test_url_normalization() -> None:
    assert (
        ai.openai_chat_url("https://open.bigmodel.cn/api/paas/v4")
        == "https://open.bigmodel.cn/api/paas/v4/chat/completions"
    )
    assert (
        ai.openai_chat_url("https://api.openai.com/v1/")
        == "https://api.openai.com/v1/chat/completions"
    )
    assert (
        ai.openai_chat_url("https://api.openai.com")
        == "https://api.openai.com/v1/chat/completions"
    )
    assert (
        ai.openai_chat_url("https://example.com/v1/chat/completions")
        == "https://example.com/v1/chat/completions"
    )
    assert (
        ai.ollama_chat_url("http://127.0.0.1:11434")
        == "http://127.0.0.1:11434/api/chat"
    )
    assert (
        ai.ollama_chat_url("http://127.0.0.1:11434/api")
        == "http://127.0.0.1:11434/api/chat"
    )


def test_ai_config_from_config(tmp_path) -> None:
    config = Config(tmp_path / "config.json")
    config.set("ai_provider", "openai")
    config.set("ai_base_url", "https://example.com/v1")
    config.set("ai_api_key", "secret")
    config.set("ai_model", "model-x")
    cfg = ai.ai_config_from_config(config)
    assert cfg.provider == "openai"
    assert cfg.base_url == "https://example.com/v1"
    assert cfg.api_key == "secret"
    assert cfg.model == "model-x"
    assert cfg.enabled is True


def test_weekly_context_and_rule_report(tmp_path) -> None:
    db = Database(tmp_path / "test.db")
    _seed(db)

    context = ai.build_weekly_context(db, days=7, baseline_days=30)
    assert context["period"]["days"] == 7
    assert context["metrics"]["steps"]["avg"] == 8000.0
    assert context["metrics"]["resting_heart_rate"]["avg"] == 60.0
    assert context["sleep"]["nights"] == 7
    assert context["sleep"]["avg_hours"] == 8.0
    assert context["workouts"]["count"] == 1
    assert "running" not in context["workouts"]["by_type"]  # 显示为中文“跑步”
    assert "跑步" in context["workouts"]["by_type"]

    report = ai.rule_based_report(context)
    assert "本周概览" in report
    assert "睡眠" in report
    assert "恢复" in report
    assert "训练" in report
    assert "不构成医疗诊断" in report

    content, mode, error = ai.generate_report(AIConfig(provider="none"), context)
    assert mode == "rule"
    assert error == ""
    assert content == report

    reports = db.recent_ai_reports(5)
    assert reports
    assert reports[0]["content"] == "# 测试周报"
    assert db.ai_report(reports[0]["id"])["model"] == "glm-4.6v-flash"
    db.close()


def test_openai_response_parsing(monkeypatch) -> None:
    def fake_post(url, payload, headers, timeout):
        assert url.endswith("/chat/completions")
        assert headers["Authorization"] == "Bearer key"
        return {
            "choices": [
                {"message": {"content": "# 模型周报\n\n" + "内容" * 60}}
            ]
        }

    monkeypatch.setattr(ai, "_post_json", fake_post)
    config = AIConfig(
        provider="openai",
        base_url="https://example.com/v1",
        api_key="key",
        model="model-x",
    )
    assert ai.call_openai_compatible(config, [{"role": "user", "content": "hi"}]).startswith(
        "# 模型周报"
    )
    content, mode, error = ai.generate_report(
        config,
        {
            "period": {"start": "2026-11-07", "end": "2026-11-13", "baseline_days": 30},
            "metrics": {},
            "sleep": {},
            "workouts": {},
            "flags": [],
        },
    )
    assert mode == "llm"
    assert error == ""
    assert content.startswith("# 模型周报")


def test_http_provider_round_trip() -> None:
    import http.server
    import json
    import threading

    received: dict = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length))
            received["path"] = self.path
            received["auth"] = self.headers.get("Authorization")
            received["body"] = body
            if self.path.endswith("/api/chat"):
                reply = {"message": {"role": "assistant", "content": "OLLAMA OK"}}
            else:
                reply = {"choices": [{"message": {"content": "OPENAI OK"}}]}
            data = json.dumps(reply).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):  # noqa: A003
            return

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        openai_config = AIConfig(
            provider="openai",
            base_url=f"http://127.0.0.1:{port}/v1",
            api_key="key",
            model="model-x",
        )
        assert (
            ai.call_openai_compatible(
                openai_config, [{"role": "user", "content": "hi"}]
            )
            == "OPENAI OK"
        )
        assert received["path"].endswith("/v1/chat/completions")
        assert received["auth"] == "Bearer key"
        assert received["body"]["model"] == "model-x"

        ollama_config = AIConfig(
            provider="ollama",
            base_url=f"http://127.0.0.1:{port}",
            model="model-y",
        )
        assert (
            ai.call_ollama(
                ollama_config, [{"role": "user", "content": "hi"}]
            )
            == "OLLAMA OK"
        )
        assert received["path"].endswith("/api/chat")
    finally:
        server.shutdown()
        server.server_close()


def test_reasoning_only_response_counts_as_connection(monkeypatch) -> None:
    monkeypatch.setattr(
        ai,
        "_post_json",
        lambda *args, **kwargs: {
            "choices": [
                {
                    "message": {
                        "content": "",
                        "reasoning_content": "thinking...",
                    }
                }
            ]
        },
    )
    config = AIConfig(
        provider="openai",
        base_url="https://example.com/v1",
        api_key="key",
        model="deepseek-flash",
    )
    ok, message = ai.test_connection(config)
    assert ok is True
    assert "思考" in message


def test_model_failure_falls_back_to_rule(monkeypatch) -> None:
    def fail_post(url, payload, headers, timeout):
        raise ai.AIError("boom")

    monkeypatch.setattr(ai, "_post_json", fail_post)
    config = AIConfig(
        provider="openai",
        base_url="https://example.com/v1",
        api_key="key",
        model="model-x",
    )
    context = {
        "period": {"start": "2026-11-07", "end": "2026-11-13", "baseline_days": 30},
        "metrics": {},
        "sleep": {},
        "workouts": {},
        "flags": [],
    }
    content, mode, error = ai.generate_report(config, context)
    assert mode == "rule"
    assert "boom" in error
    assert "本周概览" in content
