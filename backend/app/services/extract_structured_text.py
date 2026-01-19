"""
Extract structured text blocks from PDFs using PyMuPDF.
"""

from __future__ import annotations

import datetime as dt
import logging
import os
import re
from statistics import median

import fitz  # PyMuPDF
from sqlalchemy.orm import Session

from app.db.models import Document, DocumentBlock


logger = logging.getLogger(__name__)

WHITESPACE_RE = re.compile(r"\s+")
PAGE_NUMBER_RE = re.compile(r"^\d{1,3}$")
BULLET_CHARS = "\u2022\u2013\u25a0\u25aa\u25cf\u25e6\u2023\u00b7\u2219"
LIST_PREFIX_RE = re.compile(
    r"^\s*(?:[-*" + BULLET_CHARS + r"]|\d{1,3}[.)]|[a-zA-Z][.)]|\([a-zA-Z0-9]{1,3}\))\s+"
)
BOILERPLATE_CLEAN_RE = re.compile(r"[\d\W_]+")
HEADER_FOOTER_THRESHOLD = 0.1


def _normalize_text(value: str) -> str:
    return WHITESPACE_RE.sub(" ", value or "").strip()


def is_page_number(text: str) -> bool:
    return bool(PAGE_NUMBER_RE.match((text or "").strip()))


def _normalize_boilerplate(text: str) -> str:
    lowered = (text or "").lower()
    cleaned = BOILERPLATE_CLEAN_RE.sub(" ", lowered)
    return _normalize_text(cleaned)


def _span_is_bold(span: dict) -> bool:
    flags = int(span.get("flags") or 0)
    font_name = (span.get("font") or "").lower()
    return bool(flags & 2) or "bold" in font_name


def _starts_with_lower(text: str) -> bool:
    stripped = (text or "").lstrip()
    return bool(stripped) and stripped[0].islower()


def _uppercase_ratio(text: str) -> float:
    letters = [char for char in (text or "") if char.isalpha()]
    if not letters:
        return 0.0
    upper = sum(1 for char in letters if char.isupper())
    return upper / len(letters)


def _classify_text(text: str, font_size: float, is_bold: bool, median_font_size: float) -> str:
    if LIST_PREFIX_RE.match(text):
        return "LIST_ITEM"
    is_title = False
    if median_font_size > 0 and font_size > median_font_size * 1.2:
        is_title = True
    elif is_bold and len(text) < 120:
        is_title = True

    if is_title:
        if _starts_with_lower(text):
            return "PARAGRAPH"
        if len(text) > 80 and _uppercase_ratio(text) < 0.5:
            return "PARAGRAPH"
        return "TITLE"
    return "PARAGRAPH"


def _finalize_block_type(block_type: str, text: str) -> str:
    if block_type == "TITLE":
        if len(text) > 80 and _uppercase_ratio(text) < 0.5:
            return "PARAGRAPH"
    return block_type


def _append_text(base: str, addition: str, block_type: str) -> str:
    if not base:
        return addition
    if not addition:
        return base
    if block_type == "LIST_ITEM":
        return f"{base}\n{addition}".strip()
    return _normalize_text(f"{base} {addition}")


def _starts_with_upper(text: str) -> bool:
    stripped = (text or "").lstrip()
    return bool(stripped) and stripped[0].isupper()


def _ends_with_period(text: str) -> bool:
    stripped = (text or "").rstrip()
    return stripped.endswith(".")


def _should_merge(current: dict, next_item: dict) -> bool:
    next_type = next_item["block_type"]
    next_text = next_item["text"]
    if current["block_type"] != next_type:
        return False
    if next_type == "TITLE":
        if current["page_number"] != next_item["page_number"]:
            return False
        if len(current["text"]) > 80 or len(next_text) > 80:
            return False
        return True
    if next_type == "LIST_ITEM":
        return True
    if next_type == "PARAGRAPH":
        if _ends_with_period(current["text"]) and _starts_with_upper(next_text):
            return False
        return True
    return False


