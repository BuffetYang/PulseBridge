# AI 健康周报

PulseBridge 的周报有两种模式：

1. **本地规则（默认）**：不联网，直接用 7 天统计对比 30 天基线，生成中文周报。
2. **你自己的模型**：配置 OpenAI 兼容 API（GLM、DeepSeek、OpenAI 等）或本地 Ollama，
   把聚合统计发给模型生成更自然的解读。

程序**不内置任何 API Key**，也不会读取环境变量里的密钥；只有你在「模型设置」里填写并
点击「生成周报」后才会发起请求。

## 使用本地规则

打开 **AI 健康周报** → 直接点 **生成周报**。数据不会离开电脑。

## 配置智谱 GLM 免费 API

1. 在 [智谱开放平台](https://open.bigmodel.cn/) 注册并创建 API Key。
2. PulseBridge → **AI 健康周报** → **模型设置**。
3. 选择 **OpenAI 兼容 API**，点 **GLM-4.7-Flash** 或 **GLM-4.6V-Flash** 预设：
   - API 地址：`https://open.bigmodel.cn/api/paas/v4`
   - 模型：`glm-4.7-flash`（GLM-4.7-Flash，免费文本模型，推荐用于周报）
     或 `glm-4.6v-flash`（GLM-4.6V-Flash，免费多模态模型；周报只需要文本）。
     如果平台调整了免费模型名称，按控制台显示的填写。
4. 粘贴你的 API Key，点 **测试连接**。
5. 保存后点 **生成周报**。

> 免费模型的可用性、速率限制和额度由智谱平台决定。遇到 429 表示触发限流，
> 稍后再试或换用其他模型。

## 配置本地 Ollama

1. 安装 [Ollama](https://ollama.com/) 并拉取一个模型，例如：
   ```bash
   ollama pull qwen2.5:7b
   ```
2. PulseBridge → **模型设置** → **本地 Ollama** → **Ollama 预设**：
   - API 地址：`http://127.0.0.1:11434`
   - 模型：`qwen2.5:7b`（或你已安装的模型名）
3. **测试连接** → 保存 → 生成周报。

Ollama 不需要 API Key；生成时不会出本机。

## 其他 OpenAI 兼容服务

选择 **OpenAI 兼容 API**，API 地址填写服务商的 Base URL，例如：

- OpenAI：`https://api.openai.com/v1`
- DeepSeek：`https://api.deepseek.com/v1`（模型 `deepseek-flash`，即 DeepSeek V4.1 Flash）
  - 注意：DeepSeek API **不是免费**的，需要账户余额；余额不足时测试会报
    `Insufficient Balance`。
  - V4.1 Flash 默认开启思考模式；连接测试使用较大 token 上限，若模型只返回思考内容
    也会视为连接成功。
- 其他服务：填到 `/v1` 或服务商要求的版本路径，程序会自动追加
  `/chat/completions`；也可以直接填完整的 `.../chat/completions` 地址。

模型名称按服务商文档填写。

## 隐私

- 默认规则模式完全不联网。
- 调用模型时只发送 **7/30 天的聚合统计**（平均值、总量、睡眠时长、训练次数等），
  不发送原始心率/睡眠样本，也不发送姓名等身份信息。
- API Key 保存在本机 `%APPDATA%\PulseBridge\config.json`，不会写入日志或 JSON 导出。
  每个 API 地址的 Key/模型会分别保存，切换 GLM / DeepSeek / Ollama 后自动恢复。
- 周报内容保存在本地 SQLite 的 `ai_reports` 表，可随时复制或导出 Markdown。
- 如果使用云端 API，数据会发送给对应服务商，请自行确认其隐私政策。

## 排错

| 现象 | 处理 |
| --- | --- |
| 401 / invalid api key | 检查 Key 是否复制完整、是否与 Base URL 匹配 |
| 402 / Insufficient Balance | DeepSeek 等账户余额不足；充值或改用 GLM 免费模型/Ollama |
| 404 / model not found | 模型名写错，或该模型未开通 |
| 429 / rate limit | 免费额度或频率限制，稍后再试或换模型 |
| 连接超时 | 检查网络、代理；云端服务需要能访问对应域名 |
| model not found | 模型名写错，或 Ollama 还没 `pull` 该模型 |
| 模型失败但仍有报告 | 程序会自动回退到本地规则版，并在状态栏显示原因 |

## 免责声明

周报基于统计趋势，不构成医疗诊断或治疗建议。如有持续不适或异常指标，请咨询专业医生。
