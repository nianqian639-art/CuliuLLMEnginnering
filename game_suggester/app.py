import json
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import requests
from flask import Flask, jsonify, render_template, request


DEFAULT_GAME_BASE_URL = os.getenv("GAME_BASE_URL", "http://127.0.0.1:5000")
DEFAULT_OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
DEFAULT_MODEL = os.getenv("OLLAMA_MODEL", "qwen3.5:0.8b")
DEFAULT_TIMEOUT = float(os.getenv("GAME_TIMEOUT_SECONDS", "12"))
MODEL_TIMEOUT = float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "90"))
DEFAULT_MAX_CANDIDATES = int(os.getenv("SUGGESTER_MAX_CANDIDATES", "6"))

PROMPT_PATH = os.path.join(os.path.dirname(__file__), "prompts", "suggest_prompt.md")
PROMPT_VERSIONS_DIR = os.path.join(os.path.dirname(__file__), "prompt_versions")
DEFAULT_PROMPT_VERSION = os.getenv("SUGGESTER_PROMPT_VERSION", "default")

app = Flask(__name__)
app.config["JSON_AS_ASCII"] = False


@dataclass
class Candidate:
    row: int
    col: int
    value: str
    reason: str
    risk: str
    source: str


def build_url(base_url: str, path: str) -> str:
    return base_url.rstrip("/") + path


def available_prompt_versions() -> List[str]:
    versions = ["default"]
    if os.path.isdir(PROMPT_VERSIONS_DIR):
        for name in os.listdir(PROMPT_VERSIONS_DIR):
            if name.endswith(".md"):
                versions.append(name[:-3])
    return sorted(set(versions))


def resolve_prompt_path(prompt_version: str) -> str:
    version = (prompt_version or "default").strip().lower()
    if version == "default":
        return PROMPT_PATH
    candidate = os.path.join(PROMPT_VERSIONS_DIR, f"{version}.md")
    if os.path.isfile(candidate):
        return candidate
    raise ValueError(
        f"promptVersion '{prompt_version}' 不存在，可用版本：{', '.join(available_prompt_versions())}"
    )


def read_prompt_template(prompt_version: str = "default") -> str:
    path = resolve_prompt_path(prompt_version)
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def parse_bool_env(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def parse_json_strict_or_embedded(text: str) -> Dict[str, Any]:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    fenced = re.search(r"```(?:json)?\s*(\{[\s\S]*\})\s*```", text, flags=re.IGNORECASE)
    if fenced:
        return json.loads(fenced.group(1))
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        return json.loads(text[start : end + 1])
    raise ValueError("model output is not valid json")


def ollama_chat_json(system_prompt: str, user_prompt: str, model: str) -> Dict[str, Any]:
    think_enabled = parse_bool_env("OLLAMA_THINKING", default=False)
    final_user_prompt = user_prompt if think_enabled else "/no_think\n" + user_prompt

    payload_chat = {
        "model": model,
        "stream": False,
        "think": think_enabled,
        "thinking": think_enabled,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": final_user_prompt},
        ],
        "options": {"temperature": 0.2},
    }
    r = requests.post(
        build_url(DEFAULT_OLLAMA_BASE_URL, "/api/chat"),
        json=payload_chat,
        timeout=MODEL_TIMEOUT,
    )
    if r.status_code == 404:
        payload_generate = {
            "model": model,
            "stream": False,
            "think": think_enabled,
            "thinking": think_enabled,
            "prompt": f"[SYSTEM]\n{system_prompt}\n\n[USER]\n{final_user_prompt}",
            "options": {"temperature": 0.2},
        }
        r = requests.post(
            build_url(DEFAULT_OLLAMA_BASE_URL, "/api/generate"),
            json=payload_generate,
            timeout=MODEL_TIMEOUT,
        )
        if r.status_code == 404:
            payload_openai_compat = {
                "model": model,
                "temperature": 0.2,
                "think": think_enabled,
                "thinking": think_enabled,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": final_user_prompt},
                ],
            }
            r = requests.post(
                build_url(DEFAULT_OLLAMA_BASE_URL, "/v1/chat/completions"),
                json=payload_openai_compat,
                timeout=MODEL_TIMEOUT,
            )
            r.raise_for_status()
            text = (
                r.json().get("choices", [{}])[0].get("message", {}).get("content", "").strip()
            )
            return parse_json_strict_or_embedded(text)
        r.raise_for_status()
        text = r.json().get("response", "").strip()
        return parse_json_strict_or_embedded(text)

    r.raise_for_status()
    text = r.json().get("message", {}).get("content", "").strip()
    return parse_json_strict_or_embedded(text)


