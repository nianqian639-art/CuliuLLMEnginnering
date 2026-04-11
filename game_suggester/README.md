# game_suggester

`game_suggester` 是 Lesson 03 的课堂主线项目。它连接 `game_coach_game` 的实时房间，读取对局快照，调用本地大模型生成候选走法，再用 `evaluate_move` 二次校验，最后输出更可信的下一步建议。

这个项目现在同时承担两件事：

1. 作为可演示的建议器应用
2. 作为 Prompt 评测的最小闭环

## 已实现能力

- 输入游戏服务地址、账号、密码、房间号后，一键生成建议
- 后端先调用 `GET /api/coach/snapshot/<room_code>` 获取对局快照
- 使用 Prompt + Ollama 生成候选动作
- 对每条候选调用 `POST /api/coach/evaluate_move` 验证合法性与收益
- 输出最佳建议、备选建议、风险提示和置信度
- 当模型不可用或输出异常时，自动回退到启发式候选
- 支持 `promptVersion` 切换：`default / zero_shot / one_shot / few_shot`
- 支持 Lesson 03 批量评测：实时房间样本 + 静态快照样本

## 游戏规则摘要

- 棋盘是 `rows x cols`
- 只能在空格子落子
- 同一行、同一列的数字不能重复
- `X` 可以重复
- 通常只有整行或整列填满时才触发计分检查
- 建议器会优先考虑合法性、当前收益和后续延展空间

## 目录结构

```text
game_suggester/
├─ app.py
├─ templates/
│  └─ index.html
├─ static/
│  └─ app.js
├─ prompts/
│  └─ suggest_prompt.md
├─ prompt_versions/
│  ├─ zero_shot.md
│  ├─ one_shot.md
│  └─ few_shot.md
├─ evals/
│  ├─ eval_samples.json
│  └─ run_prompt_eval.py
├─ logs/
│  └─ test_log.md
├─ eval_plan.md
├─ prompt_eval_sheet_lesson03.csv
├─ prompt_eval_summary.md
├─ prompt_eval_report_draft.md
├─ personal_project_method_draft.md
└─ README.md
```

## 运行应用

在仓库根目录执行：

```bash
python game_suggester/app.py
```

打开：

- `http://127.0.0.1:5001`

默认页面参数：

- 游戏服务地址：`http://127.0.0.1:5000`
- 模型：`qwen3.5:0.8b`
- Prompt 版本：`default`

## API

### `POST /api/suggest`

请求体示例：

```json
{
  "gameBaseUrl": "http://127.0.0.1:5000",
  "username": "test1",
  "password": "1111",
  "roomCode": "1E4E9F",
  "model": "qwen3.5:0.8b",
  "promptVersion": "few_shot",
  "maxCandidates": 6
}
```

返回核心字段：

- `snapshotMeta`
- `bestSuggestion`
- `alternatives`
- `warnings`
- `promptVersion`
- `candidateCount`
- `legalCandidateCount`

### `GET /api/prompt_versions`

返回可用 Prompt 版本列表。

## Lesson 03 评测使用方式

课堂对比实验只改一个主变量：`prompt_version`。默认对比：

- `zero_shot`
- `one_shot`
- `few_shot`

评测样本定义在 [eval_samples.json](/c:/Users/dda1999/Documents/GitHub/CuliuLLMEnginnering/game_suggester/evals/eval_samples.json)。

批量评测脚本：

```bash
python game_suggester/evals/run_prompt_eval.py
```

常用参数：

```bash
python game_suggester/evals/run_prompt_eval.py --help
python game_suggester/evals/run_prompt_eval.py --prompt-versions zero_shot one_shot few_shot
python game_suggester/evals/run_prompt_eval.py --reason-quality-mode auto
```

默认输出：

- [prompt_eval_sheet_lesson03.csv](/c:/Users/dda1999/Documents/GitHub/CuliuLLMEnginnering/game_suggester/prompt_eval_sheet_lesson03.csv)
- [prompt_eval_summary.md](/c:/Users/dda1999/Documents/GitHub/CuliuLLMEnginnering/game_suggester/prompt_eval_summary.md)

## 课堂交付建议顺序

1. 先阅读 [eval_plan.md](/c:/Users/dda1999/Documents/GitHub/CuliuLLMEnginnering/game_suggester/eval_plan.md)
2. 确认评测样本和 Prompt 版本
3. 跑批量评测脚本生成 CSV 和 summary
4. 补人工 `reason_quality`
5. 完成 [prompt_eval_report_draft.md](/c:/Users/dda1999/Documents/GitHub/CuliuLLMEnginnering/game_suggester/prompt_eval_report_draft.md)
6. 从失败样本中挑 1-2 条做课堂展示

## 个人项目迁移

个人项目不必重写整套框架。建议直接复用：

- `zero/one/few` 的 Prompt 对比方法
- 样本分层思路
- CSV 记录字段
- 失败样本复盘模板
- 报告结构

参考草稿见 [personal_project_method_draft.md](/c:/Users/dda1999/Documents/GitHub/CuliuLLMEnginnering/game_suggester/personal_project_method_draft.md)。
