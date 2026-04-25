import hashlib
import json
import math
import os
import re
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from ollama_client import chat, embed


@dataclass
class Poem:
    poem_id: int
    title: str
    author: str
    paragraphs: List[str]

    @property
    def content(self) -> str:
        return "".join([p.strip() for p in self.paragraphs if str(p).strip()])

    @property
    def embedding_text(self) -> str:
        return f"题目：{self.title}\n作者：{self.author}\n正文：{self.content}"

    def to_dict(self) -> Dict[str, object]:
        return {
            "id": self.poem_id,
            "title": self.title,
            "author": self.author,
            "paragraphs": self.paragraphs,
            "content": self.content,
        }


def _cosine_similarity(vec_a: List[float], vec_b: List[float]) -> float:
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for a, b in zip(vec_a, vec_b):
        dot += a * b
        norm_a += a * a
        norm_b += b * b
    if norm_a <= 0 or norm_b <= 0:
        return 0.0
    return dot / (math.sqrt(norm_a) * math.sqrt(norm_b))


def _clean_poem_text(text: str) -> str:
    out = text.strip()
    if out.startswith("```"):
        out = out.strip("`")
    out = out.replace("【仿作】", "").replace("仿作：", "").strip()
    return out


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


def _infer_poem_constraints(requirement: str) -> Dict[str, Optional[int]]:
    req = requirement.strip()
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


def _validate_poem_constraints(poem_text: str, constraints: Dict[str, Optional[int]]) -> Tuple[bool, str]:
    chars_per_line = constraints.get("chars_per_line")
    line_count = constraints.get("line_count")
    if chars_per_line is None and line_count is None:
        return True, ""

    lines = _extract_poem_lines(poem_text)
    if not lines:
        return False, "输出为空"

    if line_count is not None and len(lines) != line_count:
        return False, f"句数不符合要求：期望 {line_count} 句，实际 {len(lines)} 句"

    if chars_per_line is not None:
        for idx, line in enumerate(lines, start=1):
            count = _count_chinese_chars(line)
            if count != chars_per_line:
                return (
                    False,
                    f"字数不符合要求：第 {idx} 句期望 {chars_per_line} 字，实际 {count} 字（{line}）",
                )
    return True, ""


def _repetition_score(poem_text: str) -> float:
    lines = _extract_poem_lines(poem_text)
    if not lines:
        return 10.0

    duplicate_line_penalty = float(len(lines) - len(set(lines)))

    chars = re.findall(r"[\u4e00-\u9fff]", "".join(lines))
    if len(chars) < 2:
        return duplicate_line_penalty
    bigrams = ["".join(chars[i : i + 2]) for i in range(len(chars) - 1)]
    dup_bigram_ratio = (len(bigrams) - len(set(bigrams))) / max(1, len(bigrams))
    return duplicate_line_penalty * 2.0 + dup_bigram_ratio


def _has_duplicate_lines(poem_text: str) -> bool:
    lines = _extract_poem_lines(poem_text)
    return len(lines) != len(set(lines))


def _requires_anti_libai_style(requirement: str) -> bool:
    req = str(requirement or "").strip()
    direct_patterns = [
        "不像李白",
        "不要李白",
        "不要李白风格",
        "避开李白",
        "非李白",
        "别学李白",
        "不学李白",
    ]
    if any(p in req for p in direct_patterns):
        return True
    if "李白" in req and re.search(r"(不|别|避开|避免|不要|非).{0,4}李白|李白.{0,4}(不|别|不要|避免|避开|非)", req):
        return True
    return False


def _infer_forbidden_terms(requirement: str) -> List[str]:
    req = str(requirement or "").strip()
    if not req:
        return []

    terms: List[str] = []

    # 典型形式：不包含“月”、不能出现“明月”、不含'酒'
    for pattern in [
        r"(?:不包含|不含|不要出现|不能出现|不得出现|避免出现)[“\"'‘]([\u4e00-\u9fff]{1,8})[”\"'’](?:字|词)?",
        r"(?:不包含|不含|不要出现|不能出现|不得出现|避免出现)[“\"'‘]([\u4e00-\u9fff]{1,8})[”\"'’]",
    ]:
        for token in re.findall(pattern, req):
            term = str(token).strip()
            if term:
                terms.append(term)

    # 典型形式：不包含月字 / 不要酒字
    for token in re.findall(r"(?:不包含|不含|不要|不能出现|不得出现|避免出现)([\u4e00-\u9fff])字", req):
        term = str(token).strip()
        if term:
            terms.append(term)

    # 典型形式：不得出现“思乡”一词
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