def login_game(session: requests.Session, base_url: str, username: str, password: str) -> Dict[str, Any]:
    r = session.post(
        build_url(base_url, "/api/login"),
        json={"username": username, "password": password},
        timeout=DEFAULT_TIMEOUT,
    )
    r.raise_for_status()
    data = r.json()
    if not data.get("success"):
        raise ValueError(data.get("message", "login failed"))
    return data


def fetch_snapshot(session: requests.Session, base_url: str, room_code: str) -> Dict[str, Any]:
    r = session.get(build_url(base_url, f"/api/coach/snapshot/{room_code}"), timeout=DEFAULT_TIMEOUT)
    r.raise_for_status()
    data = r.json()
    if not data.get("success"):
        raise ValueError(data.get("message", "snapshot failed"))
    return data["snapshot"]


def evaluate_move(
    session: requests.Session,
    base_url: str,
    room_code: str,
    row: int,
    col: int,
    value: str,
) -> Dict[str, Any]:
    r = session.post(
        build_url(base_url, "/api/coach/evaluate_move"),
        json={"roomCode": room_code, "row": row, "col": col, "value": value},
        timeout=DEFAULT_TIMEOUT,
    )
    r.raise_for_status()
    data = r.json()
    if not data.get("success"):
        raise ValueError(data.get("message", "evaluate_move failed"))
    return data["evaluation"]


def normalize_candidate(raw: Dict[str, Any], source: str) -> Optional[Candidate]:
    try:
        row = int(raw.get("row"))
        col = int(raw.get("col"))
    except Exception:
        return None
    value_raw = raw.get("value")
    if value_raw is None:
        return None
    value = str(value_raw).strip()
    if not value:
        return None
    reason = str(raw.get("reason", "")).strip() or "模型给出的候选走法"
    risk = str(raw.get("risk", "")).strip() or "可能存在规则冲突或收益不稳定"
    return Candidate(row=row, col=col, value=value, reason=reason, risk=risk, source=source)


def model_candidates(
    snapshot: Dict[str, Any], model: str, max_candidates: int, prompt_version: str
) -> Tuple[List[Candidate], str]:
    prompt_template = read_prompt_template(prompt_version=prompt_version)
    snapshot_json = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"))
    user_prompt = (
        prompt_template.replace("{{MAX_CANDIDATES}}", str(max_candidates)).replace(
            "{{SNAPSHOT_JSON}}", snapshot_json
        )
    )
    system_prompt = "你是严谨的游戏建议助手。必须输出可解析 JSON，不要输出额外文本。"
    parsed = ollama_chat_json(system_prompt=system_prompt, user_prompt=user_prompt, model=model)
    raw_list = parsed.get("candidates", [])
    if not isinstance(raw_list, list):
        return [], "模型返回格式不符合预期，已启用兜底"
    out: List[Candidate] = []
    for item in raw_list:
        if isinstance(item, dict):
            c = normalize_candidate(item, source="model")
            if c:
                out.append(c)
    if not out:
        return [], "模型未给出有效候选，已启用兜底"
    return out, ""


def line_has_digit(line: List[Any], value: str) -> bool:
    for cell in line:
        if not cell:
            continue
        cell_val = str(cell.get("value"))
        if cell_val.lower() == "x":
            continue
        if cell_val == value:
            return True
    return False


def heuristic_candidates(snapshot: Dict[str, Any], limit: int = 20) -> List[Candidate]:
    grid = snapshot["grid"]
    rows = len(grid)
    cols = len(grid[0]) if rows else 0
    value_candidates = [str(i) for i in range(1, max(rows, cols) + 1)] + ["X"]

    moves: List[Tuple[float, Candidate]] = []
    for r in range(rows):
        for c in range(cols):
            if grid[r][c] is not None:
                continue
            row_line = grid[r]
            col_line = [grid[x][c] for x in range(rows)]
            row_fill = sum(1 for cell in row_line if cell is not None)
            col_fill = sum(1 for cell in col_line if cell is not None)
            for value in value_candidates:
                if value.lower() != "x":
                    if line_has_digit(row_line, value) or line_has_digit(col_line, value):
                        continue
                score = (row_fill + col_fill) * 1.6
                if value.lower() == "x":
                    score -= 0.8
                reason = (
                    f"优先补充接近完成的线（行已占 {row_fill}/{cols}，列已占 {col_fill}/{rows}）"
                )
                risk = "若后续无法形成 value=n 的触发格，得分可能不高"
                moves.append(
                    (score, Candidate(row=r, col=c, value=value, reason=reason, risk=risk, source="heuristic"))
                )
    moves.sort(key=lambda x: x[0], reverse=True)
    return [item[1] for item in moves[:limit]]


