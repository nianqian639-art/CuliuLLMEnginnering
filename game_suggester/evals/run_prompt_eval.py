import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Tuple

import requests


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game_suggester.app import DEFAULT_MAX_CANDIDATES, DEFAULT_MODEL, suggest, suggest_from_snapshot


GAME_SUGGESTER_DIR = Path(__file__).resolve().parents[1]
DEFAULT_SAMPLES_PATH = GAME_SUGGESTER_DIR / "evals" / "eval_samples.json"
DEFAULT_CSV_PATH = GAME_SUGGESTER_DIR / "prompt_eval_sheet_lesson03.csv"
DEFAULT_SUMMARY_PATH = GAME_SUGGESTER_DIR / "prompt_eval_summary.md"
DEFAULT_PROMPT_VERSIONS = ["zero_shot", "one_shot", "few_shot"]

CSV_FIELDS = [
    "sample_id",
    "source_type",
    "scene_tags",
    "focus",
    "prompt_version",
    "model",
    "max_candidates",
    "status_code",
    "success",
    "format_ok",
    "usable",
    "candidate_count",
    "legal_candidate_count",
    "legal_pass_rate",
    "reason_quality",
    "best_value",
    "best_position",
    "best_source",
    "warning_count",
    "message",
    "notes",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Lesson 03 prompt evaluation for game_suggester.")
    parser.add_argument("--samples", default=str(DEFAULT_SAMPLES_PATH))
    parser.add_argument("--csv-out", default=str(DEFAULT_CSV_PATH))
    parser.add_argument("--summary-out", default=str(DEFAULT_SUMMARY_PATH))
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--prompt-versions", nargs="+", default=DEFAULT_PROMPT_VERSIONS)
    parser.add_argument("--max-candidates", type=int, default=DEFAULT_MAX_CANDIDATES)
    parser.add_argument(
        "--reason-quality-mode",
        choices=["pending", "auto"],
        default="pending",
        help="pending: leave blank for manual review; auto: fill a heuristic 0-2 score.",
    )
    return parser.parse_args()


def load_samples(path: Path) -> List[Dict[str, Any]]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def compute_reason_quality(result: Dict[str, Any]) -> str:
    best = result.get("bestSuggestion") or {}
    candidate = best.get("candidate") or {}
    reason = str(candidate.get("reason") or "").strip()
    risk = str(candidate.get("risk") or "").strip()
    text = f"{reason} {risk}".strip()
    if not reason or not risk:
        return "0"
    if len(text) < 20:
        return "1"
    return "2"


def compute_metrics(result: Dict[str, Any], reason_quality_mode: str) -> Dict[str, Any]:
    format_ok = int(
        isinstance(result, dict)
        and isinstance(result.get("snapshotMeta"), dict)
        and ("bestSuggestion" in result or "bestAttempt" in result or "message" in result)
    )

    candidate_count = int(result.get("candidateCount") or len(result.get("candidates") or []))
    legal_count = int(result.get("legalCandidateCount") or 0)
    legal_pass_rate = round((legal_count / candidate_count), 3) if candidate_count else 0.0
    message = str(result.get("message") or "")
    usable = int(bool(result.get("success")) or bool(message))

    best = result.get("bestSuggestion") or result.get("bestAttempt") or {}
    best_candidate = best.get("candidate") or {}
    best_position = ""
    if "row" in best_candidate and "col" in best_candidate:
        best_position = f"({best_candidate['row']},{best_candidate['col']})"

    reason_quality = ""
    if reason_quality_mode == "auto" and result.get("success"):
        reason_quality = compute_reason_quality(result)

    return {
        "format_ok": format_ok,
        "usable": usable,
        "candidate_count": candidate_count,
        "legal_candidate_count": legal_count,
        "legal_pass_rate": legal_pass_rate,
        "reason_quality": reason_quality,
        "best_value": str(best_candidate.get("value") or ""),
        "best_position": best_position,
        "best_source": str(best_candidate.get("source") or ""),
        "warning_count": len(result.get("warnings") or []),
        "message": message,
    }


def safe_run_sample(
    sample: Dict[str, Any],
    prompt_version: str,
    model: str,
    max_candidates: int,
) -> Tuple[int, Dict[str, Any]]:
    try:
        source_type = sample["source_type"]
        if source_type == "live_room":
            result = suggest(
                game_base_url=sample["game_base_url"],
                username=sample["username"],
                password=sample["password"],
                room_code=sample["room_code"],
                model=model,
                max_candidates=int(sample.get("max_candidates") or max_candidates),
                prompt_version=prompt_version,
            )
        elif source_type == "static_snapshot":
            snapshot = sample["snapshot"]
            current_turn = snapshot.get("currentTurn", "player1")
            username = snapshot.get("player1") if current_turn == "player1" else snapshot.get("player2")
            result = suggest_from_snapshot(
                snapshot=snapshot,
                model=model,
                max_candidates=int(sample.get("max_candidates") or max_candidates),
                prompt_version=prompt_version,
                username=username,
            )
        else:
            raise ValueError(f"unsupported source_type: {source_type}")
        return 200, result
    except ValueError as e:
        return 400, {"success": False, "message": str(e), "snapshotMeta": {}, "warnings": []}
    except requests.RequestException as e:
        return 502, {"success": False, "message": str(e), "snapshotMeta": {}, "warnings": []}
    except Exception as e:
        return 500, {"success": False, "message": str(e), "snapshotMeta": {}, "warnings": []}


def write_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def build_summary(rows: List[Dict[str, Any]], samples_path: Path, model: str) -> str:
    per_prompt: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in rows:
        per_prompt[row["prompt_version"]].append(row)

    lines = [
        "# Prompt Eval Summary",
        "",
        "## 本次运行",
        "",
        f"- 样本文件：`{samples_path.name}`",
        f"- 模型：`{model}`",
        f"- 总记录数：`{len(rows)}`",
        "",
        "## 按 Prompt 汇总",
        "",
    ]

    for prompt_version in sorted(per_prompt):
        prompt_rows = per_prompt[prompt_version]
        total = len(prompt_rows)
        success_count = sum(1 for row in prompt_rows if str(row["success"]).lower() == "true")
        format_ok_rate = round(sum(int(row["format_ok"]) for row in prompt_rows) / total, 3) if total else 0
        usable_rate = round(sum(int(row["usable"]) for row in prompt_rows) / total, 3) if total else 0
        avg_legal = round(sum(float(row["legal_pass_rate"]) for row in prompt_rows) / total, 3) if total else 0
        quality_scores = [int(row["reason_quality"]) for row in prompt_rows if str(row["reason_quality"]).isdigit()]
        avg_quality = round(sum(quality_scores) / len(quality_scores), 3) if quality_scores else "pending"
        top_messages = Counter(row["message"] for row in prompt_rows if row["message"]).most_common(3)

        lines.extend(
            [
                f"### {prompt_version}",
                "",
                f"- success_count: `{success_count}/{total}`",
                f"- format_ok_rate: `{format_ok_rate}`",
                f"- usable_rate: `{usable_rate}`",
                f"- avg_legal_pass_rate: `{avg_legal}`",
                f"- avg_reason_quality: `{avg_quality}`",
            ]
        )
        if top_messages:
            lines.append("- 主要失败/提示信息：")
            for message, count in top_messages:
                lines.append(f"  - `{count}` 次：{message}")
        lines.append("")

    lines.extend(
        [
            "## 失败样本筛选建议",
            "",
            "优先挑选以下类型写入报告：",
            "",
            "- 密码错误或房间身份错误导致的链路失败",
            "- 含 `X` 或非标准尺寸棋盘上，合法率明显下降的样本",
            "- 三版 Prompt 在同一样本上表现差异最大的记录",
            "",
            "## 下一步",
            "",
            "- 人工补齐或复核 `reason_quality`",
            "- 从 CSV 中挑选 1-2 条失败样本写入报告草稿",
            "- 用课堂展示口径压缩结论：变量、样本、结果、失败案例、下一步优化",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    args = parse_args()
    samples_path = Path(args.samples)
    csv_path = Path(args.csv_out)
    summary_path = Path(args.summary_out)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.parent.mkdir(parents=True, exist_ok=True)

    samples = load_samples(samples_path)
    rows: List[Dict[str, Any]] = []
    for sample in samples:
        for prompt_version in args.prompt_versions:
            status_code, result = safe_run_sample(
                sample=sample,
                prompt_version=prompt_version,
                model=args.model,
                max_candidates=args.max_candidates,
            )
            metrics = compute_metrics(result, args.reason_quality_mode)
            rows.append(
                {
                    "sample_id": sample["sample_id"],
                    "source_type": sample["source_type"],
                    "scene_tags": "|".join(sample.get("scene_tags") or []),
                    "focus": sample.get("focus", ""),
                    "prompt_version": prompt_version,
                    "model": args.model,
                    "max_candidates": int(sample.get("max_candidates") or args.max_candidates),
                    "status_code": status_code,
                    "success": result.get("success", False),
                    "format_ok": metrics["format_ok"],
                    "usable": metrics["usable"],
                    "candidate_count": metrics["candidate_count"],
                    "legal_candidate_count": metrics["legal_candidate_count"],
                    "legal_pass_rate": metrics["legal_pass_rate"],
                    "reason_quality": metrics["reason_quality"],
                    "best_value": metrics["best_value"],
                    "best_position": metrics["best_position"],
                    "best_source": metrics["best_source"],
                    "warning_count": metrics["warning_count"],
                    "message": metrics["message"],
                    "notes": "",
                }
            )

    write_csv(csv_path, rows)
    summary_path.write_text(build_summary(rows, samples_path, args.model), encoding="utf-8")
    print(f"Wrote CSV: {csv_path}")
    print(f"Wrote summary: {summary_path}")


if __name__ == "__main__":
    main()
