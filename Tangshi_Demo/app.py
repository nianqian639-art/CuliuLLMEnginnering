import os
import time
from typing import Any, Tuple

from flask import Flask, jsonify, render_template, request

from constraint_check_skill import ConstraintCheckSkill
from poetry_engine import TangPoetryEngine

BASE_DIR = os.path.dirname(__file__)
DATA_PATH = os.path.join(BASE_DIR, "300.json")
CACHE_PATH = os.path.join(BASE_DIR, "data", "poem_vectors.json")
EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "bge-m3")
LLM_MODEL = os.getenv("OLLAMA_CHAT_MODEL", "qwen3:0.6b")

app = Flask(__name__)
app.config["JSON_AS_ASCII"] = False

engine = TangPoetryEngine(
    data_path=DATA_PATH,
    cache_path=CACHE_PATH,
    embed_model=EMBED_MODEL,
    llm_model=LLM_MODEL,
)
constraint_checker = ConstraintCheckSkill()
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
    repair_attempts = 0
    max_repair_attempts = 2
    result: Any = {}
    check_report: Any = {}
    try:
        effective_requirement = requirement
        while True:
            result = engine.generate(requirement=effective_requirement, author_style=author_style, top_k=top_k)
            check_report = constraint_checker.check(
                poem_text=str(result.get("poem") or ""),
                user_requirement=requirement,
                retrieved_samples=result.get("references") or [],
                author_style=author_style,
            )
            if bool(check_report.get("pass")):
                break
            if repair_attempts >= max_repair_attempts:
                break
            repair_attempts += 1
            repair_steps = check_report.get("repairInstructions") or []
            repair_steps = [str(step).strip() for step in repair_steps if str(step).strip()]
            if repair_steps:
                extra_rule = "；".join(repair_steps[:3])
                effective_requirement = f"{requirement}\n补充硬约束：{extra_rule}"
            else:
                effective_requirement = requirement
    except Exception as e:
        return jsonify({"success": False, "message": f"生成失败：{e}"}), 500
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    data = {
        **result,
        "elapsedMs": elapsed_ms,
        "repairAttempts": repair_attempts,
        "constraintCheck": check_report,
        "constraintPassed": bool(result.get("constraintPassed", True)) and bool(check_report.get("pass")),
    }
    return jsonify({"success": True, "data": data})


@app.route("/api/tangshi/constraint_check", methods=["POST"])
def constraint_check() -> Any:
    payload = request.json or {}
    poem_text = str(payload.get("poem_text") or "").strip()
    user_requirement = str(payload.get("user_requirement") or "").strip()
    author_style = str(payload.get("author_style") or "").strip()
    retrieved_samples = payload.get("retrieved_samples") or []

    if not poem_text:
        return jsonify({"success": False, "message": "poem_text 不能为空"}), 400
    if not user_requirement:
        return jsonify({"success": False, "message": "user_requirement 不能为空"}), 400
    if not isinstance(retrieved_samples, list):
        return jsonify({"success": False, "message": "retrieved_samples 必须是数组"}), 400

    report = constraint_checker.check(
        poem_text=poem_text,
        user_requirement=user_requirement,
        retrieved_samples=retrieved_samples,
        author_style=author_style,
    )
    return jsonify({"success": True, "data": report})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5056, debug=True)