def dedupe_candidates(cands: List[Candidate]) -> List[Candidate]:
    seen = set()
    out: List[Candidate] = []
    for c in cands:
        key = (c.row, c.col, c.value)
        if key in seen:
            continue
        seen.add(key)
        out.append(c)
    return out


def expected_turn_username(snapshot: Dict[str, Any]) -> Optional[str]:
    turn = snapshot.get("currentTurn")
    if turn == "player1":
        return snapshot.get("player1")
    if turn == "player2":
        return snapshot.get("player2")
    return None


def compute_confidence(
    is_model_used: bool,
    legal_count: int,
    top_net_gain: int,
    username_matches_turn: bool,
) -> float:
    conf = 0.45
    if is_model_used:
        conf += 0.15
    conf += min(0.2, legal_count * 0.04)
    conf += min(0.15, max(0, top_net_gain) * 0.05)
    if not username_matches_turn:
        conf -= 0.25
    return max(0.05, min(0.95, conf))


def rank_results(
    evaluated: List[Dict[str, Any]],
    current_turn: str,
) -> List[Dict[str, Any]]:
    other = "player2" if current_turn == "player1" else "player1"

    def score_tuple(item: Dict[str, Any]) -> Tuple[int, int, int, int]:
        ev = item["evaluation"]
        legal = 1 if ev.get("isLegal") else 0
        delta = ev.get("scoreDelta", {})
        self_gain = int(delta.get(current_turn, 0))
        opp_gain = int(delta.get(other, 0))
        net = self_gain - opp_gain
        non_x_bonus = 1 if str(item["candidate"]["value"]).lower() != "x" else 0
        return (legal, net, self_gain, non_x_bonus)

    return sorted(evaluated, key=score_tuple, reverse=True)


