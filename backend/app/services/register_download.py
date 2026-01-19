"""
Service for registering and downloading scraped documents.
Handles deduplication, PDF download, and metadata storage.
"""

import hashlib
import os
import re
import unicodedata
from datetime import date
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import requests
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.db.models import Document
from app.db.session import SessionLocal
from app.services.tv_scraper import find_pdf_link


# Storage directory for downloaded PDFs
STORAGE_DIR = Path(__file__).parent.parent.parent / "storage" / "raw_pdfs"
INVALID_PATH_CHARS = re.compile(r'[<>:"/\\|?*]')
WHITESPACE_RE = re.compile(r"\s+")


def ensure_storage_dir() -> Path:
    """Create storage directory if it doesn't exist."""
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    return STORAGE_DIR


def sanitize_component(value: str, default: str = "unknown_source") -> str:
    """Sanitize a path component for Windows-friendly storage."""
    if not value:
        return default
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    cleaned = INVALID_PATH_CHARS.sub("_", ascii_value)
    cleaned = WHITESPACE_RE.sub("_", cleaned)
    cleaned = cleaned.strip("._-")
    if not cleaned:
        return default
    return cleaned[:120]


def compute_sha256_bytes(data: bytes) -> str:
    """Compute SHA256 hash of in-memory data."""
    sha256_hash = hashlib.sha256()
    sha256_hash.update(data)
    return sha256_hash.hexdigest()


def safe_filename(url: str, default: str = "document.pdf") -> str:
    """Extract filename from URL."""
    try:
        parsed = urlparse(url)
        filename = os.path.basename(parsed.path)
        if filename and filename.endswith(".pdf"):
            return filename
    except Exception:
        pass
    return default


def ensure_pdf_extension(filename: str) -> str:
    """Ensure filename ends with .pdf."""
    if filename.lower().endswith(".pdf"):
        return filename
    return f"{filename}.pdf"


def normalize_filename(filename: Optional[str], default: str = "document.pdf") -> str:
    """Normalize filename for safe local storage."""
    name = os.path.basename(filename) if filename else ""
    if not name:
        return default
    return name


def sanitize_filename(filename: Optional[str], default: str = "document.pdf") -> str:
    """Sanitize filename while preserving extension."""
    name = normalize_filename(filename, default=default)
    stem, ext = os.path.splitext(name)
    safe_stem = sanitize_component(stem, default="document")
    ext = ext if ext else ".pdf"
    return f"{safe_stem}{ext}"


def source_directory(source_url: Optional[str]) -> Path:
    """Resolve storage directory for a given source URL."""
    parsed = urlparse(source_url or "")
    source = parsed.netloc or "unknown_source"
    storage_dir = ensure_storage_dir() / sanitize_component(source)
    storage_dir.mkdir(parents=True, exist_ok=True)
    return storage_dir


def unique_destination(directory: Path, filename: str) -> Path:
    """Create a unique file path under directory to avoid overwrites."""
    filename = ensure_pdf_extension(sanitize_filename(filename))
    dest = directory / filename
    counter = 1
    while dest.exists():
        stem, ext = os.path.splitext(filename)
        dest = directory / f"{stem}_{counter}{ext}"
        counter += 1
    return dest


def write_pdf_to_disk(content: bytes, filename: str, source_url: Optional[str]) -> str:
    """Write PDF bytes to disk and return the local path."""
    storage_dir = source_directory(source_url)
    dest = unique_destination(storage_dir, filename)
    with open(dest, "wb") as f:
        f.write(content)
    return str(dest)


def compute_sha256_file(file_path: Path) -> str:
    """Compute SHA256 hash of a file on disk."""
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()


