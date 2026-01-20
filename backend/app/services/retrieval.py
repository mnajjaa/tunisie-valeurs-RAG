"""
Query embedding and pgvector retrieval helpers.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from sqlalchemy.orm import Session

from app.db.models import Chunk, Document, VECTOR_DIM


def embed_query_openai(query: str, api_key: str, model: str, base_url: str) -> list[float]:
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required.")
    if not query:
        raise ValueError("Query is empty.")

    url = base_url.rstrip("/") + "/embeddings"
    payload = {"model": model, "input": query}
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
    data_items = result.get("data") or []
    if not data_items:
        return []
    embedding = data_items[0].get("embedding") or []
    if len(embedding) != VECTOR_DIM:
        raise ValueError(
            f"embedding_dim_mismatch: expected {VECTOR_DIM}, got {len(embedding)} for model {model}"
        )
    return embedding


def search_chunks(
    db: Session,
    query_embedding: list[float],
    top_k: int = 6,
    doc_id: int | None = None,
) -> list[dict]:
    if not query_embedding:
        return []
    distance = Chunk.embedding.cosine_distance(query_embedding).label("score")
    query = (
        db.query(Chunk, Document, distance)
        .join(Document, Chunk.document_id == Document.id)
    )
    if doc_id is not None:
        query = query.filter(Chunk.document_id == doc_id)
    rows = query.order_by(distance.asc()).limit(top_k).all()
    results: list[dict] = []
    for chunk, document, score in rows:
        results.append(
            {
                "chunk": chunk,
                "document": document,
                "score": float(score) if score is not None else None,
            }
        )
    return results
