import json
import os
import re
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

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


def evaluate_move_remote(
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


def normalize_cell_value(cell: Any) -> Optional[str]:
    if cell is None:
        return None
    if isinstance(cell, dict):
        raw = cell.get("value")
    else:
        raw = cell
    if raw is None:
        return None
    text = str(raw).strip()
    return text or None


def normalize_grid(grid: List[List[Any]]) -> List[List[Optional[Dict[str, str]]]]:
    normalized: List[List[Optional[Dict[str, str]]]] = []
    for row in grid:
        normalized_row: List[Optional[Dict[str, str]]] = []
        for cell in row:
            value = normalize_cell_value(cell)
            normalized_row.append(None if value is None else {"value": value})
        normalized.append(normalized_row)
    return normalized


def coerce_snapshot(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    normalized = dict(snapshot)
    normalized["grid"] = normalize_grid(snapshot["grid"])
    normalized.setdefault("roomCode", snapshot.get("roomCode") or "STATIC")
    normalized.setdefault("gameId", snapshot.get("gameId") or f"static-{uuid.uuid4().hex[:8]}")
    normalized.setdefault("rulesVersion", snapshot.get("rulesVersion") or "static-v1")
    normalized.setdefault("status", snapshot.get("status") or "IN_PROGRESS")
    normalized.setdefault("currentTurn", snapshot.get("currentTurn") or "player1")
    normalized.setdefault("player1", snapshot.get("player1") or "player1")
    normalized.setdefault("player2", snapshot.get("player2") or "player2")
    normalized.setdefault("player1Score", int(snapshot.get("player1Score") or 0))
    normalized.setdefault("player2Score", int(snapshot.get("player2Score") or 0))
    return normalized


def evaluate_move_static(
    snapshot: Dict[str, Any],
    row: int,
    col: int,
    value: str,
) -> Dict[str, Any]:
    grid = snapshot["grid"]
    rows = len(grid)
    cols = len(grid[0]) if rows else 0
    value_text = str(value).strip()

    if row < 0 or col < 0 or row >= rows or col >= cols:
        return {
            "isLegal": False,
            "reason": "坐标越界",
            "reasonCode": "INVALID_POSITION",
            "scoreDelta": {"player1": 0, "player2": 0},
            "nextTurn": snapshot.get("currentTurn"),
            "turnSkipped": False,
        }
    if grid[row][col] is not None:
        return {
            "isLegal": False,
            "reason": "该格子已经有值",
            "reasonCode": "CELL_OCCUPIED",
            "scoreDelta": {"player1": 0, "player2": 0},
            "nextTurn": snapshot.get("currentTurn"),
            "turnSkipped": False,
        }
    if not value_text:
        return {
            "isLegal": False,
            "reason": "缺少落子值",
            "reasonCode": "INVALID_VALUE",
            "scoreDelta": {"player1": 0, "player2": 0},
            "nextTurn": snapshot.get("currentTurn"),
            "turnSkipped": False,
        }
    if value_text.lower() != "x":
        for c, cell in enumerate(grid[row]):
            if c == col or cell is None:
                continue
            if str(cell.get("value")) == value_text:
                return {
                    "isLegal": False,
                    "reason": "同行数字重复",
                    "reasonCode": "ROW_DUPLICATE",
                    "scoreDelta": {"player1": 0, "player2": 0},
                    "nextTurn": snapshot.get("currentTurn"),
                    "turnSkipped": False,
                }
        for r, row_cells in enumerate(grid):
            cell = row_cells[col]
            if r == row or cell is None:
                continue
            if str(cell.get("value")) == value_text:
                return {
                    "isLegal": False,
                    "reason": "同列数字重复",
                    "reasonCode": "COL_DUPLICATE",
                    "scoreDelta": {"player1": 0, "player2": 0},
                    "nextTurn": snapshot.get("currentTurn"),
                    "turnSkipped": False,
                }

    next_turn = "player2" if snapshot.get("currentTurn") == "player1" else "player1"
    return {
        "isLegal": True,
        "reason": "静态样本规则校验通过",
        "reasonCode": "OK",
        "scoreDelta": {"player1": 0, "player2": 0},
        "nextTurn": next_turn,
        "turnSkipped": False,
    }


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
    reason = str(raw.get("reason", "")).strip() or "模型给出了这个候选走法。"
    risk = str(raw.get("risk", "")).strip() or "可能存在规则冲突，或后续收益不稳定。"
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
        return [], "模型返回格式不符合预期，已启用规则兜底。"

    out: List[Candidate] = []
    for item in raw_list:
        if isinstance(item, dict):
            candidate = normalize_candidate(item, source="model")
            if candidate:
                out.append(candidate)

    if not out:
        return [], "模型没有给出有效候选，已启用规则兜底。"
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
                    f"优先补接近完成的线：该行已占 {row_fill}/{cols}，该列已占 {col_fill}/{rows}。"
                )
                risk = "如果后续无法形成触发得分的整行或整列，这步的收益可能有限。"
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


def build_no_legal_result(
    snapshot: Dict[str, Any],
    prompt_version: str,
    warnings: List[str],
    ranked: List[Dict[str, Any]],
    legal_only: List[Dict[str, Any]],
    max_candidates: int,
) -> Dict[str, Any]:
    top = ranked[0] if ranked else None
    return {
        "success": False,
        "message": "未找到合法候选，请检查房间状态、样本定义或当前账号身份。",
        "warnings": warnings,
        "promptVersion": prompt_version,
        "snapshotMeta": snapshot_meta(snapshot),
        "bestAttempt": top,
        "candidates": ranked[:max_candidates],
        "legalCandidateCount": len(legal_only),
    }


def suggest_from_snapshot(
    snapshot: Dict[str, Any],
    model: str,
    max_candidates: int,
    prompt_version: str = "default",
    username: Optional[str] = None,
    evaluator: Optional[Callable[[int, int, str], Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    snapshot = coerce_snapshot(snapshot)
    warnings: List[str] = []
    expected_user = expected_turn_username(snapshot)
    username_matches_turn = True

    if username:
        username_matches_turn = expected_user == username
        if expected_user and expected_user != username:
            warnings.append(
                f"当前回合应由 {expected_user} 操作，你当前使用的是 {username}。评估结果可能与真实下一手存在偏差。"
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

    if evaluator is None:
        evaluator = lambda row, col, value: evaluate_move_static(snapshot, row, col, value)

    evaluated: List[Dict[str, Any]] = []
    for c in all_candidates:
        try:
            ev = evaluator(c.row, c.col, c.value)
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
    legal_only = [item for item in ranked if item["evaluation"].get("isLegal")]
    if not legal_only:
        return build_no_legal_result(
            snapshot,
            prompt_version,
            warnings,
            ranked,
            legal_only,
            max_candidates,
        )

    best = legal_only[0]
    current_turn = snapshot["currentTurn"]
    other = "player2" if current_turn == "player1" else "player1"
    best_delta = best["evaluation"].get("scoreDelta", {})
    top_net_gain = int(best_delta.get(current_turn, 0)) - int(best_delta.get(other, 0))
    confidence = compute_confidence(
        is_model_used=model_used and any(item["candidate"]["source"] == "model" for item in ranked),
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

    def remote_evaluator(row: int, col: int, value: str) -> Dict[str, Any]:
        return evaluate_move_remote(session, game_base_url, room_code, row, col, value)

    return suggest_from_snapshot(
        snapshot=snapshot,
        model=model,
        max_candidates=max_candidates,
        prompt_version=prompt_version,
        username=username,
        evaluator=remote_evaluator,
    )


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
        return jsonify({"success": False, "message": f"网络请求失败：{e}"}), 502
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
