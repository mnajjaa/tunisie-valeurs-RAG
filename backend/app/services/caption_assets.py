"""
Caption cropped document assets using VLM providers.
"""

from __future__ import annotations

import base64
import datetime as dt
import io
import json
import logging
import os
import urllib.error
import urllib.request
from pathlib import Path

from PIL import Image
from sqlalchemy.orm import Session

from app.db.models import DocumentAsset


logger = logging.getLogger(__name__)

FIGURE_PROMPT = (
    "Ecris en francais. Donne une description concise (1-2 phrases) puis ajoute une section "
    "'Donnees' qui liste les libelles, axes, series, et valeurs lisibles. "
    "Ne devine pas les valeurs. Si c'est un graphique, mentionne les tendances visibles."
)
TABLE_PROMPT = (
    "Ecris en francais. Retourne uniquement un JSON avec les cles caption et content. "
    "caption doit resumer la table et indiquer les tendances ou points cles. "
    "content doit etre une table Markdown si possible, sinon une table en texte brut. "
    "N'ajoute pas d'autre texte hors du JSON."
)
TABLE_TOKENS = ("table", "grid", "tabular")
MAX_ERROR_LENGTH = 2000
DEFAULT_MAX_TOKENS = 512
PROVIDER_ORDER = ("openrouter", "gemini", "grok", "openai")


def _is_table_asset(asset: DocumentAsset) -> bool:
    label = (asset.asset_type or "").lower()
    return any(token in label for token in TABLE_TOKENS)


def _resolve_image_path(image_path: str) -> Path | None:
    if not image_path:
        return None
    normalized = Path(os.path.normpath(image_path))
    if normalized.is_file():
        return normalized
    repo_root = Path(__file__).resolve().parents[3]
    alt = repo_root / normalized
    if alt.is_file():
        return alt
    backend_root = Path(__file__).resolve().parents[2]
    alt = backend_root / normalized
    if alt.is_file():
        return alt
    return None


def load_image(path: str) -> Image.Image:
    resolved = _resolve_image_path(path)
    if not resolved:
        raise FileNotFoundError(f"Image not found: {path}")
    with Image.open(resolved) as img:
        return img.copy()


def _guess_image_format(path: str) -> tuple[str, str]:
    ext = Path(str(path or "")).suffix.lower()
    if ext in {".jpg", ".jpeg"}:
        return "image/jpeg", "JPEG"
    if ext == ".png":
        return "image/png", "PNG"
    if ext == ".webp":
        return "image/webp", "WEBP"
    return "image/jpeg", "JPEG"


def _image_to_data_url(img: Image.Image, image_path: str) -> str:
    mime_type, pil_format = _guess_image_format(image_path)
    buffer = io.BytesIO()
    if pil_format == "JPEG":
        if img.mode in {"RGBA", "P"}:
            img = img.convert("RGB")
        img.save(buffer, format="JPEG", quality=90, optimize=True)
    else:
        img.save(buffer, format=pil_format)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def _extract_chat_content(message: dict) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "text":
                text = item.get("text")
                if text:
                    parts.append(text)
        return "\n".join(parts)
    return ""


def _get_max_tokens(*env_keys: str) -> int:
    for key in env_keys:
        value = os.environ.get(key)
        if value:
            try:
                return max(1, int(value))
            except ValueError:
                continue
    return DEFAULT_MAX_TOKENS


def _caption_openai_compatible(
    asset: DocumentAsset,
    api_key: str,
    model: str,
    base_url: str,
    prompt: str,
    max_tokens: int,
) -> str:
    if not asset.local_path:
        raise FileNotFoundError("Asset has no local_path")
    img = load_image(asset.local_path)
    url = base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": _image_to_data_url(img, asset.local_path)},
                    },
                ],
            }
        ],
        "max_tokens": max_tokens,
    }
    data = json.dumps(payload).encode("utf-8")
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"OpenRouter error {exc.code}: {error_body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"OpenRouter connection error: {exc}") from exc

    result = json.loads(body)
    choices = result.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message") or {}
    return _extract_chat_content(message).strip()


def caption_asset_openrouter(
    asset: DocumentAsset,
    api_key: str,
    model: str,
    base_url: str,
    prompt: str,
    max_tokens: int,
) -> str:
    return _caption_openai_compatible(
        asset=asset,
        api_key=api_key,
        model=model,
        base_url=base_url,
        prompt=prompt,
        max_tokens=max_tokens,
    )


