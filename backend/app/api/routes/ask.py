from __future__ import annotations

import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.services.retrieval import embed_query_openai, search_chunks
from app.services.rag_answer import answer_with_openai


router = APIRouter(tags=["rag"])


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1)
    top_k: int = Field(6, ge=1, le=20)
    document_id: Optional[int] = Field(default=None, examples=[None])


class SourceOut(BaseModel):
    document_id: int
    title: Optional[str]
    page: Optional[int]
    score: Optional[float]
    text_preview: str


class AskResponse(BaseModel):
    answer: str
    sources: list[SourceOut]


@router.post("/ask", response_model=AskResponse)
def ask_question(payload: AskRequest, db: Session = Depends(get_db)) -> AskResponse:
    api_key = os.environ.get("OPENAI_API_KEY") or ""
    base_url = os.environ.get("OPENAI_BASE_URL") or "https://api.openai.com/v1"
    embedding_model = os.environ.get("OPENAI_EMBEDDING_MODEL") or "text-embedding-3-small"
    chat_model = os.environ.get("OPENAI_CHAT_MODEL") or "gpt-4o-mini"

    if not api_key:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY is not set.")

    try:
        query_embedding = embed_query_openai(
            payload.question,
            api_key=api_key,
            model=embedding_model,
            base_url=base_url,
        )
        retrieved = search_chunks(
            db,
            query_embedding=query_embedding,
            top_k=payload.top_k,
            doc_id=payload.document_id,
        )
        if not retrieved:
            return AskResponse(answer="No relevant sources found.", sources=[])

        answer = answer_with_openai(
            question=payload.question,
            retrieved_chunks=retrieved,
            api_key=api_key,
            model=chat_model,
            base_url=base_url,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    sources: list[SourceOut] = []
    for item in retrieved:
        chunk = item.get("chunk")
        document = item.get("document")
        if not chunk or not document:
            continue
        text_preview = (chunk.text or "").replace("\n", " ").strip()
        if len(text_preview) > 240:
            text_preview = text_preview[:240] + "..."
        sources.append(
            SourceOut(
                document_id=document.id,
                title=document.title,
                page=chunk.page,
                score=item.get("score"),
                text_preview=text_preview,
            )
        )

    return AskResponse(answer=answer, sources=sources)
