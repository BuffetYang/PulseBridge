"""应用内「iPhone 快捷指令」配置指南。"""

from __future__ import annotations

import html
import json


def shortcut_payload_template(base_url: str) -> dict:
    """一份可直接用 curl 测试的示例载荷。"""
    return {
        "device": "iPhone",
        "sent_at": "2026-11-12T08:00:00+08:00",
        "samples": [
            {
                "type": "heart_rate",
                "start": "2026-11-12T07:55:00+08:00",
                "end": "2026-11-12T07:56:00+08:00",
                "value": 72,
                "unit": "count/min",
                "source": "Apple Watch",
            },
            {
                "type": "steps",
                "start": "2026-11-12T07:00:00+08:00",
                "end": "2026-11-12T08:00:00+08:00",
                "value": 860,
                "unit": "count",
                "source": "Apple Watch",
            },
        ],
        "workouts": [],
    }


def build_puls_guide_html(base_url: str, token: str) -> str:
    """应用内 PulsHealth（免费自动同步 App）配置指南。"""
    safe_base = html.escape(base_url)
    safe_token = html.escape(token)
    return f"""
<style>
  body {{ color: #D7E1EC; font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif;
         font-size: 13px; line-height: 1.65; }}
  h2 {{ color: #EAF0F7; font-size: 17px; margin: 20px 0 8px; }}
  h3 {{ color: #3DDC97; font-size: 14px; margin: 18px 0 6px; }}
  p, li {{ color: #B9C7D8; }}
  code {{ color: #7CF0BF; background: #0B1A14; font-family: Consolas, monospace; }}
  pre {{ background: #0B121B; color: #C8D5E4; border: 1px solid #1E2B3A;
         padding: 10px; font-family: Consolas, monospace; font-size: 12px; }}
  .tip {{ color: #FFB347; }}
  .dim {{ color: #7F90A5; }}
</style>

<h2>PulsHealth：免费的自动同步（推荐）</h2>
<p>PulsHealth 是开源、免费的 iPhone App。免费版可以<strong>自动后台同步 5 类数据</strong>，
不需要手动搭快捷指令，也不需要付费订阅。PulseBridge 已经内置了它的接收协议。</p>

<h3>1. 安装 App</h3>
<p>在 App Store 搜索 <strong>PulsHealth</strong> 并免费下载（iOS 17+）。</p>

<h3>2. 填写你的数据库地址</h3>
<ol>
  <li>打开 PulsHealth → 底部 <strong>Sync（同步）</strong>
      → <strong>Database（数据库）</strong> → <strong>Your Own Database（自己的数据库）</strong>。</li>
  <li>Database URL 填：<br><code>{safe_base}</code><br>
      <span class="dim">只填到端口，不要加 /v1/batches；PulsHealth 会自动追加。</span></li>
  <li>Token 填：<br><code>{safe_token}</code><br>
      <span class="dim">这是 PulseBridge「访问令牌」里的值，点「复制」获取。</span></li>
  <li>点 <strong>Test Connection</strong>，成功后点 <strong>Save &amp; Apply</strong>。</li>
</ol>

<h3>3. 选择同步类型</h3>
<p>免费版最多选 <strong>5 类</strong>。推荐：</p>
<ul>
  <li>心率（Heart Rate）</li>
  <li>步数（Steps）</li>
  <li>睡眠（Sleep）</li>
  <li>活动能量（Active Energy）</li>
  <li>体能训练（Workouts）</li>
</ul>
<p>在 PulsHealth 的 Health Access 页面把对应健康类别全部允许。
如果还需要静息心率、HRV、血氧，可以替换上面某一项（免费版总数仍为 5）。</p>

<h3>4. 自动同步</h3>
<p>PulsHealth 通过 HealthKit 后台投递自动上传；iOS 的调度不是严格整点，可能延迟。
电脑休眠时收不到，唤醒后下一次同步会补。首次连接通常会回填最近 30 天的数据，
数据多时请等几分钟，或在 App 内手动触发一次。</p>

<h3>验证</h3>
<p>电脑端「同步与配对 → 最近同步」出现 <strong>PulsHealth</strong> 记录，
仪表盘出现数据即成功。协议请求走 <code>/v1/batches</code>，按样本 UUID 去重。</p>

<h3>排错</h3>
<ul>
  <li><strong>401</strong>：Token 不一致，重新从 PulseBridge 复制并 Save &amp; Apply。</li>
  <li><strong>连接失败</strong>：确认 iPhone 与电脑在同一 Wi-Fi、电脑未休眠；
      可点「修复防火墙」；Database URL 必须是 <code>http://局域网IP:8765</code>，
      PulsHealth 对局域网地址允许 HTTP。</li>
  <li><strong>没有数据</strong>：检查 Health Access 权限和同步类型是否勾选；
      免费版只同步最近 30 天。</li>
  <li><strong>只有部分指标</strong>：免费版最多 5 类，且你选择的类型才会同步。</li>
</ul>
"""


