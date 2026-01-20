"""
RAG answer generation using retrieved chunks and OpenAI chat completions.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request


def build_prompt(question: str, retrieved_chunks: list[dict]) -> list[dict]:
    context_lines = []
    for item in retrieved_chunks:
        chunk = item.get("chunk")
        document = item.get("document")
        if not chunk or not document:
            continue
        page = chunk.page or "?"
        text = (chunk.text or "").strip()
        if not text:
            continue
        context_lines.append(f"[Doc {document.id} p.{page}] {text}")

    context = "\n\n".join(context_lines)
    system = (
        "You are a helpful assistant. Answer using only the provided context. "
        "Cite sources with the format [Doc <id> p.<page>]. "
        "If the context is insufficient, say you do not know."
    )
    user = f"Question:\n{question}\n\nContext:\n{context}"
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _extract_chat_content(message: dict) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "text":
                text = item.get("text")
                if text:
                    parts.append(text)
        return "\n".join(parts)
    return ""


def answer_with_openai(
    question: str,
    retrieved_chunks: list[dict],
    api_key: str,
    model: str,
    base_url: str,
) -> str:
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required.")
    if not question:
        raise ValueError("Question is empty.")

    url = base_url.rstrip("/") + "/chat/completions"
    messages = build_prompt(question, retrieved_chunks)
    payload = {"model": model, "messages": messages, "temperature": 0.2}
    data = json.dumps(payload).encode("utf-8")
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"OpenAI error {exc.code}: {error_body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"OpenAI connection error: {exc}") from exc

    result = json.loads(body)
    choices = result.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message") or {}
    return _extract_chat_content(message).strip()
