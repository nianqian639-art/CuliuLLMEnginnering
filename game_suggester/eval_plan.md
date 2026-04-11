# Lesson 03 - `game_suggester` 评测计划

## 1. 实验目标

本轮实验只比较一个主变量：`prompt_version`。

对比版本：

- `zero_shot`
- `one_shot`
- `few_shot`

保持不变的条件：

- 同一任务：下一步落子建议
- 同一模型：默认本地 Ollama 当前配置
- 同一批样本
- 同一评测脚本
- 同一指标口径

目标不是“我觉得哪个更好”，而是形成“有数据支撑的 Prompt 结论”。

## 2. 样本设计

样本文件：`evals/eval_samples.json`

样本按两类来源组织：

1. 实时房间样本
2. 静态快照样本

覆盖场景：

- 中局常见局面
- 稀疏盘面
- 密集盘面
- 含 `X` 的局面
- 非标准尺寸边界局面
- 明确失败场景

每条样本至少包含：

- `sample_id`
- `source_type`
- `scene_tags`
- `focus`
- 运行所需输入

## 3. 评测维度与判断标准

### `format_ok`

- `1`：返回可解析，且具备关键结构字段
- `0`：返回无法解析，或缺少关键字段

### `usable`

- `1`：有可展示建议，或虽然失败但给出明确可追踪原因
- `0`：结果不可用，无法支持分析

### `legal_pass_rate`

- 对候选列表中的 `isLegal=True` 做比例统计
- 无候选时记为 `0.0`

### `reason_quality`

使用固定 rubric，建议 0-2 分：

- `0`：理由空泛，几乎不解释“为什么这步可用”
- `1`：能说明部分合法性或局面因素，但不够具体
- `2`：能同时说明合法性、局面位置价值或后续风险

可先由脚本自动给出启发式分数，再人工复核。

## 4. 数据记录结构

明细 CSV 字段：

- `sample_id`
- `source_type`
- `scene_tags`
- `focus`
- `prompt_version`
- `model`
- `max_candidates`
- `status_code`
- `success`
- `format_ok`
- `usable`
- `candidate_count`
- `legal_candidate_count`
- `legal_pass_rate`
- `reason_quality`
- `best_value`
- `best_position`
- `best_source`
- `warning_count`
- `message`
- `notes`

失败样本补充字段：

- `failure_symptom`
- `suspected_root_cause`
- `fix_action`
- `retest_result`

## 5. 执行步骤

1. 确认三版 Prompt 文本不再混入乱码
2. 检查 `GET /api/prompt_versions` 能正确列出版本
3. 整理样本并运行批量评测脚本
4. 生成 `prompt_eval_sheet_lesson03.csv`
5. 人工补充或复核 `reason_quality`
6. 选 1-2 条失败样本，写入报告
7. 完成 `prompt_eval_summary.md` 与 `prompt_eval_report_draft.md`

## 6. 分工建议

- 同学 A：维护 Prompt 与样本设计
- 同学 B：运行评测脚本，整理 CSV
- 同学 C：写 summary、report 和展示口径

如果只有一个人完成，就按“样本 -> 运行 -> 复核 -> 写报告”的顺序推进。
