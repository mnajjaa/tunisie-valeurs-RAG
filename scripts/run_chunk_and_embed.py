import argparse
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))


def _load_env_file(env_path: Path) -> None:
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key and key not in os.environ:
            os.environ[key] = value.strip().strip("\"'")


def _load_env() -> None:
    _load_env_file(ROOT / ".env")
    _load_env_file(BACKEND_DIR / ".env")


def main() -> None:
    _load_env()
    parser = argparse.ArgumentParser(description="Chunk and embed documents with OpenAI.")
    parser.add_argument("--document-id", type=int, default=None, help="Optional document id.")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing chunks.")
    parser.add_argument("--max-chars", type=int, default=2000, help="Max characters per chunk.")
    parser.add_argument(
        "--model",
        default=os.environ.get("OPENAI_EMBEDDING_MODEL") or "text-embedding-3-small",
        help="Embedding model name.",
    )
    args = parser.parse_args()

    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError("Set OPENAI_API_KEY before running.")

    from app.db.session import SessionLocal  # noqa: E402
    from app.db.models import Document  # noqa: E402
    from app.services.chunk_and_embed import embed_and_store_chunks  # noqa: E402

    with SessionLocal() as db:
        if args.document_id is not None:
            summary = embed_and_store_chunks(
                document_id=args.document_id,
                db=db,
                model=args.model,
                overwrite=args.overwrite,
                max_chars=args.max_chars,
            )
            print(f"{args.document_id}\t{summary}")
            return

        statuses = ("parsed", "captioned")
        doc_ids = (
            db.query(Document.id)
            .filter(Document.status.in_(statuses))
            .order_by(Document.id.asc())
            .all()
        )
        doc_ids = [row[0] for row in doc_ids]

        for doc_id in doc_ids:
            try:
                summary = embed_and_store_chunks(
                    document_id=doc_id,
                    db=db,
                    model=args.model,
                    overwrite=args.overwrite,
                    max_chars=args.max_chars,
                )
                print(f"{doc_id}\t{summary}")
            except Exception as exc:
                print(f"{doc_id}\tfailed\t{exc}")


if __name__ == "__main__":
    main()
