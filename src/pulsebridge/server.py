"""局域网接收服务：内置 HTTP 服务器，供 iPhone 快捷指令 POST 健康数据。"""

from __future__ import annotations

import json
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

from .config import APP_NAME, APP_VERSION, Config
from .db import Database
from .ingest import normalize_payload

MAX_BODY_BYTES = 25 * 1024 * 1024

IngestCallback = Callable[[dict[str, Any]], None]


class _Handler(BaseHTTPRequestHandler):
    server_version = f"{APP_NAME}/{APP_VERSION}"
    protocol_version = "HTTP/1.1"

    # -- 基础设施 -------------------------------------------------------
    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003
        # 静默：错误通过桌面端“最近同步”展示
        return

    @property
    def app(self) -> "IngestServer":
        return self.server  # type: ignore[return-value]

    def _send(
        self,
        status: int,
        body: bytes,
        content_type: str = "application/json; charset=utf-8",
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        if extra_headers:
            for key, value in extra_headers.items():
                self.send_header(key, value)
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send(status, body)

    def _token_from_request(self) -> str | None:
        header = self.headers.get("X-PulseBridge-Token") or self.headers.get(
            "X-Auth-Token"
        )
        if header:
            return header.strip()
        query = parse_qs(urlparse(self.path).query)
        values = query.get("token")
        return values[0].strip() if values else None

    def _authorized(self) -> bool:
        provided = self._token_from_request()
        return bool(provided) and secrets.compare_digest(provided, self.app.config.token)

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            raise ValueError("请求体为空")
        if length > MAX_BODY_BYTES:
            raise ValueError("请求体过大")
        body = self.rfile.read(length)
        if len(body) != length:
            raise ValueError("请求体不完整")
        return body

    # -- 路由 -----------------------------------------------------------
    def do_OPTIONS(self) -> None:  # noqa: N802
        self._send(
            204,
            b"",
            extra_headers={
                "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type, X-PulseBridge-Token",
            },
        )

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path.rstrip("/") or "/"

        if path in ("/", "/index.html"):
            self._send(200, self._status_page().encode("utf-8"), "text/html; charset=utf-8")
            return

        if path == "/api/ping":
            stats = self.app.db.stats()
            self._json(
                200,
                {
                    "ok": True,
                    "app": APP_NAME,
                    "version": APP_VERSION,
                    "server_time": int(time.time()),
                    "last_sync_ts": stats["last_sync_ts"],
                },
            )
            return

        if path == "/api/status":
            if not self._authorized():
                self._json(401, {"ok": False, "error": "token 无效"})
                return
            stats = self.app.db.stats()
            self._json(
                200,
                {
                    "ok": True,
                    "samples": stats["samples"],
                    "workouts": stats["workouts"],
                    "last_sync_ts": stats["last_sync_ts"],
                    "port": self.app.server_port,
                },
            )
            return

        if path == "/api/export":
            if not self._authorized():
                self._json(401, {"ok": False, "error": "token 无效"})
                return
            query = parse_qs(urlparse(self.path).query)
            try:
                days = int((query.get("days") or ["7"])[0])
            except ValueError:
                days = 7
            days = max(1, min(days, 3650))
            payload = self.app.db.export_payload(int(time.time()) - days * 86400)
            self._json(200, payload)
            return

        if path == "/favicon.ico":
            self._send(204, b"")
            return

        self._json(404, {"ok": False, "error": "Not found"})

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path.rstrip("/") or "/"
        if path not in ("/api/ingest", "/ingest"):
            self._json(404, {"ok": False, "error": "Not found"})
            return
        if not self._authorized():
            self._json(401, {"ok": False, "error": "token 无效，请检查快捷指令中的 X-PulseBridge-Token"})
            return

        remote = self.client_address[0] if self.client_address else None
        try:
            body = self._read_body()
            try:
                payload = json.loads(body.decode("utf-8-sig"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError(f"JSON 解析失败：{exc}") from exc
            if not isinstance(payload, dict):
                raise ValueError("请求体必须是 JSON 对象")

            result = normalize_payload(payload)
            samples_new, samples_dupe = self.app.db.insert_samples(result.samples)
            workouts_new, workouts_dupe = self.app.db.insert_workouts(result.workouts)
            self.app.db.record_ingest(
                remote=remote,
                device=result.device,
                samples_new=samples_new,
                samples_dupe=samples_dupe,
                workouts_new=workouts_new,
                workouts_dupe=workouts_dupe,
                status="ok",
                message="; ".join(result.warnings) if result.warnings else None,
            )
            summary = {
                "ok": True,
                "samples_new": samples_new,
                "samples_duplicate": samples_dupe,
                "workouts_new": workouts_new,
                "workouts_duplicate": workouts_dupe,
                "warnings": result.warnings,
            }
            if self.app.on_ingest:
                try:
                    self.app.on_ingest(
                        {
                            **summary,
                            "device": result.device,
                            "remote": remote,
                            "received_at": int(time.time()),
                        }
                    )
                except Exception:  # 回调失败不能影响手机端请求
                    pass
            self._json(200, summary)
        except Exception as exc:  # noqa: BLE001
            message = str(exc) or exc.__class__.__name__
            try:
                self.app.db.record_ingest(
                    remote=remote,
                    device=None,
                    samples_new=0,
                    samples_dupe=0,
                    workouts_new=0,
                    workouts_dupe=0,
                    status="error",
                    message=message,
                )
            except Exception:
                pass
            self._json(400, {"ok": False, "error": message})

    # -- 状态页 ---------------------------------------------------------
    def _status_page(self) -> str:
        stats = self.app.db.stats()
        last_sync = (
            time.strftime("%Y-%m-%d %H:%M", time.localtime(stats["last_sync_ts"]))
            if stats["last_sync_ts"]
            else "尚未同步"
        )
        return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{APP_NAME} · 接收服务</title>
<style>
  :root {{ color-scheme: dark; }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; min-height: 100vh; display: grid; place-items: center;
         background: radial-gradient(1200px 600px at 20% 0%, #12251f 0%, #0a0e14 55%);
         color: #eaf0f7; font-family: -apple-system, "Segoe UI", "PingFang SC", sans-serif; }}
  .card {{ width: min(92vw, 480px); padding: 32px; border-radius: 24px;
          background: #121923; border: 1px solid #22303f;
          box-shadow: 0 30px 80px rgba(0,0,0,.45); }}
  .brand {{ display: flex; align-items: center; gap: 10px; font-weight: 650; letter-spacing: .3px; }}
  .logo {{ width: 34px; height: 34px; border-radius: 10px;
          background: linear-gradient(135deg, #3ddc97, #27b4d8);
          display: grid; place-items: center; color: #052016; font-size: 18px; }}
  h1 {{ font-size: 22px; margin: 22px 0 6px; }}
  p {{ color: #93a4b8; line-height: 1.6; margin: 0 0 20px; font-size: 14px; }}
  .status {{ display: inline-flex; align-items: center; gap: 8px; padding: 6px 12px;
            border-radius: 999px; background: #14291f; color: #3ddc97; font-size: 13px; }}
  .dot {{ width: 8px; height: 8px; border-radius: 50%; background: #3ddc97;
         box-shadow: 0 0 0 4px rgba(61,220,151,.15); }}
  .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin: 22px 0; }}
  .stat {{ background: #0e151e; border: 1px solid #1e2a38; border-radius: 14px; padding: 14px; }}
  .stat span {{ display: block; color: #7f90a5; font-size: 12px; margin-bottom: 6px; }}
  .stat strong {{ font-size: 20px; font-variant-numeric: tabular-nums; }}
  .hint {{ font-size: 12.5px; color: #6f8198; border-top: 1px solid #1e2a38; padding-top: 16px; }}
</style>
</head>
<body>
  <main class="card">
    <div class="brand"><div class="logo">⌁</div>{APP_NAME}</div>
    <h1>接收服务运行中</h1>
    <p>iPhone 已可通过同一 Wi-Fi 向这台电脑发送健康数据。</p>
    <div class="status"><span class="dot"></span>在线 · 端口 {self.app.server_port}</div>
    <div class="grid">
      <div class="stat"><span>健康样本</span><strong>{stats["samples"]:,}</strong></div>
      <div class="stat"><span>运动记录</span><strong>{stats["workouts"]:,}</strong></div>
      <div class="stat"><span>最近同步</span><strong style="font-size:15px">{last_sync}</strong></div>
      <div class="stat"><span>服务版本</span><strong style="font-size:15px">v{APP_VERSION}</strong></div>
    </div>
    <div class="hint">这个页面只用于验证手机与电脑之间的连接。数据看板请打开电脑上的 {APP_NAME} 桌面程序。</div>
  </main>
</body>
</html>"""


class IngestServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        address: tuple[str, int],
        db: Database,
        config: Config,
        on_ingest: IngestCallback | None = None,
    ) -> None:
        super().__init__(address, _Handler)
        self.db = db
        self.config = config
        self.on_ingest = on_ingest


class ServerController:
    """启动/停止内嵌 HTTP 服务，供 UI 控制。"""

    def __init__(
        self,
        config: Config,
        db: Database,
        on_ingest: IngestCallback | None = None,
    ) -> None:
        self.config = config
        self.db = db
        self.on_ingest = on_ingest
        self._server: IngestServer | None = None
        self._thread: threading.Thread | None = None
        self.error: str | None = None

    @property
    def running(self) -> bool:
        return self._server is not None

    @property
    def port(self) -> int:
        if self._server is not None:
            return int(self._server.server_port)
        return self.config.port

    def start(self) -> bool:
        self.stop()
        port = self.config.port
        try:
            server = IngestServer(
                ("0.0.0.0", port), self.db, self.config, self.on_ingest
            )
        except OSError as exc:
            self.error = (
                f"端口 {port} 启动失败：{exc}。请确认端口未被占用，或改用其他端口。"
            )
            self._server = None
            self._thread = None
            return False

        thread = threading.Thread(
            target=server.serve_forever,
            name="pulsebridge-http",
            kwargs={"poll_interval": 0.25},
            daemon=True,
        )
        thread.start()
        self._server = server
        self._thread = thread
        self.error = None
        return True

    def restart(self) -> bool:
        return self.start()

    def stop(self) -> None:
        server, thread = self._server, self._thread
        self._server = None
        self._thread = None
        if server is None:
            return
        try:
            server.shutdown()
        except Exception:
            pass
        try:
            server.server_close()
        except Exception:
            pass
        if thread is not None:
            thread.join(timeout=3)
