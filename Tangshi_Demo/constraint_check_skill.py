import re
from typing import Dict, List, Optional


LIBAI_PHRASE_MARKERS = [
    "谪仙",
    "将进酒",
    "举杯邀明月",
    "黄河之水天上来",
    "仰天大笑",
    "天生我材必有用",
    "飞流直下三千尺",
    "长风破浪会有时",
]


def _count_chinese_chars(text: str) -> int:
    return len(re.findall(r"[\u4e00-\u9fff]", text))


def _extract_poem_lines(poem_text: str) -> List[str]:
    normalized = "\n".join([line.strip() for line in poem_text.splitlines() if line.strip()])
    parts = [x.strip() for x in re.split(r"[，。！？；、\n]+", normalized) if x.strip()]
    cleaned: List[str] = []
    for part in parts:
        line = re.sub(r"[，。！？；、\s]+$", "", part)
        if line:
            cleaned.append(line)
    return cleaned


def _infer_meter_constraints(user_requirement: str) -> Dict[str, Optional[int]]:
    req = str(user_requirement or "").strip()
    chars_per_line: Optional[int] = None
    line_count: Optional[int] = None

    if "五言" in req or "五绝" in req or "五律" in req:
        chars_per_line = 5
    elif "七言" in req or "七绝" in req or "七律" in req:
        chars_per_line = 7

    if "绝句" in req or "五绝" in req or "七绝" in req:
        line_count = 4
    elif "律诗" in req or "五律" in req or "七律" in req:
        line_count = 8

    return {"chars_per_line": chars_per_line, "line_count": line_count}


def _requires_anti_libai(user_requirement: str) -> bool:
    req = str(user_requirement or "").strip()
    direct_patterns = [
        "不像李白",
        "不要李白",
        "避开李白",
        "非李白",
        "别学李白",
        "不学李白",
        "不要李白风格",
    ]
    if any(p in req for p in direct_patterns):
        return True
    if "李白" in req and re.search(r"(不|别|避开|避免|不要|非).{0,4}李白|李白.{0,4}(不|别|不要|避免|避开|非)", req):
        return True
    return False


def _infer_forbidden_terms(user_requirement: str) -> List[str]:
    req = str(user_requirement or "").strip()
    if not req:
        return []

    terms: List[str] = []
    for pattern in [
        r"(?:不包含|不含|不要出现|不能出现|不得出现|避免出现)[“\"'‘]([\u4e00-\u9fff]{1,8})[”\"'’](?:字|词)?",
        r"(?:不包含|不含|不要出现|不能出现|不得出现|避免出现)[“\"'‘]([\u4e00-\u9fff]{1,8})[”\"'’]",
    ]:
        for token in re.findall(pattern, req):
            term = str(token).strip()
            if term:
                terms.append(term)

    for token in re.findall(r"(?:不包含|不含|不要|不能出现|不得出现|避免出现)([\u4e00-\u9fff])字", req):
        term = str(token).strip()
        if term:
            terms.append(term)

    for token in re.findall(r"(?:不包含|不含|不要出现|不能出现|不得出现|避免出现)([\u4e00-\u9fff]{1,8})(?:一词|这个词|词)", req):
        term = str(token).strip()
        if term:
            terms.append(term)

    dedup: List[str] = []
    seen = set()
    for term in terms:
        if term not in seen:
            dedup.append(term)
            seen.add(term)
    return dedup


def _find_forbidden_terms(poem_text: str, forbidden_terms: List[str]) -> List[str]:
    hits: List[str] = []
    for term in forbidden_terms:
        if term and term in poem_text:
            hits.append(term)
    return hits


def _contains_libai_style(poem_text: str) -> List[str]:
    hits = [marker for marker in LIBAI_PHRASE_MARKERS if marker in poem_text]
    if "明月" in poem_text and any(token in poem_text for token in ["酒", "醉", "杯"]) and any(
        token in poem_text for token in ["天", "青天"]
    ):
        hits.append("明月+酒/醉/杯+天(青天) 组合")
    return hits