def _extract_page_items(page: fitz.Page, page_number: int) -> list[dict]:
    items: list[dict] = []
    page_height = float(page.rect.height or 0.0)
    page_dict = page.get_text("dict")
    for block in page_dict.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            line_spans = []
            line_bbox = line.get("bbox")
            min_x0 = min_y0 = max_x1 = max_y1 = None
            for span in line.get("spans", []):
                text = _normalize_text(span.get("text", ""))
                if not text:
                    continue
                span_bbox = span.get("bbox")
                if span_bbox and len(span_bbox) >= 4:
                    x0, y0, x1, y1 = span_bbox[:4]
                    min_x0 = x0 if min_x0 is None else min(min_x0, x0)
                    min_y0 = y0 if min_y0 is None else min(min_y0, y0)
                    max_x1 = x1 if max_x1 is None else max(max_x1, x1)
                    max_y1 = y1 if max_y1 is None else max(max_y1, y1)
                line_spans.append(
                    {
                        "text": text,
                        "font_size": float(span.get("size") or 0.0),
                        "is_bold": _span_is_bold(span),
                        "bbox": span.get("bbox"),
                    }
                )
            if not line_spans:
                continue
            line_text = _normalize_text(" ".join(span["text"] for span in line_spans))
            if not line_text:
                continue
            if is_page_number(line_text):
                continue
            line_font_size = max((span["font_size"] for span in line_spans), default=0.0)
            line_is_bold = any(span["is_bold"] for span in line_spans)
            y0 = y1 = None
            if line_bbox and len(line_bbox) >= 4:
                y0, y1 = line_bbox[1], line_bbox[3]
            elif min_y0 is not None and max_y1 is not None:
                y0, y1 = min_y0, max_y1

            is_header_footer = False
            if page_height > 0 and y0 is not None and y1 is not None:
                top_threshold = page_height * HEADER_FOOTER_THRESHOLD
                bottom_threshold = page_height * (1 - HEADER_FOOTER_THRESHOLD)
                if y1 <= top_threshold or y0 >= bottom_threshold:
                    is_header_footer = True
            boilerplate_key = _normalize_boilerplate(line_text) if is_header_footer else None
            items.append(
                {
                    "page_number": page_number,
                    "text": line_text,
                    "font_size": line_font_size,
                    "is_bold": line_is_bold,
                    "is_header_footer": is_header_footer,
                    "boilerplate_key": boilerplate_key,
                }
            )
    return items


