import os
import time
from typing import Any, Tuple

from flask import Flask, jsonify, render_template, request

from poetry_engine import TangPoetryEngine

BASE_DIR = os.path.dirname(__file__)
DATA_PATH = os.path.join(BASE_DIR, "300.json")
CACHE_PATH = os.path.join(BASE_DIR, "data", "poem_vectors.json")
EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "bge-m3")
LLM_MODEL = os.getenv("OLLAMA_CHAT_MODEL", "qwen3.5:0.8b")

app = Flask(__name__)
app.config["JSON_AS_ASCII"] = False

engine = TangPoetryEngine(
    data_path=DATA_PATH,
    cache_path=CACHE_PATH,
    embed_model=EMBED_MODEL,
    llm_model=LLM_MODEL,
)
build_info = None
build_error = ""


def ensure_engine_ready() -> Tuple[bool, str]:
    global build_info
    global build_error
    if build_info is not None and not build_error:
        return True, ""
    try:
        build_info = engine.build()
        build_error = ""
        return True, ""
    except Exception as e:
        build_error = str(e)
        return False, build_error


@app.route("/")
def index() -> Any:
    return render_template("index.html")


@app.route("/api/tangshi/health", methods=["GET"])
def health() -> Any:
    ready, err = ensure_engine_ready()
    return jsonify(
        {
            "success": True,
            "data": {
                "status": "ok" if ready else "degraded",
                "poemCount": len(engine.poems),
                "authorCount": len(engine.list_authors()) if ready else 0,
                "vectorReady": len(engine.vectors) == len(engine.poems),
                "cachePath": CACHE_PATH,
                "models": {"llm": LLM_MODEL, "embedding": EMBED_MODEL},
                "buildInfo": build_info,
                "buildError": err,
            },
        }
    )


@app.route("/api/tangshi/authors", methods=["GET"])
def authors() -> Any:
    ready, err = ensure_engine_ready()
    if not ready:
        return jsonify({"success": False, "message": f"初始化失败：{err}"}), 503
    return jsonify({"success": True, "data": {"authors": engine.list_authors()}})


@app.route("/api/tangshi/recent", methods=["GET"])
def recent() -> Any:
    ready, err = ensure_engine_ready()
    if not ready:
        return jsonify({"success": False, "message": f"初始化失败：{err}"}), 503
    limit_raw = request.args.get("limit", "5")
    try:
        limit = int(limit_raw)
    except Exception:
        return jsonify({"success": False, "message": "limit 必须是整数"}), 400
    poems = engine.recent_poems(limit=limit)
    return jsonify({"success": True, "data": {"items": poems, "count": len(poems)}})


@app.route("/api/tangshi/generate", methods=["POST"])
def generate() -> Any:
    ready, err = ensure_engine_ready()
    if not ready:
        return jsonify({"success": False, "message": f"初始化失败：{err}"}), 503

    payload = request.json or {}
    requirement = str(payload.get("requirement") or "").strip()
    author_style = str(payload.get("author_style") or "").strip()
    try:
        top_k = int(payload.get("top_k") or 5)
    except Exception:
        return jsonify({"success": False, "message": "top_k 必须是整数"}), 400

    if top_k < 1 or top_k > 10:
        return jsonify({"success": False, "message": "top_k 取值范围为 1-10"}), 400

    if not requirement:
        return jsonify({"success": False, "message": "requirement 不能为空"}), 400

    started = time.perf_counter()
    try:
        result = engine.generate(requirement=requirement, author_style=author_style, top_k=top_k)
    except Exception as e:
        return jsonify({"success": False, "message": f"生成失败：{e}"}), 500
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    return jsonify({"success": True, "data": {**result, "elapsedMs": elapsed_ms}})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5056, debug=True)
