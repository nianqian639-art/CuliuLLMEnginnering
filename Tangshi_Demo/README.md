# Tangshi_Demo

一个可直接运行的唐诗仿作网页 Demo：

- 向量模型：`bge-m3`（Ollama）
- 生成模型：`qwen3.5:0.8b`（Ollama）
- 后端：Flask
- 前端：原生 HTML/CSS/JS
- 数据：`300.json`（`title/author/paragraphs`）

## 1. 功能流程

1. 启动服务时读取 `300.json`
2. 用 `bge-m3` 对每首诗做 embedding
3. 向量缓存写入 `data/poem_vectors.json`
4. 用户在网页输入作诗要求并选择诗人风格
5. 后端把用户需求向量化并做 Top-K 相似检索
6. 把检索参考 + 风格要求拼接为 Prompt
7. 调用 `qwen3.5:0.8b` 生成仿作诗
8. 前端展示结果、参考诗作、耗时，以及最近几首原诗

## 2. 目录说明

- `app.py`：Flask 主程序与 API
- `poetry_engine.py`：数据加载、向量化、检索、生成
- `ollama_client.py`：Ollama 聊天与向量接口封装
- `300.json`：诗歌数据（示例文件，可替换成你的完整 300 首）
- `data/poem_vectors.json`：向量缓存（首次运行自动生成）
- `templates/index.html`：页面
- `static/app.js`：前端逻辑
- `static/style.css`：样式

## 3. 环境准备

安装 Python 依赖：

```bash
pip install -r requirements.txt
```

确保 Ollama 已启动并拉取模型：

```bash
ollama pull bge-m3
ollama pull qwen3.5:0.8b
ollama list
```

可选环境变量（按 `test_connect.py` 风格）：

```bash
# 默认就是 generate 输出模式，可不填
set OLLAMA_OUTPUT_MODE=generate

# 若你的网关要求 Bearer Token，可配置
set OLLAMA_API_TOKEN=你的token

# 如需切换地址/模型
set OLLAMA_BASE_URL=http://127.0.0.1:11434
set OLLAMA_CHAT_MODEL=qwen3.5:0.8b
set OLLAMA_EMBED_MODEL=bge-m3
```

## 4. 启动 Demo

```bash
python app.py
```

默认地址：`http://127.0.0.1:5056`

## 5. API 一览

### 5.1 健康检查

`GET /api/tangshi/health`

返回服务状态、诗歌数量、向量缓存状态、模型信息。

### 5.2 获取诗人列表

`GET /api/tangshi/authors`

用于前端“诗人风格”下拉框。

### 5.3 获取最近几首

`GET /api/tangshi/recent?limit=6`

说明：按 `300.json` 的末尾顺序取最近 N 首并返回。

### 5.4 生成仿作

`POST /api/tangshi/generate`

请求体示例：

```json
{
  "requirement": "写一首秋夜江边思乡的七言绝句",
  "author_style": "李白",
  "top_k": 5
}
```

返回示例（节选）：

```json
{
  "success": true,
  "data": {
    "poem": "江月随波照客舟，秋声一夜满汀洲。",
    "references": [
      {
        "id": 10,
        "title": "望天门山",
        "author": "李白",
        "score": 0.82
      }
    ],
    "models": {
      "llm": "qwen3.5:0.8b",
      "embedding": "bge-m3"
    },
    "elapsedMs": 1234
  }
}
```

## 6. 常见问题

- 如果首次启动较慢：属于诗集向量初始化，后续会读取缓存加速。
- 如果生成失败：检查 `ollama serve` 是否运行，模型名是否存在。
- 如果你有自己的 `300.json`：直接覆盖同名文件，保持字段为 `title/author/paragraphs`。