def build_guide_html(base_url: str, token: str) -> str:
    endpoint = f"{base_url}/api/ingest"
    template = json.dumps(shortcut_payload_template(base_url), ensure_ascii=False, indent=2)
    safe_endpoint = html.escape(endpoint)
    safe_token = html.escape(token)
    safe_template = html.escape(template)
    return f"""
<style>
  body {{ color: #D7E1EC; font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif;
         font-size: 13px; line-height: 1.65; }}
  h2 {{ color: #EAF0F7; font-size: 17px; margin: 20px 0 8px; }}
  h3 {{ color: #3DDC97; font-size: 14px; margin: 18px 0 6px; }}
  p, li {{ color: #B9C7D8; }}
  code {{ color: #7CF0BF; background: #0B1A14; font-family: Consolas, monospace; }}
  pre {{ background: #0B121B; color: #C8D5E4; border: 1px solid #1E2B3A;
         padding: 10px; font-family: Consolas, monospace; font-size: 12px; }}
  .tip {{ color: #FFB347; }}
  .dim {{ color: #7F90A5; }}
</style>

<h2>把 iPhone 健康数据接入 PulseBridge</h2>
<p>整个方案完全免费：iPhone 自带的「快捷指令」读取 HealthKit 数据，通过同一 Wi-Fi
用 HTTP 把 JSON 发到这台电脑。电脑端程序已在监听，你只需要在手机上建一条快捷指令。</p>

<h3>0. 先确认连接</h3>
<ol>
  <li>iPhone 和这台电脑连接<strong>同一个 Wi-Fi</strong>（不要连访客网络）。</li>
  <li>用 iPhone Safari 打开 <code>{html.escape(base_url)}</code>，能看到「接收服务运行中」即连通。</li>
  <li>如果打不开：点击「同步与配对」页的「<strong>修复防火墙</strong>」并同意 UAC
      （Windows 常把 Wi-Fi 识别为公用网络，默认拦截入站且不会弹提示）；
      同时确认路由器没有开启「AP 隔离」。</li>
  <li>如果电脑安装了 VMware / VirtualBox，地址列表里会出现虚拟网卡地址
      （常见为 192.168.x.1，手机无法访问）。请在「网络地址」下拉框中切换到
      默认路由 / Wi-Fi 网卡对应的地址。</li>
  <li>Windows 电脑休眠时无法接收；唤醒后手机下一次同步会自动补齐。</li>
</ol>
<p class="tip">如果 Safari 提示「无法与服务器建立安全的连接」：这是 iOS 18.2+ 的 Safari
把 http:// 自动升级成了 https://（PulseBridge 是 HTTP 服务）。请到
「设置 → App → Safari 浏览器 → 隐私与安全性」，关闭「不安全连接警告」
（Not Secure Connection Warning），彻底退出 Safari 后重试；也可以跳过 Safari 验证，
直接在快捷指令里用 http 地址运行一次——快捷指令不受 Safari 的 HTTPS 升级影响，
电脑端「最近同步」出现记录就说明成功。</p>

<h3>0.5 先用快捷指令测试连通性（推荐，不依赖 Safari）</h3>
<p>如果在 Safari 中打不开，或者找不到「不安全连接警告」设置，可以完全跳过 Safari，
用一条只有两个动作的临时快捷指令验证。</p>
<ol>
  <li>打开「快捷指令」→ 新建，命名「PulseBridge 测试」。</li>
  <li>搜索并添加「<strong>获取 URL 内容</strong>」（Get Contents of URL），
      URL 填 <code>{html.escape(base_url)}/api/ping</code>，方法保持 GET。</li>
  <li>搜索并添加「<strong>快速查看</strong>」或「<strong>显示结果</strong>」，
      把上一步的「内容」作为输入。</li>
  <li>运行。首次会请求「本地网络」和「连接到 192.168.x.x」权限，全部允许。</li>
  <li>看到类似 <code>{{"ok": true, "app": "PulseBridge"}}</code> 的 JSON 即连通，
      说明手机、Wi-Fi、防火墙、IP 全部正常。之后按下面的步骤建正式快捷指令即可。</li>
</ol>
<p class="tip">如果这一步报错，请把完整报错文字告诉我；如果是「安全连接」相关错误，
说明 iOS 27 的 Shortcuts 也对明文 HTTP 做了限制，需要改用 HTTPS 方案。</p>

<h3>0.6 极简 POST 测试（验证 Token 与入库）</h3>
<p>连通性没问题后，用一条硬编码样本验证 POST、Token 和数据库。
<strong>不需要添加日期动作</strong>——极简格式里 start/end 可以省略，服务端会用接收时间。</p>
<ol>
  <li>添加（或修改现有的）「<strong>获取 URL 内容</strong>」：
    <ul>
      <li>URL：<code>{safe_endpoint}</code>；方法：<strong>POST</strong></li>
      <li>请求头：<code>X-PulseBridge-Token</code> = <code>{safe_token}</code></li>
      <li>请求体：<strong>JSON</strong>，添加以下字段：
        <pre>device → 文本 iPhone
type   → 文本 heart_rate
value  → 数字 72
unit   → 文本 count/min
source → 文本 快捷指令测试</pre>
      </li>
    </ul>
  </li>
  <li>运行。电脑端「最近同步」出现「+1 样本」，仪表盘出现当前时间的心率点，
      说明 POST、Token、入库全部正常。</li>
</ol>
<p class="dim">start/end 不是必填；正式同步时它们来自健康样本本身的起止时间。
如果手动填写，需要使用 ISO 8601 格式（例如 2026-11-12T23:30:00+08:00）。</p>

<h3>1. 新建快捷指令</h3>
<p>打开「快捷指令」App → 右上角 <strong>+</strong> → 命名为「同步健康数据到 PulseBridge」。</p>

<h3>2. 采集健康样本（建议先做 4 个指标）</h3>
<p>对「心率、步数、活动能量、睡眠」四个指标各重复一次下面的结构（之后可再加
静息心率、HRV、血氧、呼吸频率、体重等）：</p>
<ol>
  <li>添加「<strong>查找健康样本</strong>」：类型选「心率」；筛选「开始日期 在最近 2 天」；
      排序「开始日期，最新在前」；限制 1000。</li>
  <li>添加「<strong>重复</strong>」，重复「健康样本」。</li>
  <li>在循环内添加「<strong>获取健康样本详细信息</strong>」，样本选「重复项目」。</li>
  <li>在循环内添加「<strong>词典</strong>」，添加这些键值（值从详细信息里选）：
    <pre>type    → 文本 heart_rate
start   → 详细信息.开始日期
end     → 详细信息.结束日期
value   → 详细信息.数值
unit    → 详细信息.单位
source  → 详细信息.来源</pre>
    <span class="dim">其他指标只需把 type 换成：
    steps（步数）、active_energy（活动能量）、resting_heart_rate（静息心率）、
    hrv（心率变异性）、oxygen_saturation（血氧）、respiratory_rate（呼吸频率）、
    body_mass（体重）。</span></li>
  <li>在循环内添加「<strong>添加到变量</strong>」，变量名填 <code>样本</code>，
      值选刚建的词典。循环外添加「结束重复」。</li>
</ol>
<p class="tip">睡眠：同样用「查找健康样本」，类型选「睡眠」，最近 2 天。
详细信息里的「值」会是 Core / Deep / REM / 清醒 / 核心 / 深度 等文本，
直接作为 value 发送即可，程序会自动识别阶段并按起止时间计算时长。</p>
<p class="dim">提示：每个指标都要有自己的「查找 → 重复 → 词典 → 添加到变量」块，
所有块都往同一个「样本」变量里追加。变量类型会自动变成列表，这是正常的。</p>

<h3>3. 采集运动记录（可选但推荐）</h3>
<ol>
  <li>添加「<strong>查找体能训练</strong>」：筛选「开始日期 在最近 2 天」。</li>
  <li>添加「<strong>重复</strong>」。</li>
  <li>循环内添加「<strong>获取体能训练的详细信息</strong>」，属性选「类型」「开始日期」「结束日期」「持续时间」。</li>
  <li>循环内添加「<strong>词典</strong>」：
    <pre>type      → 详细信息.类型
start     → 详细信息.开始日期
end       → 详细信息.结束日期
duration_s→ 详细信息.持续时间
source    → 文本 Apple Watch</pre>
    距离、活动能量、平均心率可选：分别加 <code>distance_m</code>、
    <code>energy_kcal</code>、<code>avg_hr</code> 键。</li>
  <li>循环内「<strong>添加到变量</strong>」，变量名 <code>运动</code>；循环外「结束重复」。</li>
</ol>

<h3>4. 发送到电脑</h3>
<ol>
  <li>添加「<strong>词典</strong>」，建立最终请求体：
    <pre>device  → 文本 iPhone
samples → 变量 样本
workouts→ 变量 运动</pre>
    <span class="dim">如果某个指标暂时没做，对应变量可以留空或删除该键。</span></li>
  <li>添加「<strong>获取 URL 内容</strong>」：
    <ul>
      <li>URL：<code>{safe_endpoint}</code></li>
      <li>方法：<strong>POST</strong></li>
      <li>请求头：<code>X-PulseBridge-Token</code> = <code>{safe_token}</code></li>
      <li>请求体：<strong>JSON</strong> → 选上一步的词典</li>
    </ul>
  </li>
  <li>点「运行」测试。电脑端「同步与配对」页会出现一条同步记录，仪表盘开始有数据。</li>
</ol>

<h3>5. 设置自动同步</h3>
<p>iOS 的自动化没有「每小时」间隔触发器，推荐两种组合：</p>
<ul>
  <li><strong>定点同步</strong>：快捷指令 → 自动化 → 新建 → 「时间」→ 例如 08:00 → 每天 →
      立即运行 → 选择这条快捷指令。需要每小时就复制 24 条（或只建白天 8:00–23:00 的 16 条）。</li>
  <li><strong>事件触发</strong>（更省事）：再建「连接家庭 Wi-Fi 时」和「开始充电时」两条自动化，
      都指向同一条快捷指令。每次执行都会拉最近 2 天数据，服务端按 UUID 去重，
      所以不会重复，也不会因为漏掉某小时而丢数据。</li>
</ul>
<p>首次运行时 iOS 会请求「本地网络」和「健康」权限，请全部允许。健康权限路径：
设置 → 隐私与安全性 → 健康 → 快捷指令 → 打开所有需要的类别。</p>

<h3>6. 电脑端手动测试（可选）</h3>
<p>在 PowerShell 中执行下面的命令，如果返回 <code>"ok": true</code> 说明服务正常：</p>
<pre>curl.exe -X POST "{safe_endpoint}" ^
  -H "Content-Type: application/json" ^
  -H "X-PulseBridge-Token: {safe_token}" ^
  -d "{html.escape(json.dumps(shortcut_payload_template(base_url), ensure_ascii=False))}"</pre>

<h3>附：完整 JSON 示例</h3>
<pre>{safe_template}</pre>

<p class="dim">排错：401 表示 token 不一致（在「同步与配对」页复制最新 token）；
无法连接表示两台设备不在同一网络或被防火墙拦截；仪表盘无数据请检查健康权限与筛选时间范围。</p>
"""
