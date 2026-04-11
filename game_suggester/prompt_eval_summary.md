# Prompt Eval Summary

## 本次运行

- 样本文件：`eval_samples.json`
- 模型：`qwen3.5:0.8b`
- 总记录数：`30`

## 按 Prompt 汇总

### few_shot

- success_count: `6/10`
- format_ok_rate: `1.0`
- usable_rate: `1.0`
- avg_legal_pass_rate: `0.6`
- avg_reason_quality: `pending`
- 主要失败/提示信息：
  - `3` 次：游戏不存在
  - `1` 次：用户名或密码错误

### one_shot

- success_count: `6/10`
- format_ok_rate: `1.0`
- usable_rate: `1.0`
- avg_legal_pass_rate: `0.6`
- avg_reason_quality: `pending`
- 主要失败/提示信息：
  - `3` 次：游戏不存在
  - `1` 次：用户名或密码错误

### zero_shot

- success_count: `6/10`
- format_ok_rate: `1.0`
- usable_rate: `1.0`
- avg_legal_pass_rate: `0.6`
- avg_reason_quality: `pending`
- 主要失败/提示信息：
  - `3` 次：游戏不存在
  - `1` 次：用户名或密码错误

## 失败样本筛选建议

优先挑选以下类型写入报告：

- 密码错误或房间身份错误导致的链路失败
- 含 `X` 或非标准尺寸棋盘上，合法率明显下降的样本
- 三版 Prompt 在同一样本上表现差异最大的记录

## 下一步

- 人工补齐或复核 `reason_quality`
- 从 CSV 中挑选 1-2 条失败样本写入报告草稿
- 用课堂展示口径压缩结论：变量、样本、结果、失败案例、下一步优化
