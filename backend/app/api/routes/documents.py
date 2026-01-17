from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime

from app.api.deps import get_db
from app.db.models import Document, Chunk, VECTOR_DIM
from app.schemas.document import DocumentOut

router = APIRouter(tags=["documents"])

@router.post("/documents/upload", response_model=DocumentOut)
async def upload_document(file: UploadFile = File(...), db: Session = Depends(get_db)):
    if not file.filename:
        raise HTTPException(status_code=400, detail="Missing filename")

    # For now: just store metadata. We'll store the actual file later (disk/S3/etc.)
    doc = Document(filename=file.filename)
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


@router.get("/documents", response_model=list[DocumentOut])
def list_documents(db: Session = Depends(get_db)):
    return db.query(Document).order_by(Document.created_at.desc()).all()


@router.post("/documents/{doc_id}/add-dummy-chunk")
def add_dummy_chunk(doc_id: int, db: Session = Depends(get_db)):
    doc = db.get(Document, doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # Dummy embedding (all zeros) just to validate pgvector insert works
    embedding = [0.0] * VECTOR_DIM

    chunk = Chunk(
        document_id=doc_id,
        page=1,
        text="Dummy chunk for testing pgvector insert.",
        embedding=embedding
    )
    db.add(chunk)
    db.commit()
    db.refresh(chunk)

    return {"chunk_id": chunk.id, "doc_id": doc_id, "dim": len(embedding)}
