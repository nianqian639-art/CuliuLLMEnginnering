import os
from typing import List, Sequence, Union

import requests

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
DEFAULT_CHAT_MODEL = os.getenv("OLLAMA_CHAT_MODEL", "qwen3.5:0.8b")
DEFAULT_EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "bge-m3")
OLLAMA_THINKING = os.getenv("OLLAMA_THINKING", "0").lower() in ("1", "true", "yes", "on")
OLLAMA_OUTPUT_MODE = os.getenv("OLLAMA_OUTPUT_MODE", "generate").strip().lower()
OLLAMA_API_TOKEN = os.getenv("OLLAMA_API_TOKEN", "").strip()


def _maybe_disable_thinking(text: str) -> str:
    if OLLAMA_THINKING:
        return text
    return "/no_think\n" + text


def _request_headers() -> dict:
    headers = {}
    if OLLAMA_API_TOKEN:
        headers["Authorization"] = f"Bearer {OLLAMA_API_TOKEN}"
    return headers


def _post(path: str, payload: dict, timeout: int) -> requests.Response:
    return requests.post(
        f"{OLLAMA_BASE_URL}{path}",
        json=payload,
        headers=_request_headers(),
        timeout=timeout,
    )


def _chat_via_generate(system_prompt: str, final_user_prompt: str, model: str, timeout: int, temperature: float) -> str:
    payload_generate = {
        "model": model,
        "stream": False,
        "prompt": final_user_prompt,
        "system": system_prompt,
        "options": {"temperature": temperature},
    }
    resp = _post("/api/generate", payload_generate, timeout=timeout)
    if resp.status_code == 404:
        return ""
    resp.raise_for_status()
    return resp.json().get("response", "").strip()


def _chat_via_chat(system_prompt: str, final_user_prompt: str, model: str, timeout: int, temperature: float) -> str:
    payload_chat = {
        "model": model,
        "stream": False,
        "think": OLLAMA_THINKING,
        "thinking": OLLAMA_THINKING,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": final_user_prompt},
        ],
        "options": {"temperature": temperature},
    }
    resp = _post("/api/chat", payload_chat, timeout=timeout)
    if resp.status_code == 404:
        return ""
    resp.raise_for_status()
    return resp.json().get("message", {}).get("content", "").strip()


def _chat_via_openai(system_prompt: str, final_user_prompt: str, model: str, timeout: int, temperature: float) -> str:
    payload_openai = {
        "model": model,
        "temperature": temperature,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": final_user_prompt},
        ],
    }
    resp = _post("/v1/chat/completions", payload_openai, timeout=timeout)
    if resp.status_code == 404:
        return ""
    resp.raise_for_status()
    return resp.json().get("choices", [{}])[0].get("message", {}).get("content", "").strip()


def chat(
    system_prompt: str,
    user_prompt: str,
    model: str = DEFAULT_CHAT_MODEL,
    timeout: int = 120,
    temperature: float = 0.6,
) -> str:
    final_user_prompt = _maybe_disable_thinking(user_prompt)
    mode_order = {
        "generate": ("generate", "chat", "openai"),
        "chat": ("chat", "generate", "openai"),
        "openai": ("openai", "chat", "generate"),
    }.get(OLLAMA_OUTPUT_MODE, ("generate", "chat", "openai"))

    errors = []
    for mode in mode_order:
        try:
            if mode == "generate":
                text = _chat_via_generate(system_prompt, final_user_prompt, model, timeout, temperature)
            elif mode == "chat":
                text = _chat_via_chat(system_prompt, final_user_prompt, model, timeout, temperature)
            else:
                text = _chat_via_openai(system_prompt, final_user_prompt, model, timeout, temperature)
            if text:
                return text
            errors.append(f"{mode}: empty response")
        except Exception as exc:
            errors.append(f"{mode}: {exc}")
            continue
    raise RuntimeError("模型接口不可用：" + " | ".join(errors))


def _embed_via_api_embed(texts: Sequence[str], model: str, timeout: int) -> List[List[float]]:
    payload = {"model": model, "input": list(texts)}
    resp = _post("/api/embed", payload, timeout=timeout)
    if resp.status_code == 404:
        return []
    resp.raise_for_status()
    data = resp.json()
    vectors = data.get("embeddings")
    if not isinstance(vectors, list):
        raise ValueError("Ollama /api/embed 返回格式不合法")
    return vectors


def _embed_via_api_embeddings(texts: Sequence[str], model: str, timeout: int) -> List[List[float]]:
    vectors: List[List[float]] = []
    for text in texts:
        payload = {"model": model, "prompt": text}
        resp = _post("/api/embeddings", payload, timeout=timeout)
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        emb = resp.json().get("embedding")
        if not isinstance(emb, list):
            raise ValueError("Ollama /api/embeddings 返回格式不合法")
        vectors.append(emb)
    return vectors


def _embed_via_openai_compat(texts: Sequence[str], model: str, timeout: int) -> List[List[float]]:
    payload = {"model": model, "input": list(texts)}
    resp = _post("/v1/embeddings", payload, timeout=timeout)
    resp.raise_for_status()
    data = resp.json().get("data", [])
    out: List[List[float]] = []
    for item in data:
        vec = item.get("embedding")
        if isinstance(vec, list):
            out.append(vec)
    if len(out) != len(texts):
        raise ValueError("OpenAI 兼容 embeddings 返回数量不匹配")
    return out


def embed(
    texts: Union[str, Sequence[str]],
    model: str = DEFAULT_EMBED_MODEL,
    timeout: int = 120,
) -> List[List[float]]:
    if isinstance(texts, str):
        text_list = [texts]
    else:
        text_list = [str(item) for item in texts]
    if not text_list:
        return []

    vectors = _embed_via_api_embed(text_list, model=model, timeout=timeout)
    if vectors:
        return vectors

    vectors = _embed_via_api_embeddings(text_list, model=model, timeout=timeout)
    if vectors:
        return vectors

    return _embed_via_openai_compat(text_list, model=model, timeout=timeout)