def extract_structured_text(document_id: int, db: Session, overwrite: bool = True) -> dict:
    """
    Extract structured text blocks from a PDF document using PyMuPDF.

    Returns a summary dict with counts and status.
    """
    document = db.get(Document, document_id)
    if not document:
        raise ValueError(f"Document {document_id} not found")

    if not document.local_path or not os.path.isfile(document.local_path):
        error = f"local_path_missing: {document.local_path}"
        document.status = "failed"
        document.error_message = error
        document.processed_at = dt.datetime.now(dt.timezone.utc)
        db.add(document)
        db.commit()
        return {
            "document_id": document_id,
            "pages_processed": 0,
            "blocks_created": 0,
            "titles_count": 0,
            "list_items_count": 0,
            "status": "failed",
            "error": error,
        }

    if not overwrite:
        existing_blocks = (
            db.query(DocumentBlock.id)
            .filter(DocumentBlock.document_id == document_id)
            .first()
        )
        if existing_blocks:
            logger.info("Structured blocks already exist for doc %s; skipping", document_id)
            return {
                "document_id": document_id,
                "pages_processed": 0,
                "blocks_created": 0,
                "titles_count": 0,
                "list_items_count": 0,
            }

    try:
        if overwrite:
            db.query(DocumentBlock).filter(DocumentBlock.document_id == document_id).delete(
                synchronize_session=False
            )

        blocks_to_insert: list[DocumentBlock] = []
        block_index = 0
        pages_processed = 0
        titles_count = 0
        list_items_count = 0

        with fitz.open(document.local_path) as pdf_doc:
            document.page_count = pdf_doc.page_count
            pages_processed = pdf_doc.page_count
            all_pages: list[list[dict]] = []
            boilerplate_pages: dict[str, set[int]] = {}

            for page_number in range(pdf_doc.page_count):
                page = pdf_doc.load_page(page_number)
                items = _extract_page_items(page, page_number + 1)
                all_pages.append(items)
                if not items:
                    continue

                page_candidates = set()
                for item in items:
                    key = item.get("boilerplate_key")
                    if key:
                        page_candidates.add(key)
                for key in page_candidates:
                    boilerplate_pages.setdefault(key, set()).add(page_number + 1)

            boilerplate_keys = {
                key for key, pages in boilerplate_pages.items() if len(pages) >= 6
            }

            for items in all_pages:
                if not items:
                    continue
                filtered_items = [
                    item
                    for item in items
                    if not (
                        item.get("is_header_footer")
                        and item.get("boilerplate_key") in boilerplate_keys
                    )
                ]
                if not filtered_items:
                    continue
                sizes = [item["font_size"] for item in filtered_items if item["font_size"] > 0]
                median_font_size = median(sizes) if sizes else 0.0

                current: dict | None = None
                for item in filtered_items:
                    block_type = _classify_text(
                        item["text"],
                        item["font_size"],
                        item["is_bold"],
                        median_font_size,
                    )
                    next_item = {
                        "page_number": item["page_number"],
                        "block_type": block_type,
                        "text": item["text"],
                        "font_size": item["font_size"],
                        "is_bold": item["is_bold"],
                    }
                    if current and _should_merge(current, next_item):
                        current["text"] = _append_text(current["text"], item["text"], block_type)
                        current["font_size"] = max(current["font_size"], item["font_size"])
                        current["is_bold"] = current["is_bold"] or item["is_bold"]
                        continue

                    if current:
                        final_type = _finalize_block_type(current["block_type"], current["text"])
                        blocks_to_insert.append(
                            DocumentBlock(
                                document_id=document_id,
                                page_number=current["page_number"],
                                block_index=block_index,
                                block_type=final_type,
                                text=current["text"],
                                font_size=current["font_size"] or None,
                                is_bold=current["is_bold"],
                            )
                        )
                        if final_type == "TITLE":
                            titles_count += 1
                        elif final_type == "LIST_ITEM":
                            list_items_count += 1
                        block_index += 1

                    current = next_item

                if current:
                    final_type = _finalize_block_type(current["block_type"], current["text"])
                    blocks_to_insert.append(
                        DocumentBlock(
                            document_id=document_id,
                            page_number=current["page_number"],
                            block_index=block_index,
                            block_type=final_type,
                            text=current["text"],
                            font_size=current["font_size"] or None,
                            is_bold=current["is_bold"],
                        )
                    )
                    if final_type == "TITLE":
                        titles_count += 1
                    elif final_type == "LIST_ITEM":
                        list_items_count += 1
                    block_index += 1

        if blocks_to_insert:
            db.add_all(blocks_to_insert)

        document.status = "text_structured"
        document.processed_at = dt.datetime.now(dt.timezone.utc)
        document.error_message = None
        db.add(document)
        db.commit()

        return {
            "document_id": document_id,
            "pages_processed": pages_processed,
            "blocks_created": len(blocks_to_insert),
            "titles_count": titles_count,
            "list_items_count": list_items_count,
        }
    except Exception as exc:
        logger.exception("Failed to extract structured text for doc %s", document_id)
        document.status = "failed"
        document.error_message = str(exc)
        document.processed_at = dt.datetime.now(dt.timezone.utc)
        db.add(document)
        db.commit()
        return {
            "document_id": document_id,
            "pages_processed": 0,
            "blocks_created": 0,
            "titles_count": 0,
            "list_items_count": 0,
            "status": "failed",
            "error": str(exc),
        }