def caption_asset_gemini(
    asset: DocumentAsset,
    api_key: str,
    model: str,
    base_url: str,
    prompt: str,
    max_tokens: int,
) -> str:
    if not asset.local_path:
        raise FileNotFoundError("Asset has no local_path")
    img = load_image(asset.local_path)
    mime_type, _ = _guess_image_format(asset.local_path)
    buffer = io.BytesIO()
    if mime_type == "image/jpeg":
        if img.mode in {"RGBA", "P"}:
            img = img.convert("RGB")
        img.save(buffer, format="JPEG", quality=90, optimize=True)
    elif mime_type == "image/png":
        img.save(buffer, format="PNG")
    elif mime_type == "image/webp":
        img.save(buffer, format="WEBP")
    else:
        img.save(buffer, format="JPEG", quality=90, optimize=True)
        mime_type = "image/jpeg"
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")

    url = base_url.rstrip("/") + f"/models/{model}:generateContent?key={api_key}"
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"text": prompt},
                    {"inline_data": {"mime_type": mime_type, "data": encoded}},
                ],
            }
        ],
        "generationConfig": {"maxOutputTokens": max_tokens},
    }
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"Gemini error {exc.code}: {error_body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Gemini connection error: {exc}") from exc

    result = json.loads(body)
    candidates = result.get("candidates") or []
    if not candidates:
        return ""
    content = candidates[0].get("content") or {}
    parts = content.get("parts") or []
    texts = [part.get("text") for part in parts if isinstance(part, dict) and part.get("text")]
    return "\n".join(texts).strip()


def parse_table_response(text: str) -> tuple[str, str]:
    cleaned = (text or "").strip()
    if not cleaned:
        return "", ""
    candidates = [cleaned]
    if "{" in cleaned and "}" in cleaned:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if end > start:
            candidates.insert(0, cleaned[start : end + 1])
    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict):
            continue
        caption = str(data.get("caption") or "").strip()
        content = data.get("content")
        if isinstance(content, (dict, list)):
            content = json.dumps(content, ensure_ascii=False, indent=2)
        content = str(content or "").strip()
        return caption, content
    first_line, _, _ = cleaned.partition("\n")
    caption = first_line.strip()
    content = cleaned
    return caption, content


def _truncate_error(message: str) -> str:
    text = message or ""
    if len(text) > MAX_ERROR_LENGTH:
        return text[:MAX_ERROR_LENGTH]
    return text


def _resolve_provider_order(provider: str) -> list[str]:
    if provider in ("", "auto", "openrouter"):
        return list(PROVIDER_ORDER)
    return [provider]


def _provider_config(provider: str, openrouter_model: str) -> dict | None:
    if provider == "openrouter":
        api_key = os.environ.get("OPENROUTER_API_KEY") or ""
        if not api_key:
            return None
        model = openrouter_model or os.environ.get("OPENROUTER_MODEL") or "qwen/qwen2.5-vl-32b-instruct"
        base_url = os.environ.get("OPENROUTER_BASE_URL") or "https://openrouter.ai/api/v1"
        max_tokens = _get_max_tokens("OPENROUTER_MAX_TOKENS", "VLM_MAX_TOKENS")
        return {"provider": provider, "api_key": api_key, "model": model, "base_url": base_url, "max_tokens": max_tokens}
    if provider == "gemini":
        api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or ""
        if not api_key:
            return None
        model = os.environ.get("GEMINI_MODEL") or "gemini-1.5-flash"
        base_url = os.environ.get("GEMINI_BASE_URL") or "https://generativelanguage.googleapis.com/v1beta"
        max_tokens = _get_max_tokens("GEMINI_MAX_TOKENS", "GEMINI_MAX_OUTPUT_TOKENS", "VLM_MAX_TOKENS")
        return {"provider": provider, "api_key": api_key, "model": model, "base_url": base_url, "max_tokens": max_tokens}
    if provider == "grok":
        api_key = os.environ.get("GROK_API_KEY") or os.environ.get("XAI_API_KEY") or ""
        if not api_key:
            return None
        model = os.environ.get("GROK_MODEL") or "grok-2-vision"
        base_url = os.environ.get("GROK_BASE_URL") or "https://api.x.ai/v1"
        max_tokens = _get_max_tokens("GROK_MAX_TOKENS", "VLM_MAX_TOKENS")
        return {"provider": provider, "api_key": api_key, "model": model, "base_url": base_url, "max_tokens": max_tokens}
    if provider == "openai":
        api_key = os.environ.get("OPENAI_API_KEY") or ""
        if not api_key:
            return None
        model = os.environ.get("OPENAI_MODEL") or "gpt-4o-mini"
        base_url = os.environ.get("OPENAI_BASE_URL") or "https://api.openai.com/v1"
        max_tokens = _get_max_tokens("OPENAI_MAX_TOKENS", "VLM_MAX_TOKENS")
        return {"provider": provider, "api_key": api_key, "model": model, "base_url": base_url, "max_tokens": max_tokens}
    return None


