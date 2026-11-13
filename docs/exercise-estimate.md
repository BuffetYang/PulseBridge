# 锻炼分钟数估算

Apple 的 Exercise 圆环统计的是全天“中等强度及以上”的活动分钟数，具体算法没有公开。
PulseBridge 优先使用官方 **Exercise Time** 样本；没有时按下面的公开标准做本地估算，
界面会显示 `≈`，表示不是 Apple 官方值。

## 使用的信号

把一天按分钟切成 0–1439 的格子，以下任意一条成立就标记该分钟为锻炼，最后按分钟取并集，
同一分钟只计一次：

### 1. 心率储备（ACSM）

- 中等强度：40–59% 心率储备（HRR）
- 剧烈强度：60–89% HRR
- 公式：`目标心率 = 静息心率 + 百分比 × (最大心率 - 静息心率)`
- 静息心率优先用 Apple 的 Resting Heart Rate；没有时取当天心率的低分位。
- 最大心率默认按 **190 bpm** 估算（没有年龄字段）；有更准确年龄数据时结果会更好。

参考：ACSM 运动测试与处方指南中的心率储备强度划分。

### 2. 步频（Tudor-Locke 等）

- 约 **100 步/分** 接近中等强度（约 3 METs）
- 约 **130 步/分** 接近剧烈强度（约 6 METs）
- 按来源分别计算，每分钟取最大来源，避免 iPhone + Watch 重复计数。

参考：Tudor-Locke 等人关于步频与运动强度的研究；100 步/分常被用作“快走”阈值。

### 3. 活动能量换算 MET（WHO / Compendium）

- 使用最新体重（来自 Apple Health 体重记录）
- `MET = 活动 kcal/min × 200 / (3.5 × 体重kg) + 1`
- 中等强度 ≥3 METs，剧烈 ≥6 METs

参考：WHO 身体活动指南（中等 3–6 METs、剧烈 >6 METs）；Ainsworth《Compendium of
Physical Activities》的 MET 值。

### 4. 训练区间

Apple Watch 记录的 Workout 区间先按中等强度兜底；如果区间内的心率、步频或活动能量
更高，仍按剧烈计算。这样即使力量训练的平均心率不高，也不会完全不计入。

## 与官方数据的关系

最终取以下来源的较大值：

1. 官方 `Exercise Time`（如果 PulsHealth 同步了该类型）
2. 当天 `ActivitySummary.exerciseMin`（Apple 导出导入）
3. 本地估算（上面的分钟并集）

官方值胜出时显示普通数字；估算胜出时显示 `≈`，悬浮球和仪表盘的“锻炼”圆环都会有标记。

## 局限

- 最大心率固定 190，未按年龄/个体校正；
- 药物、疾病、腕表佩戴松紧都会影响心率；
- 力量、瑜伽等间歇活动的强度可能被高估或低估；
- 这是趋势参考，不是医疗测量，也不等同于 Apple 官方 Exercise 圆环。

想得到与 Apple 完全一致的数字，最可靠的方式是在 PulsHealth 的 5 类里选择
**Exercise Time（锻炼时间）**，或者定期导入 Apple Health 导出。

## 参考

- WHO《Guidelines on physical activity and sedentary behaviour》(2020)
- ACSM《Guidelines for Exercise Testing and Prescription》心率储备强度
- Ainsworth BE, et al. Compendium of Physical Activities
- Tudor-Locke C, et al. 步频与运动强度研究（100 / 130 步/分阈值）
- Apple Support：Apple Watch 活动圆环与锻炼时间说明
