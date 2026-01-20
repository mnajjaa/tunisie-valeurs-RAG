"""
Build contextual chunks from structured blocks and store OpenAI embeddings in pgvector.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import urllib.error
import urllib.request
from collections import defaultdict

from sqlalchemy.orm import Session

from app.db.models import Chunk, Document, DocumentAsset, DocumentBlock, VECTOR_DIM


logger = logging.getLogger(__name__)

DEFAULT_MAX_CHARS = 2000
DEFAULT_BATCH_SIZE = 100
REEMBED_NOTE = "Re-embedding required: python scripts/run_chunk_and_embed.py --overwrite --model text-embedding-3-small"


def _compose_chunk_text(title_text: str, units: list[dict]) -> str:
    parts = []
    if title_text:
        parts.append(title_text)
    parts.extend(unit["text"] for unit in units if unit.get("text"))
    return "\n".join(parts).strip()


def _split_units_with_overlap(
    title_text: str,
    units: list[dict],
    max_chars: int,
) -> list[str]:
    if not units:
        if title_text:
            return [title_text.strip()]
        return []

    chunks: list[str] = []
    current_units: list[dict] = []

    for unit in units:
        candidate_units = current_units + [unit]
        candidate_text = _compose_chunk_text(title_text, candidate_units)
        if current_units and len(candidate_text) > max_chars:
            chunk_text = _compose_chunk_text(title_text, current_units)
            if chunk_text:
                chunks.append(chunk_text)
            overlap_para = current_units[-1].get("paragraph_text")
            current_units = []
            if overlap_para:
                current_units.append({"text": overlap_para, "paragraph_text": overlap_para})
        current_units.append(unit)

    if current_units:
        chunk_text = _compose_chunk_text(title_text, current_units)
        if chunk_text:
            chunks.append(chunk_text)
    return chunks


def _normalize_text(value: str) -> str:
    return (value or "").strip()


def _build_asset_map(db: Session, document_id: int) -> dict[int, list[str]]:
    assets = (
        db.query(DocumentAsset)
        .filter(DocumentAsset.document_id == document_id)
        .order_by(DocumentAsset.id.asc())
        .all()
    )
    asset_map: dict[int, list[str]] = defaultdict(list)
    for asset in assets:
        if not asset.page_number:
            continue
        caption = _normalize_text(asset.caption_text or "")
        table_content = _normalize_text(asset.table_content or "")
        if not caption and not table_content:
            continue
        lines = []
        if caption:
            lines.append(f"Related figure/table: {caption}")
        elif table_content:
            lines.append("Related figure/table:")
        if table_content:
            lines.append(table_content)
        text = "\n".join(lines).strip()
        if text:
            asset_map[int(asset.page_number)].append(text)
    return asset_map


def build_contextual_chunks(
    document_id: int,
    db: Session,
    max_chars: int = DEFAULT_MAX_CHARS,
    include_assets: bool = True,
) -> list[dict]:
    blocks = (
        db.query(DocumentBlock)
        .filter(DocumentBlock.document_id == document_id)
        .order_by(DocumentBlock.block_index.asc())
        .all()
    )
    if not blocks:
        return []

    asset_map = _build_asset_map(db, document_id) if include_assets else {}

    sections: list[dict] = []
    current = {"page": None, "title": "", "blocks": []}

    for block in blocks:
        if block.block_type == "TITLE":
            if current["title"] or current["blocks"]:
                sections.append(current)
            current = {"page": block.page_number, "title": block.text or "", "blocks": []}
        else:
            if current["page"] is None:
                current["page"] = block.page_number
            current["blocks"].append(block)

    if current["title"] or current["blocks"]:
        sections.append(current)

    chunks: list[dict] = []

    for section in sections:
        page = section["page"] or 1
        title_text = _normalize_text(section["title"])

        segments: list[dict] = []
        if title_text:
            segments.append({"type": "TITLE", "text": title_text})

        list_buffer: list[str] = []
        for block in section["blocks"]:
            text = _normalize_text(block.text or "")
            if not text:
                continue
            if block.block_type == "LIST_ITEM":
                list_buffer.append(text)
                continue
            if list_buffer:
                segments.append({"type": "LIST_ITEM", "text": "\n".join(list_buffer)})
                list_buffer = []
            segments.append({"type": block.block_type, "text": text})
        if list_buffer:
            segments.append({"type": "LIST_ITEM", "text": "\n".join(list_buffer)})

        content_segments = segments[:]
        if content_segments and content_segments[0]["type"] == "TITLE":
            content_segments = content_segments[1:]

        units: list[dict] = []
        unit_segments: list[dict] = []
        for segment in content_segments:
            unit_segments.append(segment)
            if segment["type"] == "PARAGRAPH":
                unit_text = "\n".join(seg["text"] for seg in unit_segments).strip()
                if unit_text:
                    units.append({"text": unit_text, "paragraph_text": segment["text"]})
                unit_segments = []
        if unit_segments:
            unit_text = "\n".join(seg["text"] for seg in unit_segments).strip()
            if unit_text:
                units.append({"text": unit_text, "paragraph_text": None})

        section_chunks = _split_units_with_overlap(title_text, units, max_chars)
        if not section_chunks and title_text:
            section_chunks = [title_text]

        assets_texts = asset_map.get(int(page), [])
        assets_text = "\n".join(assets_texts).strip()
        if assets_text and section_chunks:
            section_chunks[-1] = f"{section_chunks[-1]}\n{assets_text}".strip()

        for chunk_text in section_chunks:
            chunks.append({"page": int(page), "text": chunk_text})

    return chunks


def _embed_texts_openai(
    texts: list[str],
    api_key: str,
    model: str,
    base_url: str,
) -> list[list[float]]:
    url = base_url.rstrip("/") + "/embeddings"
    payload = {"model": model, "input": texts}
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
    data_items = sorted(data_items, key=lambda item: item.get("index", 0))
    return [item.get("embedding", []) for item in data_items]


def embed_and_store_chunks(
    document_id: int,
    db: Session,
    model: str,
    overwrite: bool = False,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> dict:
    document = db.get(Document, document_id)
    if not document:
        raise ValueError(f"Document {document_id} not found")

    existing = (
        db.query(Chunk.id)
        .filter(Chunk.document_id == document_id)
        .first()
    )
    if existing and not overwrite:
        return {"chunks_created": 0, "embedding_model": model, "skipped": True}

    if model != "text-embedding-3-small":
        logger.warning("Embedding model mismatch. %s", REEMBED_NOTE)

    api_key = os.environ.get("OPENAI_API_KEY") or ""
    if not api_key:
        raise RuntimeError("Set OPENAI_API_KEY before embedding.")
    base_url = os.environ.get("OPENAI_BASE_URL") or "https://api.openai.com/v1"

    try:
        if overwrite:
            db.query(Chunk).filter(Chunk.document_id == document_id).delete(synchronize_session=False)

        chunk_dicts = build_contextual_chunks(
            document_id=document_id,
            db=db,
            max_chars=max_chars,
            include_assets=True,
        )
        if not chunk_dicts:
            document.status = "embedded"
            document.processed_at = dt.datetime.now(dt.timezone.utc)
            document.error_message = None
            db.add(document)
            db.commit()
            return {"chunks_created": 0, "embedding_model": model}

        texts = [chunk["text"] for chunk in chunk_dicts]
        chunks_created = 0

        for start in range(0, len(texts), DEFAULT_BATCH_SIZE):
            batch_texts = texts[start : start + DEFAULT_BATCH_SIZE]
            embeddings = _embed_texts_openai(batch_texts, api_key=api_key, model=model, base_url=base_url)
            for embedding in embeddings:
                if len(embedding) != VECTOR_DIM:
                    raise ValueError(
                        f"embedding_dim_mismatch: expected {VECTOR_DIM}, got {len(embedding)} for model {model}"
                    )
            for offset, embedding in enumerate(embeddings):
                chunk = chunk_dicts[start + offset]
                db.add(
                    Chunk(
                        document_id=document_id,
                        page=chunk["page"],
                        text=chunk["text"],
                        embedding=embedding,
                    )
                )
                chunks_created += 1

        document.status = "embedded"
        document.processed_at = dt.datetime.now(dt.timezone.utc)
        document.error_message = None
        db.add(document)
        db.commit()

        return {"chunks_created": chunks_created, "embedding_model": model}
    except Exception as exc:
        logger.exception("Failed to embed document %s", document_id)
        document.status = "failed"
        document.error_message = str(exc)
        document.processed_at = dt.datetime.now(dt.timezone.utc)
        db.add(document)
        db.commit()
        return {"chunks_created": 0, "embedding_model": model, "error": str(exc)}
