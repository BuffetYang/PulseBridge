# PulseBridge

**本地优先的 Apple 健康数据看板（Windows 桌面端）。**

PulseBridge 让你的 iPhone / Apple Watch 健康与运动数据自动出现在 Windows 上：
电脑端内置一个局域网接收服务，iPhone 自带的「快捷指令」定时把 HealthKit 数据以 JSON
POST 过来，程序归一化后存入本地 SQLite，并用一个精致的深色仪表盘展示。

- **完全免费**：不依赖任何付费 App，只使用 iOS 自带的快捷指令。
- **本地优先**：数据只存在你的电脑上，不上传云端，不注册账号。
- **开箱即用**：单个桌面程序，内置接收服务、托盘常驻、开机自启、二维码配对。
- **为 AI 打底**：结构化存储 + 一键导出 JSON，后续可接入大模型做健康分析。

<p align="center">
  <img src="docs/screenshots/dashboard.png" width="49%" alt="仪表盘">
  <img src="docs/screenshots/sync.png" width="49%" alt="同步与配对">
</p>

<p align="center">
  <img src="docs/screenshots/trends.png" width="49%" alt="趋势">
  <img src="docs/screenshots/workouts.png" width="49%" alt="运动记录">
</p>

---

## 数据流

```
 Apple Watch / iPhone 健康 App
            │  HealthKit
            ▼
 iOS「快捷指令」（免费，定时运行）
   Find Health Samples / Find Workouts
            │  HTTP POST JSON（同一 Wi-Fi）
            ▼
 ┌───────────────────────────────┐
 │  PulseBridge（Windows 桌面端） │
 │  ├─ 内置 HTTP 接收服务 :8765   │
 │  ├─ 归一化 + 去重 + SQLite     │
 │  └─ PySide6 仪表盘 / 托盘      │
 └───────────────────────────────┘
```

> **为什么不能直连？** Apple HealthKit 没有公开的云端 API，任何 Windows 程序都无法
> 直接读取 iPhone 的健康数据库。必须由手机侧 App 主动导出，快捷指令是目前唯一
> 免费、原生、可定制的通道。

## 功能

- **仪表盘**：今日步数、静息心率、最近睡眠、活动能量；24 小时心率曲线、7 天步数、
  睡眠阶段分布、最近运动。
- **趋势**：9 种指标的 7 / 30 / 90 天趋势，自动区分「按日累计」与「按日平均」。
- **运动记录**：跑步、骑行、力量训练等，含时长、距离、消耗、平均心率。
- **同步与配对**：局域网地址、Token、二维码、最近同步日志、已接收指标统计。
- **系统托盘**：关闭窗口不退出，后台持续接收；可设置开机自启。
- **AI 洞察（预留）**：数据摘要与 JSON 导出，后续接入大模型分析。

## 支持的数据

| 快捷指令类型 | 归一化类型 | 用途 |
| --- | --- | --- |
| 心率 | `heart_rate` | 24 小时曲线、日平均 |
| 静息心率 | `resting_heart_rate` | 恢复状态 |
| 心率变异性 | `hrv` | 压力 / 恢复 |
| 步数 | `steps` | 每日步数与目标 |
| 活动能量 | `active_energy` | 每日消耗与目标 |
| 睡眠 | `sleep_analysis` | 深睡 / 核心 / REM / 清醒 |
| 血氧 | `oxygen_saturation` | 趋势 |
| 呼吸频率 | `respiratory_rate` | 趋势 |
| 体重 | `body_mass` | 趋势 |
| 体能训练 | `workouts` | 运动记录 |

## 快速开始

环境：Windows 10/11，Python 3.12+，[uv](https://docs.astral.sh/uv/)。

```bash
uv sync
uv run pulsebridge
```

首次启动会：

1. 在 `%APPDATA%\PulseBridge\` 生成配置与数据库；
2. 在 `0.0.0.0:8765` 启动接收服务（Windows 防火墙弹窗请允许**专用网络**）；
3. 打开仪表盘。在「同步与配对」页可以看到局域网地址、Token 和二维码。

接着在 iPhone 上配置快捷指令：见
[docs/iphone-shortcuts.md](docs/iphone-shortcuts.md)，或在程序内点击
**「打开 iPhone 配置指南」**（指南已自动填入你的地址与 Token）。

> 手机与电脑必须在同一个 Wi-Fi。iOS 自动化没有「每小时」触发器，
> 推荐「连接家庭 Wi-Fi / 开始充电 / 若干定点时间」组合触发；每次同步最近 2 天数据，
> 服务端按 UUID 去重，因此漏掉某次触发也不会丢数据。

## 常用命令

```bash
uv run pulsebridge                 # 启动桌面程序
uv run pulsebridge --minimized     # 直接进入托盘
uv run pytest                      # 运行测试
uv run python -m pulsebridge --port 9000
```

数据目录（可用 `PULSEBRIDGE_HOME` 覆盖）：

```
%APPDATA%\PulseBridge\
├── config.json      # 端口、Token、启动偏好
└── pulsebridge.db   # SQLite（WAL）
```

## 打包为 exe

```bash
uv add --dev pyinstaller
uv run python scripts/make_icon.py            # 生成 assets/pulsebridge.ico
uv run pyinstaller --noconfirm --windowed --name PulseBridge \
  --icon assets/pulsebridge.ico \
  --collect-submodules PySide6 \
  scripts/run_app.py
```

产物在 `dist/PulseBridge/`。建议将整个目录压缩分发，首次运行仍会请求防火墙权限。

## 开发

```
src/pulsebridge/
├── app.py            # QApplication 入口
├── server.py         # 内置 HTTP 服务 + 鉴权 + 状态页
├── ingest.py         # JSON 归一化（支持原生格式 / Health Auto Export 风格）
├── db.py             # SQLite 存储与查询
├── analytics.py      # 日汇总、睡眠夜间聚合、心率序列
├── config.py         # 配置与 Token
├── startup.py        # Windows 开机自启
├── guide.py          # 应用内快捷指令指南
└── ui/
    ├── main_window.py# 侧边栏 / 页面栈 / 托盘
    ├── pages.py      # 仪表盘、趋势、运动、同步、AI、设置
    ├── charts.py     # 自绘折线 / 柱状 / 迷你图 / 睡眠阶段条
    ├── widgets.py    # 卡片、指标卡、复制行、空状态
    ├── theme.py      # 深色主题 QSS
    └── icons.py      # 程序图标
```

测试：

```bash
uv run pytest -q
```

## 隐私与安全

- 所有数据保存在本机 SQLite，无遥测、无云端上传。
- 接收服务监听局域网，使用随机 Token 鉴权；请求体上限 25 MB。
- **不要**在路由器上做端口映射 / 公网暴露。
- 导出的 JSON 包含完整健康数据，请自行妥善保管。

## 路线图

- [x] 局域网接收、去重、SQLite
- [x] 仪表盘 / 趋势 / 运动 / 同步 / 设置
- [x] 托盘常驻、开机自启、二维码配对
- [x] 数据导出，为 AI 分析做准备
- [ ] AI 周报：睡眠、恢复、训练负荷解读（可选接入云端或本地模型）
- [ ] 异常波动提醒
- [ ] 多设备 / 家庭成员支持

## License

MIT
