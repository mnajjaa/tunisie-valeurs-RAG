import datetime as dt
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))


def load_env() -> None:
    if os.environ.get("DATABASE_URL"):
        return
    for env_path in (ROOT / ".env", BACKEND_DIR / ".env"):
        if not env_path.exists():
            continue
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())
        if os.environ.get("DATABASE_URL"):
            return


load_env()

from app.services import tv_scraper, register_download  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.db.models import Document  # noqa: E402


def main() -> None:
    min_date = dt.date(2026, 1, 1)
    notes = tv_scraper.get_notes(min_date)[:3]
    print(f"Fetched {len(notes)} notes since {min_date.isoformat()}")

    if not notes:
        return

    doc_ids = register_download.register_and_download_batch(notes)
    print("Inserted IDs:", doc_ids)

    with SessionLocal() as db:
        docs = db.query(Document).filter(Document.id.in_(doc_ids)).all()
        for doc in docs:
            file_data_present = bool(getattr(doc, "file_data", None))
            print(
                "source_url={source_url} pdf_url={pdf_url} local_path={local_path} "
                "sha256={sha256} size_bytes={size_bytes} status={status} "
                "file_data_present={file_data_present}".format(
                    source_url=doc.source_url,
                    pdf_url=doc.pdf_url,
                    local_path=doc.local_path,
                    sha256=doc.sha256,
                    size_bytes=doc.size_bytes,
                    status=doc.status,
                    file_data_present=file_data_present,
                )
            )


if __name__ == "__main__":
    main()
