"""
Parse PDF layout to extract tables and figures/images as cropped assets.
"""

from __future__ import annotations

import datetime as dt
import io
import logging
import os
import re
import shutil
from pathlib import Path
from typing import Optional

import fitz  # PyMuPDF
from PIL import Image
from sqlalchemy.orm import Session

from app.db.models import Document, DocumentAsset

try:
    from unstructured.partition.pdf import partition_pdf
except ImportError as exc:
    raise ImportError(
        "The unstructured library with PDF support is required. "
        'Install it via `pip install "unstructured[pdf]"`.'
    ) from exc


logger = logging.getLogger(__name__)

ASSET_ROOT = Path(__file__).resolve().parents[2] / "storage" / "artifacts"
INVALID_PATH_CHARS = re.compile(r'[<>:"/\\|?*]')

TABLE_TOKENS = ("table", "grid", "tabular")
FIGURE_TOKENS = ("figure", "image", "chart", "graph", "logo", "photo")



def _sanitize_filename(value: str) -> str:
    cleaned = INVALID_PATH_CHARS.sub("_", value)
    cleaned = cleaned.strip("._-")
    return cleaned or "asset"


def _asset_type(category: str) -> Optional[str]:
    label = (category or "").lower()
    if any(token in label for token in TABLE_TOKENS):
        return "table"
    if any(token in label for token in FIGURE_TOKENS):
        return "figure"
    return None


def _asset_dir(document_id: int, asset_type: str) -> Path:
    subfolder = "tables" if asset_type == "table" else "figures"
    path = ASSET_ROOT / str(document_id) / subfolder
    path.mkdir(parents=True, exist_ok=True)
    return path


def _tmp_block_dir(document_id: int, pdf_stem: str) -> Path:
    safe_stem = _sanitize_filename(pdf_stem)
    path = ASSET_ROOT / str(document_id) / "tmp_blocks" / safe_stem
    path.mkdir(parents=True, exist_ok=True)
    return path


def _point_xy(point) -> Optional[tuple[float, float]]:
    if hasattr(point, "x") and hasattr(point, "y"):
        return float(point.x), float(point.y)
    if isinstance(point, (list, tuple)) and len(point) >= 2:
        return float(point[0]), float(point[1])
    return None


def _crop_with_pymupdf(
    pdf_doc: fitz.Document,
    page_number: int,
    coords,
    dest_path: Path,
) -> bool:
    if not coords or not getattr(coords, "points", None):
        return False

    points = []
    for point in coords.points:
        xy = _point_xy(point)
        if xy:
            points.append(xy)

    if not points:
        return False

    x_vals = [pt[0] for pt in points]
    y_vals = [pt[1] for pt in points]
    x0, y0 = float(min(x_vals)), float(min(y_vals))
    x1, y1 = float(max(x_vals)), float(max(y_vals))
    if x1 <= x0 or y1 <= y0:
        return False

    page = pdf_doc.load_page(page_number - 1)
    dpi = 300
    mat = fitz.Matrix(dpi / 72.0, dpi / 72.0)
    pix = page.get_pixmap(matrix=mat)

    image = Image.open(io.BytesIO(pix.tobytes()))
    img_w, img_h = image.size

    # --- Option B: expand crop box to include nearby caption/title text ---
    bbox_w = max(1.0, x1 - x0)
    bbox_h = max(1.0, y1 - y0)

    x_margin = bbox_w * CAPTION_MARGIN_X_RATIO
    top_margin = bbox_h * CAPTION_MARGIN_TOP_RATIO
    bottom_margin = bbox_h * CAPTION_MARGIN_BOTTOM_RATIO

    x0e = int(max(0, x0 - x_margin))
    x1e = int(min(img_w, x1 + x_margin))
    y0e = int(max(0, y0 - top_margin))
    y1e = int(min(img_h, y1 + bottom_margin))

    if x1e <= x0e or y1e <= y0e:
        return False

    crop_img = image.crop((x0e, y0e, x1e, y1e))
    crop_img.save(dest_path)
    return True



def parse_pdf_layout(document_id: int, db: Session) -> dict:
    """
    Parse a PDF document to extract tables/figures as image assets.

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
        return {"document_id": document_id, "status": "failed", "error": error, "assets": 0}

    assets_created = 0
    try:
        pdf_stem = Path(document.local_path).stem
        block_output_dir = _tmp_block_dir(document_id, pdf_stem)
        elements = partition_pdf(
            filename=document.local_path,
            strategy="hi_res",
            infer_table_structure=True,
            skip_infer_table_types="[]",
            model_name="yolox",
            extract_images_in_pdf=True,
            extract_image_block_types=["Image", "Table"],
            extract_image_block_to_payload=False,
            extract_image_block_output_dir=str(block_output_dir),
        )

        with fitz.open(document.local_path) as pdf_doc:
            document.page_count = pdf_doc.page_count
            for idx, element in enumerate(elements):
                meta = element.metadata or {}
                category = (element.category or type(element).__name__).lower()
                asset_type = _asset_type(category)
                if not asset_type:
                    continue

                page_number = getattr(meta, "page_number", None)
                coords = getattr(meta, "coordinates", None)
                image_path = getattr(meta, "image_path", None)

                if not page_number:
                    logger.warning("Skipping asset without page_number for doc %s", document_id)
                    continue

                saved = False
                if image_path and os.path.isfile(image_path):
                    try:
                        dest_dir = _asset_dir(document_id, asset_type)
                        dest_name = _sanitize_filename(Path(image_path).name)
                        dest_path = dest_dir / dest_name
                        shutil.move(image_path, dest_path)
                        saved = True
                    except Exception:
                        logger.exception("Failed to move extracted image for doc %s", document_id)

                if not saved and coords:
                    try:
                        dest_dir = _asset_dir(document_id, asset_type)
                        filename = _sanitize_filename(f"{pdf_stem}_{category}_{page_number}_{idx}.png")
                        dest_path = dest_dir / filename
                        saved = _crop_with_pymupdf(pdf_doc, page_number, coords, dest_path)
                    except Exception:
                        logger.exception("Failed to crop asset for doc %s", document_id)

                if not saved:
                    continue

                asset = DocumentAsset(
                    document_id=document_id,
                    asset_type=asset_type,
                    page_number=page_number,
                    local_path=str(dest_path),
                )
                db.add(asset)
                assets_created += 1

        document.status = "parsed"
        document.processed_at = dt.datetime.now(dt.timezone.utc)
        document.error_message = None
        db.add(document)
        db.commit()

        for file in block_output_dir.rglob("*"):
            try:
                if file.is_file():
                    file.unlink()
            except Exception:
                logger.exception("Failed to cleanup temp block %s", file)
        return {
            "document_id": document_id,
            "status": document.status,
            "assets": assets_created,
            "page_count": document.page_count,
        }
    except Exception as exc:
        logger.exception("Failed to parse PDF layout for doc %s", document_id)
        document.status = "failed"
        document.error_message = str(exc)
        document.processed_at = dt.datetime.now(dt.timezone.utc)
        db.add(document)
        db.commit()
        return {"document_id": document_id, "status": "failed", "error": str(exc), "assets": 0}
