# PulseBridge

Windows 桌面端 Apple 健康数据看板：iPhone 快捷指令 → 局域网 HTTP → SQLite → PySide6 UI。

## 常用命令

```bash
uv sync
uv run pulsebridge              # 启动桌面程序（需要图形环境）
uv run pytest -q                # 测试（无界面，不依赖 Qt）
uv run python scripts/seed_demo.py   # 生成演示数据并截图到 docs/screenshots/
uv run python -m pulsebridge --minimized --port 9000
```

## 架构要点

- `server.py`：`ThreadingHTTPServer` 监听 `0.0.0.0:8765`，Token 鉴权（`X-PulseBridge-Token` 或 `?token=`）；
  路由 `/`、`/api/ping`、`/api/status`、`/api/ingest`、`/api/export`。服务在后台线程运行，
  通过 `bus.IngestBus.ingested` 信号通知 UI。
- `ingest.py`：把快捷指令 JSON 归一化为样本/运动。没有 UUID 时用内容指纹生成稳定 UUID；
  运动去重指纹不包含来源（同一场训练可能来自 iPhone 与 Watch）。
- `db.py`：WAL SQLite，单连接 + `RLock`；`samples.uuid` 唯一索引实现幂等去重。
- `analytics.py`：累计型指标按「来源日合计取最大值」避免 iPhone + Watch 重复计数；
  睡眠按醒来日聚合，多来源取睡眠时长最大的来源。
- 时间戳统一存 UTC 秒，展示用本地时区；`util.parse_timestamp` 支持 ISO 8601 / 秒 / 毫秒。
- UI 为纯 PySide6 + 自绘图表，无 pyqtgraph/matplotlib；主题在 `ui/theme.py`。

## 约束与背景

- HealthKit 无公开云端 API，Windows 无法直接读取；只能用 iPhone 快捷指令（免费）导出。
- iOS 自动化没有「每小时」触发器，只能 24 条定点自动化或 Wi-Fi/充电触发；
  客户端每次拉最近 1 天，服务端去重，因此缺失触发不会丢数据。
- 不要将端口暴露到公网；Token 是唯一写入鉴权。
- 中文文案与格式化统一走 `util.py` 的辅助函数。

## 测试注意

- 测试直接导入核心模块，不创建 QApplication；Qt 相关代码只在 `ui/` 与 `app.py`。
- 服务端测试使用端口 0（系统分配）避免占用。