def snapshot_meta(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    grid = snapshot["grid"]
    rows = len(grid)
    cols = len(grid[0]) if rows else 0
    occupied = sum(1 for row in grid for cell in row if cell is not None)
    return {
        "roomCode": snapshot.get("roomCode"),
        "gameId": snapshot.get("gameId"),
        "rulesVersion": snapshot.get("rulesVersion"),
        "status": snapshot.get("status"),
        "rows": rows,
        "cols": cols,
        "occupiedCells": occupied,
        "currentTurn": snapshot.get("currentTurn"),
        "player1": snapshot.get("player1"),
        "player2": snapshot.get("player2"),
        "player1Score": snapshot.get("player1Score"),
        "player2Score": snapshot.get("player2Score"),
    }


def suggest(
    game_base_url: str,
    username: str,
    password: str,
    room_code: str,
    model: str,
    max_candidates: int,
    prompt_version: str = "default",
) -> Dict[str, Any]:
    session = requests.Session()
    login_game(session, game_base_url, username, password)
    snapshot = fetch_snapshot(session, game_base_url, room_code)

    warnings: List[str] = []
    expected_user = expected_turn_username(snapshot)
    username_matches_turn = expected_user == username
    if expected_user and expected_user != username:
        warnings.append(
            f"当前回合应由 {expected_user} 操作，你当前登录为 {username}。评估结果可能与真实下一手存在偏差。"
        )

    model_err = ""
    model_used = True
    try:
        model_cands, model_err = model_candidates(
            snapshot, model=model, max_candidates=max_candidates, prompt_version=prompt_version
        )
    except Exception as e:
        model_cands = []
        model_err = f"模型调用失败：{e}"
        model_used = False
    if model_err:
        warnings.append(model_err)

    heuristics = heuristic_candidates(snapshot, limit=max(12, max_candidates * 2))
    all_candidates = dedupe_candidates(model_cands + heuristics)
    all_candidates = all_candidates[: max(20, max_candidates * 3)]

    evaluated: List[Dict[str, Any]] = []
    for c in all_candidates:
        try:
            ev = evaluate_move(session, game_base_url, room_code, c.row, c.col, c.value)
            evaluated.append(
                {
                    "candidate": {
                        "row": c.row,
                        "col": c.col,
                        "value": c.value,
                        "reason": c.reason,
                        "risk": c.risk,
                        "source": c.source,
                    },
                    "evaluation": ev,
                }
            )
        except Exception as e:
            evaluated.append(
                {
                    "candidate": {
                        "row": c.row,
                        "col": c.col,
                        "value": c.value,
                        "reason": c.reason,
                        "risk": c.risk,
                        "source": c.source,
                    },
                    "evaluation": {
                        "isLegal": False,
                        "reason": f"评估请求失败：{e}",
                        "reasonCode": "EVAL_REQUEST_FAILED",
                        "scoreDelta": {"player1": 0, "player2": 0},
                        "nextTurn": snapshot.get("currentTurn"),
                        "turnSkipped": False,
                    },
                }
            )

    ranked = rank_results(evaluated, current_turn=snapshot["currentTurn"])
    legal_only = [x for x in ranked if x["evaluation"].get("isLegal")]
    if not legal_only:
        top = ranked[0] if ranked else None
        return {
            "success": False,
            "message": "未找到合法候选，请检查房间状态或更换账号后重试",
            "warnings": warnings,
            "promptVersion": prompt_version,
            "snapshotMeta": snapshot_meta(snapshot),
            "bestAttempt": top,
            "candidates": ranked[:max_candidates],
            "legalCandidateCount": len(legal_only),
        }

    best = legal_only[0]
    current_turn = snapshot["currentTurn"]
    other = "player2" if current_turn == "player1" else "player1"
    best_delta = best["evaluation"].get("scoreDelta", {})
    top_net_gain = int(best_delta.get(current_turn, 0)) - int(best_delta.get(other, 0))
    confidence = compute_confidence(
        is_model_used=model_used and any(c["candidate"]["source"] == "model" for c in ranked),
        legal_count=len(legal_only),
        top_net_gain=top_net_gain,
        username_matches_turn=username_matches_turn,
    )
    best["confidence"] = round(confidence, 2)

    return {
        "success": True,
        "promptVersion": prompt_version,
        "snapshotMeta": snapshot_meta(snapshot),
        "bestSuggestion": best,
        "alternatives": legal_only[1:max_candidates],
        "warnings": warnings,
        "candidateCount": len(ranked),
        "legalCandidateCount": len(legal_only),
    }




@app.route("/")
def index() -> Any:
    return render_template("index.html")


@app.route("/api/suggest", methods=["POST"])
def api_suggest() -> Any:
    data = request.json or {}
    game_base_url = str(data.get("gameBaseUrl") or DEFAULT_GAME_BASE_URL).strip()
    username = str(data.get("username") or "").strip()
    password = str(data.get("password") or "").strip()
    room_code = str(data.get("roomCode") or "").strip()
    model = str(data.get("model") or DEFAULT_MODEL).strip()
    prompt_version = str(data.get("promptVersion") or DEFAULT_PROMPT_VERSION).strip()
    max_candidates = int(data.get("maxCandidates") or DEFAULT_MAX_CANDIDATES)

    if not username or not password or not room_code:
        return (
            jsonify(
                {
                    "success": False,
                    "message": "username/password/roomCode 不能为空",
                }
            ),
            400,
        )

    try:
        result = suggest(
            game_base_url=game_base_url,
            username=username,
            password=password,
            room_code=room_code,
            model=model,
            max_candidates=max_candidates,
            prompt_version=prompt_version,
        )
        return jsonify(result)
    except ValueError as e:
        return jsonify({"success": False, "message": str(e)}), 400
    except requests.HTTPError as e:
        return jsonify({"success": False, "message": f"HTTP error: {e}"}), 502
    except requests.RequestException as e:
        return jsonify({"success": False, "message": f"网络请求失败: {e}"}), 502
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/api/prompt_versions", methods=["GET"])
def api_prompt_versions() -> Any:
    return jsonify(
        {
            "success": True,
            "default": DEFAULT_PROMPT_VERSION,
            "versions": available_prompt_versions(),
        }
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=True)