class ConstraintCheckSkill:
    def __init__(self) -> None:
        self.name = "ConstraintCheckSkill"

    def check(
        self,
        poem_text: str,
        user_requirement: str,
        retrieved_samples: Optional[List[Dict[str, object]]] = None,
        author_style: str = "",
    ) -> Dict[str, object]:
        poem_text = str(poem_text or "").strip()
        user_requirement = str(user_requirement or "").strip()
        retrieved_samples = retrieved_samples or []
        author_style = str(author_style or "").strip()

        violations: List[Dict[str, object]] = []
        normalized_requirements: List[str] = []
        repair_instructions: List[str] = []

        if user_requirement:
            normalized_requirements.append(f"用户要求: {user_requirement}")
        if author_style:
            normalized_requirements.append(f"指定风格: {author_style}")

        meter = _infer_meter_constraints(user_requirement)
        chars_per_line = meter.get("chars_per_line")
        line_count = meter.get("line_count")
        if chars_per_line is not None:
            normalized_requirements.append(f"字数约束: 每句{chars_per_line}字")
        if line_count is not None:
            normalized_requirements.append(f"句数约束: 全诗{line_count}句")

        anti_libai = _requires_anti_libai(user_requirement)
        forbidden_terms = _infer_forbidden_terms(user_requirement)
        if anti_libai:
            normalized_requirements.append("风格负向约束: 不像李白")
        if forbidden_terms:
            normalized_requirements.append(f"禁用字词: {'、'.join(forbidden_terms)}")

        if not poem_text:
            violations.append(
                {
                    "rule_id": "CONTENT_NOT_EMPTY",
                    "severity": "hard",
                    "message": "候选诗作为空",
                    "evidence": ["poem_text 为空字符串"],
                }
            )
            repair_instructions.append("重新生成完整诗作正文，不要返回空文本。")
        else:
            lines = _extract_poem_lines(poem_text)
            if line_count is not None and len(lines) != line_count:
                violations.append(
                    {
                        "rule_id": "METER_LINE_COUNT",
                        "severity": "hard",
                        "message": f"句数不符合要求：期望{line_count}句，实际{len(lines)}句",
                        "evidence": [f"lines={lines}"],
                    }
                )
                repair_instructions.append(f"调整为严格 {line_count} 句。")

            if chars_per_line is not None:
                wrong_lines = []
                for idx, line in enumerate(lines, start=1):
                    c = _count_chinese_chars(line)
                    if c != chars_per_line:
                        wrong_lines.append(f"第{idx}句({line})={c}字")
                if wrong_lines:
                    violations.append(
                        {
                            "rule_id": "METER_CHARS_PER_LINE",
                            "severity": "hard",
                            "message": f"字数不符合要求：每句应为{chars_per_line}字",
                            "evidence": wrong_lines,
                        }
                    )
                    repair_instructions.append(f"逐句修正为每句严格 {chars_per_line} 字。")

            if forbidden_terms:
                forbidden_hits = _find_forbidden_terms(poem_text, forbidden_terms)
                if forbidden_hits:
                    violations.append(
                        {
                            "rule_id": "FORBIDDEN_TERMS",
                            "severity": "hard",
                            "message": f"命中禁用字词：{'、'.join(forbidden_hits)}",
                            "evidence": forbidden_hits,
                        }
                    )
                    repair_instructions.append(f"重写并严格避免这些字词：{'、'.join(forbidden_terms)}。")

            if anti_libai:
                style_hits = _contains_libai_style(poem_text)
                if style_hits:
                    violations.append(
                        {
                            "rule_id": "STYLE_NEG_LI_BAI",
                            "severity": "hard",
                            "message": "命中李白风格高辨识表达，违反“不像李白”约束",
                            "evidence": style_hits,
                        }
                    )
                    repair_instructions.extend(
                        [
                            "删除李白标签化表达（如谪仙、将进酒、举杯邀明月等同类句法）。",
                            "改用含蓄克制、细节化表达，可参考王维/杜牧风格。",
                        ]
                    )

                if retrieved_samples:
                    total = len(retrieved_samples)
                    libai_count = 0
                    for item in retrieved_samples:
                        author = str(item.get("author") or "").strip()
                        if author == "李白":
                            libai_count += 1
                    if total > 0 and libai_count > 0:
                        violations.append(
                            {
                                "rule_id": "RETRIEVAL_ZERO_LI_BAI",
                                "severity": "hard",
                                "message": "检索样本违反硬约束：要求“不像李白”时李白样本占比必须为0%",
                                "evidence": [f"李白样本占比={libai_count}/{total}"],
                            }
                        )
                        repair_instructions.append("重检索并硬过滤李白作者样本，确保 source 中李白占比为 0%。")

        has_hard = any(v.get("severity") == "hard" for v in violations)
        if has_hard:
            if any(
                v.get("rule_id") in ("STYLE_NEG_LI_BAI", "RETRIEVAL_ZERO_LI_BAI", "FORBIDDEN_TERMS")
                for v in violations
            ):
                decision = "regenerate"
            else:
                decision = "revise"
        elif violations:
            decision = "revise"
        else:
            decision = "allow"

        compliant = not violations
        if compliant:
            repair_instructions = []

        return {
            "skill": self.name,
            "isCompliant": compliant,
            "pass": compliant,
            "decision": decision,
            "problemParts": [v.get("message") for v in violations],
            "violations": violations,
            "correctRequirements": normalized_requirements,
            "normalizedRequirements": normalized_requirements,
            "repairInstructions": repair_instructions,
            "outputFormat": "json",
            "是否符合要求": compliant,
            "是否符合要求_TF": "T" if compliant else "F",
            "问题所在": [v.get("message") for v in violations],
            "正确要求": normalized_requirements,
            "可执行修复指令": repair_instructions,
            "标准化后的约束列表": normalized_requirements,
            "输出格式": "JSON",
        }