def download_pdf(url: str, *, timeout: int = 60) -> Optional[tuple[bytes, str, str]]:
    """
    Download PDF from URL. Returns (content_bytes, filename, mime_type) on success, None on failure.
    """
    try:
        response = requests.get(url, timeout=timeout, allow_redirects=True)
        response.raise_for_status()

        content_type = response.headers.get("Content-Type", "").lower()
        mime_type = content_type.split(";", 1)[0].strip() if content_type else ""
        header_ok = "pdf" in content_type
        content = response.content
        prefix = content[:1024].lstrip()
        magic_ok = prefix.startswith(b"%PDF")
        if not (header_ok or magic_ok):
            return None
        if not mime_type:
            mime_type = "application/pdf"
        if "pdf" not in mime_type:
            mime_type = "application/pdf"

        # Get filename from URL or use default
        filename = safe_filename(url)
        return content, filename, mime_type
    except Exception:
        return None


def find_existing_by_source(db: Session, source_url: Optional[str]) -> Optional[Document]:
    """Find existing document by source URL or legacy details URL."""
    if not source_url:
        return None
    return (
        db.query(Document)
        .filter(or_(Document.source_url == source_url, Document.details_url == source_url))
        .first()
    )


def parse_published_at(item: dict) -> Optional[date]:
    """Parse published date from scraper item."""
    if item.get("date"):
        try:
            return date.fromisoformat(item["date"])
        except Exception:
            return None
    return None


def download_into_document(
    db: Session,
    *,
    item: dict,
    source_url: str,
    pdf_url: str,
    details_url: Optional[str],
    timeout: int,
    doc: Optional[Document] = None,
) -> Optional[int]:
    """Download PDF and write metadata into a new or existing document."""
    downloaded = download_pdf(pdf_url, timeout=timeout)

    if not downloaded:
        if doc:
            doc.status = "failed"
            doc.error_message = "download_failed_or_not_pdf"
            doc.source_url = source_url
            doc.pdf_url = pdf_url
            doc.details_url = details_url
            db.add(doc)
            db.commit()
            db.refresh(doc)
            return doc.id
        failed_doc = Document(
            filename=safe_filename(pdf_url, default="failed.pdf"),
            source_url=source_url,
            pdf_url=pdf_url,
            details_url=details_url,
            title=item.get("title"),
            published_at=parse_published_at(item),
            local_path=None,
            sha256=None,
            size_bytes=None,
            mime_type=None,
            status="failed",
            error_message="download_failed_or_not_pdf",
        )
        db.add(failed_doc)
        db.commit()
        db.refresh(failed_doc)
        return failed_doc.id

    content, filename, mime_type = downloaded
    sha256 = compute_sha256_bytes(content)

    existing_by_sha = db.query(Document).filter(Document.sha256 == sha256).first()
    if existing_by_sha:
        if doc:
            doc.status = "failed"
            doc.error_message = "duplicate_sha256"
            doc.source_url = source_url
            doc.pdf_url = pdf_url
            doc.details_url = details_url
            db.add(doc)
            db.commit()
            db.refresh(doc)
            return existing_by_sha.id
        return existing_by_sha.id

    published_at = parse_published_at(item)
    local_path = write_pdf_to_disk(content, filename, source_url)
    stored_filename = os.path.basename(local_path)
    size_bytes = len(content)

    if doc is None:
        doc = Document(
            filename=stored_filename,
            source_url=source_url,
            pdf_url=pdf_url,
            details_url=details_url,
            title=item.get("title"),
            published_at=published_at,
            local_path=local_path,
            sha256=sha256,
            size_bytes=size_bytes,
            mime_type=mime_type,
            status="downloaded",
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)
        return doc.id

    doc.filename = stored_filename
    doc.source_url = source_url
    doc.pdf_url = pdf_url
    doc.details_url = details_url
    doc.title = item.get("title")
    doc.published_at = published_at
    doc.local_path = local_path
    doc.sha256 = sha256
    doc.size_bytes = size_bytes
    doc.mime_type = mime_type
    doc.status = "downloaded"
    doc.error_message = None

    db.add(doc)
    db.commit()
    db.refresh(doc)

    return doc.id