def caption_document_assets(
    document_id: int | None,
    db: Session,
    provider: str = "openrouter",
    model: str = "qwen/qwen2.5-vl-32b-instruct",
    overwrite: bool = False,
    limit: int = 0,
    skip_tables: bool = False,
) -> dict:
    providers = _resolve_provider_order(provider or "openrouter")

    query = db.query(DocumentAsset.id)
    if document_id is not None:
        query = query.filter(DocumentAsset.document_id == document_id)
        if not overwrite:
            query = query.filter(
                (DocumentAsset.caption_status == "pending") | (DocumentAsset.caption_status.is_(None))
            )
    else:
        if not overwrite:
            query = query.filter(
                (DocumentAsset.caption_status == "pending") | (DocumentAsset.caption_status.is_(None))
            )

    query = query.order_by(DocumentAsset.id.asc())
    if limit:
        query = query.limit(limit)

    processed = 0
    captioned = 0
    failed = 0
    skipped = 0

    asset_rows = query.all()
    asset_ids = [row[0] for row in asset_rows]

    for asset_id in asset_ids:
        asset = db.get(DocumentAsset, asset_id)
        if not asset:
            continue
        is_table = _is_table_asset(asset)
        if is_table and skip_tables:
            skipped += 1
            continue
        if not overwrite and asset.caption_status == "done":
            skipped += 1
            continue

        processed += 1
        prompt = TABLE_PROMPT if is_table else FIGURE_PROMPT
        last_error = ""
        used_label = ""
        caption = ""
        content = ""
        succeeded = False

        provider_configs = []
        for provider_name in providers:
            config = _provider_config(provider_name, model)
            if config:
                provider_configs.append(config)

        if not provider_configs:
            last_error = "no_providers_available"

        for config in provider_configs:
            provider_name = config["provider"]
            try:
                if provider_name == "gemini":
                    response = caption_asset_gemini(
                        asset=asset,
                        api_key=config["api_key"],
                        model=config["model"],
                        base_url=config["base_url"],
                        prompt=prompt,
                        max_tokens=config["max_tokens"],
                    )
                else:
                    response = caption_asset_openrouter(
                        asset=asset,
                        api_key=config["api_key"],
                        model=config["model"],
                        base_url=config["base_url"],
                        prompt=prompt,
                        max_tokens=config["max_tokens"],
                    )

                if is_table:
                    caption, content = parse_table_response(response)
                else:
                    caption, content = response.strip(), ""

                if not caption and not content:
                    raise RuntimeError("Empty caption response")

                used_label = f"{provider_name}:{config['model']}"
                succeeded = True
                break
            except Exception as exc:
                last_error = f"{provider_name}: {exc}"
                logger.exception("Captioning failed for asset %s via %s", asset.id, provider_name)

        if succeeded:
            asset.caption_text = caption or None
            asset.caption_model = used_label if caption else asset.caption_model
            if is_table:
                asset.table_content = content or None
                asset.table_model = used_label if content else asset.table_model
            asset.caption_status = "done"
            asset.caption_error = None
            asset.captioned_at = dt.datetime.now(dt.timezone.utc)
            db.add(asset)
            db.commit()
            captioned += 1
        else:
            asset.caption_status = "failed"
            asset.caption_error = _truncate_error(last_error or "caption_failed")
            asset.captioned_at = dt.datetime.now(dt.timezone.utc)
            db.add(asset)
            db.commit()
            failed += 1

    return {
        "processed": processed,
        "captioned": captioned,
        "failed": failed,
        "skipped": skipped,
        "model_label": "auto" if providers != ["openrouter"] else f"openrouter:{model}",
        "providers": providers,
    }
