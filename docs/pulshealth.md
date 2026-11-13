# PulsHealth 自动同步（推荐）

PulsHealth 是一款开源、免费的 iPhone App（App Store 免费下载），可以把 Apple Health
数据自动同步到你自己的服务器。PulseBridge 已内置它的接收协议
（Puls Sync Protocol v1 的 `POST /v1/batches`），因此**不需要手搭快捷指令**。

- **免费版**：自动后台同步最多 **5 类**数据，覆盖最近 **30 天**
- **局域网 HTTP**：PulsHealth 允许本地网络使用 `http://`，不需要证书
- **无账号、无中转**：数据从 iPhone 直接发到你的电脑
- **自动同步**：HealthKit 后台投递；iOS 决定调度时机，不保证严格整点
- Pro 是可选升级（更多类型 / 更长历史），本方案不需要

> 协议与 App：<https://github.com/pulshealth/pulshealth>（Apache-2.0）。
> 本文以 App 1.6+/2.x 的界面为例，菜单文案可能随版本略有变化。

---

## 1. 准备

1. iPhone 与 Windows 电脑连接**同一个 Wi-Fi**。
2. 电脑上运行 PulseBridge，确认「同步与配对」页显示：
   - 网络地址：例如 `192.168.31.111`（不要选 VMware 虚拟网卡）
   - 访问令牌（Token）
3. 如果之前点过「修复防火墙」，入站规则已放行；否则可让 iPhone 与电脑同网段访问。
   PulsHealth 对**局域网地址**允许 HTTP，无需 HTTPS。

## 2. 在 PulsHealth 里添加服务器

1. App Store 搜索 **PulsHealth**，免费安装（iOS 17+）。
2. 打开 App → 底部 **Sync（同步）** → **Database（数据库）**
   → **Your Own Database（自己的数据库）**。
3. 填写：
   - **Database URL**：`http://192.168.31.111:8765`
     - 只填到端口，**不要**加 `/v1/batches`（App 会自动追加）
     - 必须用电脑的 Wi-Fi 地址，不能用 `127.0.0.1`
   - **Token**：PulseBridge「访问令牌」里的值
4. 点 **Test Connection**。成功后会显示服务器信息（PulseBridge 实现了
   `GET /v1/capabilities`）。
5. 点 **Save & Apply**。

> 如果界面还要求 User ID，可留空；PulsHealth 会发送自己的用户 ID，
> PulseBridge 单用户接收，不校验该字段。

## 3. 选择同步类型（免费版最多 5 类）

推荐这 5 类，正好覆盖看板：

| 看板模块 | PulsHealth 类型 |
| --- | --- |
| 心率曲线 | Heart Rate（心率） |
| 今日步数 | Steps（步数） |
| 最近睡眠 | Sleep（睡眠） |
| 活动能量 | Active Energy（活动能量） |
| 运动记录 | Workouts（体能训练） |

在 **Health Access** 页面允许对应类别。若更想要静息心率、HRV、血氧或体重，
可以替换上表中的某一项；免费版总数仍是 5 类。

> 如果没有勾选静息心率，PulseBridge 会在官方样本缺失的日期用**睡眠期间的心率估算**，
> 界面上显示为 `≈` 和「估算」。这是近似值（与 Apple 算法一般相差几 bpm），
> 需要精确数据时仍建议勾选 Resting Heart Rate。

## 4. 开启自动同步

PulsHealth 通过 HealthKit 后台投递 + 后台任务上传，无需快捷指令：

- iOS 会按系统策略调度，可能延迟或不严格整点；打开 App 或充电时通常会更积极。
- 电脑休眠时无法接收，唤醒后 App 会重试并补齐。
- 首次连接会回填最近 30 天；数据量大时等几分钟，或在 App 内手动触发一次同步。
- 免费版历史窗口为 30 天；更久历史需要 Pro（本方案不要求）。

## 5. 验证

1. 电脑端「同步与配对 → 最近同步」出现 **PulsHealth** 记录，显示 `+N 样本`。
2. 仪表盘出现心率/步数/睡眠/活动能量，运动页出现训练。
3. 可以在 PulsHealth 的 Sync 日志里看到 HTTP 200。

后台批量接口：

```
POST http://192.168.31.111:8765/v1/batches
Authorization: Bearer <Token>
Content-Type: application/x-ndjson
Content-Encoding: gzip
X-Puls-Protocol: 1
```

PulseBridge 按样本 UUID 幂等入库，重复批次不会重复计数。

## 6. 排错

| 现象 | 处理 |
| --- | --- |
| Test Connection 401 | Token 不一致：重新从 PulseBridge 复制，Save & Apply |
| Test Connection 连接失败 | 确认同一 Wi-Fi、电脑未休眠、地址是 Wi-Fi 网卡 IP；可点「修复防火墙」；不要用 https |
| 只有部分指标 | 免费版最多 5 类，只同步你勾选的类型；检查 Health Access 权限 |
| 没有数据 / 延迟 | 打开 PulsHealth 手动同步一次；iOS 后台调度可能延后；免费版只回填 30 天 |
| 步数偏少 | PulseBridge 按「同一来源日合计」统计，避免 iPhone + Watch 重复；确认 Watch 数据已同步到健康 App |
| 睡眠没有深睡/REM | PulsHealth 发送的是 HealthKit 睡眠分类；需 Apple Watch 开启睡眠跟踪 |

### 手机熄屏后会停止同步吗？

不会因为「锁屏」本身停止。PulsHealth 使用 HealthKit 后台投递，锁屏/切后台时仍可能收到
新数据并尝试上传；但 iOS 对后台执行有调度和限流，实际会**延迟**，不是持续实时：

- 开启「设置 → 通用 → 后台 App 刷新 → PulsHealth」；
- 关闭低电量模式（低电量会明显限制后台任务）；
- **不要**从多任务界面强制上滑关闭 PulsHealth，强制退出后系统不会再唤醒它；
- 电脑休眠/关机时上传会失败，App 会保留游标，下次联网/唤醒后重试并补齐；
- 如果几小时没有新数据，打开 PulsHealth 一次触发同步即可，历史数据不会丢。

### 控制台出现 ConnectionResetError / WinError 10054

这是 iPhone 在请求过程中主动断开连接（熄屏、切后台、Wi-Fi 切换、App 被系统挂起）导致的，
**不影响已经收到的数据**，也不需要处理。新版 PulseBridge 已经把这类正常的客户端断开
静默，不再打印 traceback。

## 7. 隐私

- PulsHealth 从 HealthKit 只读，不写回；数据直接发到你的电脑。
- PulseBridge 只监听局域网，Token 用于写入鉴权；不要做公网端口映射。
- PulsHealth 本身不含第三方统计/广告；其 Pro 订阅与本方案无关。

## 8. 与快捷指令方案的关系

两条通道可以同时使用，数据按 UUID 去重：

- **PulsHealth**：推荐，安装 App 后自动同步。
- **快捷指令**：完全自带、无需安装第三方 App，但需要手工搭建动作。
  见 [iphone-shortcuts.md](iphone-shortcuts.md)。
- **Apple Health 导出导入**：免费、全量类型/全部历史，手动 + 周/月提醒。
  见 [health-export-import.md](health-export-import.md)。跨通道重复数据会按内容指纹去重。