def register_and_download(
    db: Session,
    item: dict,
    *,
    timeout: int = 60,
) -> Optional[int]:
    """
    Register a scraped note and download its PDF.

    Args:
        db: Database session
        item: Scraped item dict with keys: title, date, pdf_link, details_link
        timeout: HTTP request timeout in seconds

    Returns:
        Document ID on success, None on failure or if document already exists
    """
    pdf_url = item.get("pdf_link")
    details_link = item.get("details_link")
    source_url = details_link or pdf_url

    if details_link and not pdf_url:
        try:
            pdf_url = find_pdf_link(details_link, timeout=timeout)
        except Exception:
            pdf_url = None

    if not pdf_url:
        if not source_url:
            return None
        existing = find_existing_by_source(db, source_url)
        if existing:
            return None
        pending_doc = Document(
            filename=safe_filename(source_url, default="pending.pdf"),
            source_url=source_url,
            pdf_url=None,
            details_url=details_link,
            title=item.get("title"),
            published_at=parse_published_at(item),
            local_path=None,
            sha256=None,
            size_bytes=None,
            mime_type=None,
            status="pending_pdf",
            error_message="pdf_link_missing",
        )
        db.add(pending_doc)
        db.commit()
        db.refresh(pending_doc)
        return pending_doc.id

    source_url = details_link or pdf_url
    existing_by_source = find_existing_by_source(db, source_url)
    if existing_by_source:
        if existing_by_source.status == "pending_pdf" and not existing_by_source.local_path:
            return download_into_document(
                db,
                item=item,
                source_url=source_url,
                pdf_url=pdf_url,
                details_url=details_link,
                timeout=timeout,
                doc=existing_by_source,
            )
        return None

    return download_into_document(
        db,
        item=item,
        source_url=source_url,
        pdf_url=pdf_url,
        details_url=details_link,
        timeout=timeout,
    )


def register_and_download_batch(
    items: list[dict],
    *,
    timeout: int = 60,
) -> list[int]:
    """
    Register and download multiple scraped items.

    Args:
        items: List of scraped item dicts
        timeout: HTTP request timeout in seconds

    Returns:
        List of document IDs successfully registered
    """
    db = SessionLocal()
    try:
        doc_ids = []
        for item in items:
            doc_id = register_and_download(db, item, timeout=timeout)
            if doc_id:
                doc_ids.append(doc_id)
        return doc_ids
    finally:
        db.close()


def backfill_local_files(*, limit: Optional[int] = None) -> int:
    """
    Backfill local files for documents that have file_data but no local_path.

    Args:
        limit: Optional limit on number of documents to process

    Returns:
        Count of documents updated
    """
    db = SessionLocal()
    try:
        query = db.query(Document).filter(
            Document.file_data.isnot(None),
            or_(Document.local_path.is_(None), Document.local_path == ""),
        )
        if limit:
            query = query.limit(limit)

        updated = 0
        for doc in query.yield_per(10):
            if not doc.file_data:
                continue
            storage_dir = source_directory(doc.source_url)
            base_name = sanitize_filename(doc.filename, default=f"document_{doc.id}.pdf")
            candidate = storage_dir / ensure_pdf_extension(base_name)

            if candidate.exists():
                try:
                    if doc.sha256 and compute_sha256_file(candidate) == doc.sha256:
                        doc.local_path = str(candidate)
                        doc.filename = candidate.name
                        doc.size_bytes = doc.size_bytes or len(doc.file_data)
                        doc.mime_type = doc.mime_type or "application/pdf"
                        db.add(doc)
                        updated += 1
                        continue
                except Exception:
                    pass
                candidate = unique_destination(storage_dir, base_name)

            with open(candidate, "wb") as f:
                f.write(doc.file_data)

            doc.local_path = str(candidate)
            doc.filename = candidate.name
            doc.size_bytes = doc.size_bytes or len(doc.file_data)
            doc.mime_type = doc.mime_type or "application/pdf"
            db.add(doc)
            updated += 1

        db.commit()
        return updated
    finally:
        db.close()