def _find_forbidden_terms_in_text(poem_text: str, forbidden_terms: List[str]) -> List[str]:
    hits: List[str] = []
    for term in forbidden_terms:
        term = str(term or "").strip()
        if term and term in poem_text:
            hits.append(term)
    return hits


class TangPoetryEngine:
    def __init__(
        self,
        data_path: str,
        cache_path: str,
        embed_model: str = "bge-m3",
        llm_model: str = "qwen3:0.6b",
    ) -> None:
        self.data_path = data_path
        self.cache_path = cache_path
        self.embed_model = embed_model
        self.llm_model = llm_model
        self.poems: List[Poem] = []
        self.vectors: List[List[float]] = []

    def build(self) -> Dict[str, object]:
        start = time.perf_counter()
        self.poems = self._load_poems()
        self.vectors = self._load_or_create_vectors()
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        return {
            "poemCount": len(self.poems),
            "vectorCount": len(self.vectors),
            "elapsedMs": elapsed_ms,
            "cachePath": self.cache_path,
        }

    def _load_poems(self) -> List[Poem]:
        with open(self.data_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        if not isinstance(raw, list):
            raise ValueError("300.json 必须是数组")

        poems: List[Poem] = []
        for idx, item in enumerate(raw):
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").strip() or f"未命名{idx+1}"
            author = str(item.get("author") or "").strip() or "佚名"
            paragraphs = item.get("paragraphs") or []
            if isinstance(paragraphs, list):
                paragraphs = [str(x) for x in paragraphs if str(x).strip()]
            else:
                paragraphs = [str(paragraphs)]
            if not paragraphs:
                continue
            poems.append(Poem(poem_id=idx + 1, title=title, author=author, paragraphs=paragraphs))
        if not poems:
            raise ValueError("未从 300.json 读取到有效诗歌")
        return poems

    def _source_signature(self) -> str:
        with open(self.data_path, "rb") as f:
            raw = f.read()
        h = hashlib.sha256()
        h.update(raw)
        h.update(self.embed_model.encode("utf-8"))
        return h.hexdigest()

    def _load_or_create_vectors(self) -> List[List[float]]:
        os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
        signature = self._source_signature()

        if os.path.exists(self.cache_path):
            try:
                with open(self.cache_path, "r", encoding="utf-8") as f:
                    cache = json.load(f)
                if (
                    cache.get("signature") == signature
                    and cache.get("embed_model") == self.embed_model
                    and isinstance(cache.get("vectors"), list)
                    and len(cache.get("vectors", [])) == len(self.poems)
                ):
                    return cache["vectors"]
            except Exception:
                pass

        texts = [p.embedding_text for p in self.poems]
        vectors: List[List[float]] = []
        batch_size = 24
        for i in range(0, len(texts), batch_size):
            vectors.extend(embed(texts[i : i + batch_size], model=self.embed_model, timeout=180))

        if len(vectors) != len(self.poems):
            raise RuntimeError("向量化数量与诗歌数量不一致，请检查 bge-m3 是否可用")

        cache_obj = {
            "signature": signature,
            "embed_model": self.embed_model,
            "created_at": int(time.time()),
            "vectors": vectors,
        }
        with open(self.cache_path, "w", encoding="utf-8") as f:
            json.dump(cache_obj, f, ensure_ascii=False)
        return vectors

    def list_authors(self) -> List[str]:
        return sorted(set([p.author for p in self.poems]))

    def recent_poems(self, limit: int = 5) -> List[Dict[str, object]]:
        limit = max(1, min(limit, 30))
        return [p.to_dict() for p in self.poems[-limit:]][::-1]

    def retrieve(self, requirement: str, author_style: str, top_k: int = 5) -> List[Tuple[Poem, float]]:
        top_k = max(1, min(top_k, 10))
        query = requirement.strip()
        if author_style.strip():
            query = f"{query}\n风格参考作者：{author_style.strip()}"

        q_vec = embed(query, model=self.embed_model, timeout=120)[0]
        scored: List[Tuple[Poem, float]] = []
        target_author = author_style.strip()
        anti_libai = _requires_anti_libai_style(requirement)
        for poem, vec in zip(self.poems, self.vectors):
            score = _cosine_similarity(q_vec, vec)
            if target_author and poem.author == target_author:
                score += 0.08
            # 强约束：用户要求“不像李白”时，对李白样本显著降权。
            if anti_libai and poem.author == "李白":
                score -= 0.35
            scored.append((poem, score))
        scored.sort(key=lambda x: x[1], reverse=True)

        if anti_libai:
            non_libai = [item for item in scored if item[0].author != "李白"]
            # 硬约束：只要要求“非李白”，source 中李白占比必须 0%。
            # 因此这里不做回退，宁可返回更少参考也不引入李白样本。
            return non_libai[:top_k]
        return scored[:top_k]

    def _build_generation_prompt(
        self, requirement: str, author_style: str, refs: List[Tuple[Poem, float]]
    ) -> str:
        constraints = _infer_poem_constraints(requirement)
        anti_libai = _requires_anti_libai_style(requirement)
        forbidden_terms = _infer_forbidden_terms(requirement)
        chars_per_line = constraints.get("chars_per_line")
        line_count = constraints.get("line_count")
        meter_line = ""
        if chars_per_line is not None:
            meter_line += f"- 每句严格 {chars_per_line} 个汉字；\n"
        if line_count is not None:
            meter_line += f"- 全诗严格 {line_count} 句；\n"
        if not meter_line:
            meter_line = "- 按用户要求的体裁创作，句式统一；\n"

        ref_block = []
        for idx, (poem, score) in enumerate(refs, start=1):
            ref_block.append(
                f"[参考{idx}] 题目《{poem.title}》 作者：{poem.author} 相似度：{score:.4f}\n{poem.content}"
            )
        ref_text = "\n\n".join(ref_block)
        if anti_libai and not author_style.strip():
            style_line = "非李白风格（偏王维/杜牧的含蓄凝练表达）"
        else:
            style_line = author_style.strip() or "不限（偏唐诗古典风格）"
        anti_style_line = ""
        if anti_libai:
            anti_style_line = (
                "- 风格负向约束（强制）：不得出现李白标签化表达（如谪仙、将进酒、举杯邀明月等同类句法）；\n"
                "- 语气需含蓄克制，避免豪放飞仙、纵酒高歌腔调；\n"
            )
        forbidden_line = ""
        if forbidden_terms:
            forbidden_line = f"- 禁止出现以下字词（硬约束）：{'、'.join(forbidden_terms)}；\n"
        return (
            f"用户要求：{requirement.strip()}\n"
            f"指定风格：{style_line}\n\n"
            f"参考诗作：\n{ref_text}\n\n"
            "请你创作一首中文古诗仿作，要求：\n"
            "1) 风格贴近指定作者或参考诗作；\n"
            "2) 语言自然，意象统一；\n"
            f"3) 格式约束：\n{meter_line}"
            f"{anti_style_line}"
            f"{forbidden_line}"
            "4) 输出仅包含诗正文，不要解释，不要标题，不要 markdown。"
        )

    def _repair_poem_to_constraints(
        self,
        poem_text: str,
        requirement: str,
        author_style: str,
        constraints: Dict[str, Optional[int]],
    ) -> str:
        chars_per_line = constraints.get("chars_per_line")
        line_count = constraints.get("line_count")
        style_line = author_style.strip() or "古典唐诗风格"
        rule_lines = []
        if chars_per_line is not None:
            rule_lines.append(f"每句必须 {chars_per_line} 个汉字")
        if line_count is not None:
            rule_lines.append(f"全诗必须 {line_count} 句")
        rule_text = "；".join(rule_lines) if rule_lines else "句式统一"

        prompt = (
            f"原始要求：{requirement.strip()}\n"
            f"风格要求：{style_line}\n"
            f"请把下面诗稿严格改写为满足以下硬性约束：{rule_text}。\n"
            "只输出改写后的诗正文，不要解释。\n\n"
            f"待改写诗稿：\n{poem_text}"
        )
        return _clean_poem_text(
            chat(
                "你是严格的古诗格律修正助手，必须满足硬性格式要求。",
                prompt,
                model=self.llm_model,
                timeout=120,
                temperature=0.2,
            )
        )

    def _rewrite_poem_from_scratch(
        self,
        requirement: str,
        author_style: str,
        constraints: Dict[str, Optional[int]],
    ) -> str:
        chars_per_line = constraints.get("chars_per_line")
        line_count = constraints.get("line_count")
        style_line = author_style.strip() or "古典唐诗风格"

        format_req = []
        if chars_per_line is not None:
            format_req.append(f"每句 {chars_per_line} 字")
        if line_count is not None:
            format_req.append(f"共 {line_count} 句")
        format_text = "，".join(format_req) if format_req else "句式统一"

        prompt = (
            f"用户要求：{requirement.strip()}\n"
            f"风格：{style_line}\n"
            f"硬性格式：{format_text}。\n"
            "现在直接重新创作，不参考旧稿。\n"
            "输出规则：\n"
            "1) 每句单独一行；\n"
            "2) 只输出诗正文；\n"
            "3) 不要解释说明。"
        )
        return _clean_poem_text(
            chat(
                "你是古诗生成助手，必须严格遵守字数与句数约束。",
                prompt,
                model=self.llm_model,
                timeout=120,
                temperature=0.2,
            )
        )

    def _rewrite_to_reduce_repetition(
        self,
        poem_text: str,
        requirement: str,
        author_style: str,
        constraints: Dict[str, Optional[int]],
    ) -> str:
        chars_per_line = constraints.get("chars_per_line")
        line_count = constraints.get("line_count")
        style_line = author_style.strip() or "古典唐诗风格"

        format_req = []
        if chars_per_line is not None:
            format_req.append(f"每句 {chars_per_line} 字")
        if line_count is not None:
            format_req.append(f"共 {line_count} 句")
        format_text = "，".join(format_req) if format_req else "句式统一"

        prompt = (
            f"原始要求：{requirement.strip()}\n"
            f"风格要求：{style_line}\n"
            f"格式要求：{format_text}\n"
            "下面诗稿出现了较明显重复，请在保留主题的前提下重写，严格遵守以下规则：\n"
            "1) 不允许出现任何两句完全相同；\n"
            "2) 每句意象要有变化，避免重复词组；\n"
            "3) 每句独立一行；\n"
            "4) 只输出诗正文。\n\n"
            f"原诗稿：\n{poem_text}"
        )
        return _clean_poem_text(
            chat(
                "你是古诗润色助手，专门降低诗句重复率并保持诗意统一。",
                prompt,
                model=self.llm_model,
                timeout=120,
                temperature=0.35,
            )
        )

    def _rewrite_to_avoid_forbidden_terms(
        self,
        poem_text: str,
        requirement: str,
        author_style: str,
        constraints: Dict[str, Optional[int]],
        forbidden_terms: List[str],
    ) -> str:
        chars_per_line = constraints.get("chars_per_line")
        line_count = constraints.get("line_count")
        style_line = author_style.strip() or "古典唐诗风格"
        format_req = []
        if chars_per_line is not None:
            format_req.append(f"每句 {chars_per_line} 字")
        if line_count is not None:
            format_req.append(f"共 {line_count} 句")
        format_text = "，".join(format_req) if format_req else "句式统一"
        forbidden_text = "、".join(forbidden_terms)
        prompt = (
            f"原始要求：{requirement.strip()}\n"
            f"风格要求：{style_line}\n"
            f"格式要求：{format_text}\n"
            f"硬约束：不得出现这些字词：{forbidden_text}\n"
            "请在保持主题的同时重写下面诗稿，并严格遵守硬约束。\n"
            "只输出诗正文，每句单独一行，不要解释。\n\n"
            f"原诗稿：\n{poem_text}"
        )
        return _clean_poem_text(
            chat(
                "你是严格的古诗约束修正助手，必须满足禁用字词与格律要求。",
                prompt,
                model=self.llm_model,
                timeout=120,
                temperature=0.25,
            )
        )

    def _force_replace_forbidden_terms(self, poem_text: str, forbidden_terms: List[str]) -> str:
        forbidden_set = set("".join(forbidden_terms))
        safe_chars = [c for c in list("山水风云江海秋夜花灯舟客烟雨松城雁渔") if c not in forbidden_set]
        if not safe_chars:
            safe_chars = list("山水风云江海秋夜")

        out = poem_text
        cursor = 0
        for term in forbidden_terms:
            term = str(term or "").strip()
            if not term:
                continue
            while term in out:
                if len(term) == 1:
                    replacement = safe_chars[cursor % len(safe_chars)]
                else:
                    replacement = "".join([safe_chars[(cursor + i) % len(safe_chars)] for i in range(len(term))])
                out = out.replace(term, replacement, 1)
                cursor += 1
        return out

    def _force_shape_poem(
        self,
        poem_text: str,
        constraints: Dict[str, Optional[int]],
        refs: List[Tuple[Poem, float]],
    ) -> str:
        chars_per_line = constraints.get("chars_per_line")
        line_count = constraints.get("line_count")
        if chars_per_line is None and line_count is None:
            return poem_text

        lines = _extract_poem_lines(poem_text)
        if not lines:
            lines = [""]

        target_line_count = line_count or len(lines)
        if target_line_count <= 0:
            target_line_count = len(lines)

        reservoir_text = poem_text + "".join([poem.content for poem, _ in refs]) + "山水春秋风月云天江湖故园"
        reservoir_chars = re.findall(r"[\u4e00-\u9fff]", reservoir_text)
        if not reservoir_chars:
            reservoir_chars = list("山水春秋风月云天江湖故园")
        ptr = 0

        shaped_lines: List[str] = []
        for i in range(target_line_count):
            base = lines[i] if i < len(lines) else ""
            chars = re.findall(r"[\u4e00-\u9fff]", base)

            if chars_per_line is not None:
                chars = chars[:chars_per_line]
                while len(chars) < chars_per_line:
                    chars.append(reservoir_chars[ptr % len(reservoir_chars)])
                    ptr += 1
            if not chars:
                chars.append(reservoir_chars[ptr % len(reservoir_chars)])
                ptr += 1

            shaped_line = "".join(chars)
            retries = 0
            while shaped_line in shaped_lines and retries < 3:
                if chars_per_line is None:
                    chars.append(reservoir_chars[ptr % len(reservoir_chars)])
                else:
                    chars[-1] = reservoir_chars[ptr % len(reservoir_chars)]
                ptr += 1
                retries += 1
                shaped_line = "".join(chars[:chars_per_line] if chars_per_line is not None else chars)

            shaped_lines.append(shaped_line)

        return "\n".join(shaped_lines)

    def _force_deduplicate_lines(
        self,
        poem_text: str,
        constraints: Dict[str, Optional[int]],
        refs: List[Tuple[Poem, float]],
    ) -> str:
        lines = _extract_poem_lines(poem_text)
        if not lines:
            return poem_text

        chars_per_line = constraints.get("chars_per_line")
        reservoir_text = poem_text + "".join([poem.content for poem, _ in refs]) + "山水江月风云花雨城楼渔火"
        reservoir_chars = re.findall(r"[\u4e00-\u9fff]", reservoir_text)
        if not reservoir_chars:
            reservoir_chars = list("山水江月风云花雨城楼渔火")
        ptr = 0

        seen = set()
        out: List[str] = []
        for line in lines:
            candidate = line
            if candidate in seen:
                chars = re.findall(r"[\u4e00-\u9fff]", candidate)
                if chars_per_line is not None:
                    chars = chars[:chars_per_line]
                    while len(chars) < chars_per_line:
                        chars.append(reservoir_chars[ptr % len(reservoir_chars)])
                        ptr += 1

                attempts = 0
                while attempts < 6:
                    if not chars:
                        chars = [reservoir_chars[ptr % len(reservoir_chars)]]
                        ptr += 1
                    replace_idx = max(0, len(chars) - 1 - (attempts % max(1, len(chars))))
                    chars[replace_idx] = reservoir_chars[ptr % len(reservoir_chars)]
                    ptr += 1
                    proposal = "".join(chars[:chars_per_line] if chars_per_line is not None else chars)
                    if proposal not in seen:
                        candidate = proposal
                        break
                    attempts += 1
            seen.add(candidate)
            out.append(candidate)

        return "\n".join(out)

    def generate(self, requirement: str, author_style: str, top_k: int = 5) -> Dict[str, object]:
        refs = self.retrieve(requirement=requirement, author_style=author_style, top_k=top_k)
        prompt = self._build_generation_prompt(requirement, author_style, refs)
        system_prompt = "你是唐诗仿作助手，擅长根据用户要求与参考风格创作古体诗句。"
        text = chat(system_prompt, prompt, model=self.llm_model, timeout=120, temperature=0.75)
        poem_text = _clean_poem_text(text)
        constraints = _infer_poem_constraints(requirement)
        forbidden_terms = _infer_forbidden_terms(requirement)
        valid, constraint_msg = _validate_poem_constraints(poem_text, constraints)
        if not valid:
            repaired = self._repair_poem_to_constraints(
                poem_text=poem_text,
                requirement=requirement,
                author_style=author_style,
                constraints=constraints,
            )
            valid2, msg2 = _validate_poem_constraints(repaired, constraints)
            if valid2:
                poem_text = repaired
                constraint_msg = ""
            else:
                rewritten = self._rewrite_poem_from_scratch(
                    requirement=requirement,
                    author_style=author_style,
                    constraints=constraints,
                )
                valid3, msg3 = _validate_poem_constraints(rewritten, constraints)
                if valid3:
                    poem_text = rewritten
                    constraint_msg = ""
                else:
                    forced = self._force_shape_poem(rewritten, constraints, refs)
                    valid4, msg4 = _validate_poem_constraints(forced, constraints)
                    poem_text = forced
                    constraint_msg = "" if valid4 else msg4

        best_poem = poem_text
        best_score = _repetition_score(poem_text)
        if _has_duplicate_lines(poem_text) or best_score > 0.28:
            for _ in range(2):
                candidate = self._rewrite_to_reduce_repetition(
                    poem_text=best_poem,
                    requirement=requirement,
                    author_style=author_style,
                    constraints=constraints,
                )
                c_valid, _ = _validate_poem_constraints(candidate, constraints)
                if not c_valid:
                    candidate = self._force_shape_poem(candidate, constraints, refs)
                c_valid2, _ = _validate_poem_constraints(candidate, constraints)
                if not c_valid2:
                    continue

                score = _repetition_score(candidate)
                if score < best_score:
                    best_poem = candidate
                    best_score = score
            poem_text = best_poem

        if _has_duplicate_lines(poem_text):
            poem_text = self._force_deduplicate_lines(poem_text, constraints, refs)

        forbidden_msg = ""
        if forbidden_terms:
            for _ in range(2):
                hits = _find_forbidden_terms_in_text(poem_text, forbidden_terms)
                if not hits:
                    break
                candidate = self._rewrite_to_avoid_forbidden_terms(
                    poem_text=poem_text,
                    requirement=requirement,
                    author_style=author_style,
                    constraints=constraints,
                    forbidden_terms=forbidden_terms,
                )
                c_valid, _ = _validate_poem_constraints(candidate, constraints)
                if not c_valid:
                    candidate = self._force_shape_poem(candidate, constraints, refs)
                poem_text = candidate

            final_hits = _find_forbidden_terms_in_text(poem_text, forbidden_terms)
            if final_hits:
                poem_text = self._force_replace_forbidden_terms(poem_text, forbidden_terms)
                c_valid, _ = _validate_poem_constraints(poem_text, constraints)
                if not c_valid:
                    poem_text = self._force_shape_poem(poem_text, constraints, refs)
                final_hits = _find_forbidden_terms_in_text(poem_text, forbidden_terms)
            if final_hits:
                forbidden_msg = f"包含禁用字词：{'、'.join(final_hits)}"

        repetition_message = ""
        if _has_duplicate_lines(poem_text):
            repetition_message = "仍存在重复句，可再次生成获取更多变化。"
        if forbidden_msg:
            constraint_msg = f"{constraint_msg}；{forbidden_msg}" if constraint_msg else forbidden_msg

        return {
            "poem": poem_text,
            "references": [
                {
                    "id": poem.poem_id,
                    "title": poem.title,
                    "author": poem.author,
                    "content": poem.content,
                    "score": round(score, 4),
                }
                for poem, score in refs
            ],
            "models": {"llm": self.llm_model, "embedding": self.embed_model},
            "constraintPassed": not bool(constraint_msg),
            "constraintMessage": constraint_msg,
            "forbiddenTerms": forbidden_terms,
            "repetitionScore": round(_repetition_score(poem_text), 4),
            "repetitionMessage": repetition_message,
        }
