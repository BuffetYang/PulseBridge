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

- `server.py`：`ThreadingHTTPServer` 监听 `0.0.0.0:8765`，Token 鉴权（`Authorization: Bearer`、
  `X-PulseBridge-Token` 或 `?token=`）；快捷指令路由 `/api/ingest`，PulsHealth 路由
  `POST /v1/batches`、`GET /v1/capabilities`、`GET /healthz`。服务在后台线程运行，
  通过 `bus.IngestBus.ingested` 信号通知 UI。
- `puls.py`：PulsHealth Puls Sync Protocol v1 接收端；gzip NDJSON，按 header 行数解析，
  转换 quantity/category(睡眠)/workout，UUID 幂等；路线/序列/聚合/活动圆环/Profile 行忽略。
  可用官方 fixtures 验证：`docs/protocol/fixtures/`（PulsHealth 仓库）。
- `health_export.py`：流式导入 Apple Health `export.zip` / `export.xml`（iterparse + 分批写入，
  支持取消/进度）；记录、运动与 ActivitySummary 一并导入，按内容指纹跨通道去重。
- `reminders.py`：每周几/每月几号的导入提醒计算；`MainWindow._check_import_reminder` 通过托盘通知。
- `discovery.py`：mDNS 固定地址（`pulsebridge-xxxx.local`），随局域网 IP 变化重新广播；
  依赖 zeroconf，需放行 UDP 5353；部分公共 Wi-Fi 屏蔽组播时回退到 IP/热点/Tailscale。
- `update.py`：检查 GitHub Releases 是否有新版本（每天最多一次，不自动下载/安装）；
  `ui/main_window.py` 后台线程检查，托盘通知 + 设置页手动检查。
- `scripts/build_windows.py`：PyInstaller 便携包 + zip + Inno Setup 安装包 + SHA256SUMS；
  `installer/PulseBridge.iss` 按用户安装并保留 `%APPDATA%` 数据。
- `ai.py`：AI 健康周报。默认本地规则；用户可配置 OpenAI 兼容 API（GLM/DeepSeek 等）
  或本地 Ollama，不内置任何 Key；只发送 7/30 天聚合统计，周报存入 `ai_reports` 表。
- `db.py` 的 `fingerprint` 唯一索引用于跨通道去重（PulsHealth UUID 与 Apple 导出无 UUID 的同一数据）；
  启动时会把旧类型（walkingspeed、activity_4 等）规范化为新名称并重建指纹。
- UI：`ui/pages.py` 的 MetricsPage（指标库）、SleepPage（Hypnogram）、Dashboard 活动圆环；
  `ui/charts.py` 的 RingMetric / Hypnogram / SleepStagesChart；
  `ui/floating.py` 的可选桌面悬浮球（悬停卡片、动态表情、位置记忆）。
- `ingest.py`：把快捷指令 JSON 归一化为样本/运动。没有 UUID 时用内容指纹生成稳定 UUID；
  运动去重指纹不包含来源（同一场训练可能来自 iPhone 与 Watch）。
- `db.py`：WAL SQLite，单连接 + `RLock`；`samples.uuid` 唯一索引实现幂等去重；
  `ai_reports` 保存周报与生成时的聚合上下文。
- `analytics.py`：累计型指标按「来源日合计取最大值」避免 iPhone + Watch 重复计数；
  睡眠按醒来日聚合，多来源取睡眠时长最大的来源。
- 时间戳统一存 UTC 秒，展示用本地时区；`util.parse_timestamp` 支持 ISO 8601 / 秒 / 毫秒。
- UI 为纯 PySide6 + 自绘图表，无 pyqtgraph/matplotlib；主题在 `ui/theme.py`。

## 约束与背景

- HealthKit 无公开云端 API，Windows 无法直接读取；免费方案：PulsHealth App（自动同步，推荐）
  或 iPhone 快捷指令（系统自带，需手工配置）。
- PulsHealth 免费版：自动同步最多 5 类、最近 30 天；局域网 HTTP 可用；后台调度由 iOS 决定。
- 全量/其他类型：Apple Health 导出导入（`export.zip`），手动 + 周/月提醒；跨通道按内容指纹去重。
- iOS 自动化没有「每小时」触发器，只能 24 条定点自动化或 Wi-Fi/充电触发；
  快捷指令每次拉最近 2 天，服务端去重，因此缺失触发不会丢数据。
- 不要将端口暴露到公网；Token 是唯一写入鉴权。
- AI 周报默认不联网；用户自填的模型 API Key 只存本机 `config.json`，不内置、不写日志；
  调用模型时只发送聚合统计，不发送原始样本。
- 悬浮球默认关闭，开启后只读本地 SQLite；位置存 `floating_x/floating_y`，不联网。
- mDNS 固定地址默认开启；名称由 Token 派生。换 Wi-Fi/IP 后自动重新广播，
  但公共 Wi-Fi 可能屏蔽组播，需保留 IP/配对二维码/热点/Tailscale 回退说明。
- 首次启动向导由 `onboarding_done` 控制；更新检查由 `update_check_enabled` /
  `last_update_check_ts` 控制，只访问 GitHub API，不自动下载安装。
- 公开分发需保留 `THIRD_PARTY_NOTICES.md` 与 `licenses/`（Qt/PySide6 LGPL 等合规）。
- 中文文案与格式化统一走 `util.py` 的辅助函数。

## 测试注意

- 测试直接导入核心模块，不创建 QApplication；Qt 相关代码只在 `ui/` 与 `app.py`。
- 服务端测试使用端口 0（系统分配）避免占用。
