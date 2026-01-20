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
    parser = argparse.ArgumentParser(description="Caption document assets using VLM providers.")
    parser.add_argument("--document-id", type=int, default=None, help="Optional document id.")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing captions.")
    parser.add_argument("--limit", type=int, default=0, help="Optional limit on assets to process.")
    parser.add_argument("--skip-tables", action="store_true", help="Skip table assets.")
    parser.add_argument(
        "--provider",
        default="auto",
        choices=["auto", "openrouter", "gemini", "grok", "openai"],
        help="Provider selection (default: auto fallback).",
    )
    args = parser.parse_args()

    model = os.environ.get("OPENROUTER_MODEL") or "qwen/qwen2.5-vl-32b-instruct"
    os.environ.setdefault("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    os.environ.setdefault("OPENAI_BASE_URL", "https://api.openai.com/v1")
    os.environ.setdefault("GROK_BASE_URL", "https://api.x.ai/v1")
    os.environ.setdefault("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta")

    from app.db.session import SessionLocal  # noqa: E402
    from app.services.caption_assets import caption_document_assets  # noqa: E402

    with SessionLocal() as db:
        summary = caption_document_assets(
            document_id=args.document_id,
            db=db,
            provider=args.provider,
            model=model,
            overwrite=args.overwrite,
            limit=args.limit,
            skip_tables=args.skip_tables,
        )

    print(summary)


if __name__ == "__main__":
    main()
