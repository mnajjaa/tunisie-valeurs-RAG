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

from app.db.session import SessionLocal  # noqa: E402
from app.db.models import Document  # noqa: E402
from app.services.extract_structured_text import extract_structured_text  # noqa: E402


def main() -> None:
    totals = {
        "documents": 0,
        "failed": 0,
        "pages": 0,
        "blocks": 0,
        "titles": 0,
        "list_items": 0,
    }
    statuses = ("parsed", "downloaded", "embedded", "text_structured", "failed")

    with SessionLocal() as db:
        doc_ids = (
            db.query(Document.id)
            .filter(Document.status.in_(statuses), Document.local_path.isnot(None))
            .order_by(Document.id.asc())
            .all()
        )
    doc_ids = [row[0] for row in doc_ids]

    for doc_id in doc_ids:
        totals["documents"] += 1
        with SessionLocal() as db:
            try:
                result = extract_structured_text(doc_id, db, overwrite=True)
            except Exception as exc:
                totals["failed"] += 1
                print(f"{doc_id}\tfailed\terror={exc}")
                continue

        status = result.get("status", "ok")
        if status == "failed":
            totals["failed"] += 1
            error = result.get("error") or "unknown_error"
            print(f"{doc_id}\tfailed\terror={error}")
            continue

        print(
            f"{doc_id}\tok\tpages={result.get('pages_processed', 0)}\t"
            f"blocks={result.get('blocks_created', 0)}\t"
            f"titles={result.get('titles_count', 0)}\t"
            f"list_items={result.get('list_items_count', 0)}"
        )
        totals["pages"] += result.get("pages_processed", 0)
        totals["blocks"] += result.get("blocks_created", 0)
        totals["titles"] += result.get("titles_count", 0)
        totals["list_items"] += result.get("list_items_count", 0)

    print(
        "TOTALS\t"
        f"documents={totals['documents']}\tfailed={totals['failed']}\t"
        f"pages={totals['pages']}\tblocks={totals['blocks']}\t"
        f"titles={totals['titles']}\tlist_items={totals['list_items']}"
    )


if __name__ == "__main__":
    main()
