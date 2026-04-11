# 个人项目方法迁移草稿

## 目标

个人项目本轮不重写整套系统，先复用 `game_suggester` 的评测方法。

## 最小迁移步骤

1. 定义一个新的最小 Prompt 任务
2. 为这个任务准备 `zero_shot / one_shot / few_shot`
3. 设计 6-10 条样本
4. 复用相同字段记录 CSV
5. 复用失败样本模板和报告模板

## 推荐可迁移的骨架

- `eval_plan.md` 的结构
- 样本分层方法
- `format_ok / usable / legal_pass_rate / reason_quality`
- 失败样本复盘格式
- summary + report 的写法

## 可选的个人项目题目

- 用 `agent_minimal` 做“工具调用是否正确”的 Prompt 对比
- 做一个小型分类或抽取任务的 Prompt 对比
- 做一个固定格式 JSON 输出任务的 Prompt 对比

## 个人项目最小交付

- 任务定义
- 三版 Prompt
- 一组样本
- 一轮 CSV 结果
- 1 条失败样本
- 一版报告草稿
