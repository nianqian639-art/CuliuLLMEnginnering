import os
from typing import List, Sequence, Union

import requests

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
DEFAULT_CHAT_MODEL = os.getenv("OLLAMA_CHAT_MODEL", "qwen3.5:0.8b")
DEFAULT_EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "bge-m3")
OLLAMA_THINKING = os.getenv("OLLAMA_THINKING", "0").lower() in ("1", "true", "yes", "on")


def _maybe_disable_thinking(text: str) -> str:
    if OLLAMA_THINKING:
        return text
    return "/no_think\n" + text


def chat(
    system_prompt: str,
    user_prompt: str,
    model: str = DEFAULT_CHAT_MODEL,
    timeout: int = 120,
    temperature: float = 0.6,
) -> str:
    final_user_prompt = _maybe_disable_thinking(user_prompt)

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
    resp = requests.post(f"{OLLAMA_BASE_URL}/api/chat", json=payload_chat, timeout=timeout)
    if resp.status_code == 404:
        payload_generate = {
            "model": model,
            "stream": False,
            "think": OLLAMA_THINKING,
            "thinking": OLLAMA_THINKING,
            "prompt": f"[SYSTEM]\n{system_prompt}\n\n[USER]\n{final_user_prompt}",
            "options": {"temperature": temperature},
        }
        resp = requests.post(f"{OLLAMA_BASE_URL}/api/generate", json=payload_generate, timeout=timeout)
        if resp.status_code == 404:
            payload_openai = {
                "model": model,
                "temperature": temperature,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": final_user_prompt},
                ],
            }
            resp = requests.post(
                f"{OLLAMA_BASE_URL}/v1/chat/completions", json=payload_openai, timeout=timeout
            )
            resp.raise_for_status()
            return (
                resp.json().get("choices", [{}])[0].get("message", {}).get("content", "").strip()
            )
        resp.raise_for_status()
        return resp.json().get("response", "").strip()

    resp.raise_for_status()
    return resp.json().get("message", {}).get("content", "").strip()


def _embed_via_api_embed(texts: Sequence[str], model: str, timeout: int) -> List[List[float]]:
    payload = {"model": model, "input": list(texts)}
    resp = requests.post(f"{OLLAMA_BASE_URL}/api/embed", json=payload, timeout=timeout)
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
        resp = requests.post(f"{OLLAMA_BASE_URL}/api/embeddings", json=payload, timeout=timeout)
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
    resp = requests.post(f"{OLLAMA_BASE_URL}/v1/embeddings", json=payload, timeout=timeout)
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
