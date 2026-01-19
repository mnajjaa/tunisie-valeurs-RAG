import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))


def _load_database_url() -> None:
    if os.environ.get("DATABASE_URL"):
        return
    env_path = BACKEND_DIR / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() == "DATABASE_URL":
            os.environ["DATABASE_URL"] = value.strip().strip("\"'")
            return


_load_database_url()

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from sqlalchemy import func  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.db.models import Document, DocumentBlock  # noqa: E402
from app.services.extract_structured_text import extract_structured_text  # noqa: E402


def _resolve_document_id(db: Session, provided: int | None) -> int:
    if provided is not None:
        return provided
    doc = (
        db.query(Document)
        .filter(Document.local_path.isnot(None))
        .order_by(Document.id.desc())
        .first()
    )
    if not doc:
        raise RuntimeError("No document with local_path found.")
    return doc.id


def main() -> None:
    provided_id = int(sys.argv[1]) if len(sys.argv) > 1 else None
    with SessionLocal() as db:
        document_id = _resolve_document_id(db, provided_id)
        result = extract_structured_text(document_id, db, overwrite=True)
        print(f"extract_structured_text result: {result}")

        counts = dict(
            db.query(DocumentBlock.block_type, func.count(DocumentBlock.id))
            .filter(DocumentBlock.document_id == document_id)
            .group_by(DocumentBlock.block_type)
            .all()
        )
        print(
            "block counts:",
            {
                "TITLE": counts.get("TITLE", 0),
                "LIST_ITEM": counts.get("LIST_ITEM", 0),
                "PARAGRAPH": counts.get("PARAGRAPH", 0),
            },
        )

        blocks = (
            db.query(DocumentBlock)
            .filter(DocumentBlock.document_id == document_id)
            .order_by(DocumentBlock.block_index.asc())
            .limit(5)
            .all()
        )
        print("first 5 blocks:")
        for block in blocks:
            text = block.text.replace("\n", " ").strip()
            if len(text) > 160:
                text = text[:160] + "..."
            print(f"{block.block_index}\t{block.block_type}\t{block.page_number}\t{text}")


if __name__ == "__main__":
    main()
