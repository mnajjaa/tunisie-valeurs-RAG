# Tunisie Valeurs RAG - AI Coding Guide

## Architecture Overview

**Tunisie Valeurs RAG** is a document-based Retrieval-Augmented Generation (RAG) system for financial research documents. It combines PDF ingestion, vector embeddings, and LLM-powered Q&A.

### Core Data Flow

1. **Document Ingestion**: PDFs downloaded from Tunisie Valeurs website via web scraper (`tv_scraper.py`)
2. **PDF Parsing**: Extract text, tables, and figures using `unstructured` + PyMuPDF (`parse_pdfs.py`)
3. **Structured Text Extraction**: Convert raw blocks into semantic units (`extract_structured_text.py`)
4. **Chunking & Embedding**: Split documents into 2000-char chunks with OpenAI embeddings (`chunk_and_embed.py`)
5. **Storage**: Store in PostgreSQL with pgvector for semantic search (`db/models.py`)
6. **Retrieval**: Query embeddings retrieved via cosine distance, answers generated via LLM (`ask.py` route)

### Database Models

- **Document**: Master record with metadata (title, published_at, source_url, sha256 integrity check, processing status)
- **Chunk**: 1536-dim OpenAI embeddings with page numbers for RAG retrieval
- **DocumentBlock**: Structured text blocks extracted from PDFs (contains text, page, font_size, is_bold)
- **DocumentAsset**: Extracted tables/figures with optional captions from vision models

**Critical**: All models use cascading deletes on document_id ForeignKey.

## Workflow Patterns

### Adding New Documents

```bash
# Manual upload via API
curl -X POST http://localhost:8000/api/documents/upload -F "file=@research.pdf"

# Or scrape from TV website
python scripts/test_scrape_one.py  # Download and register
```

### Processing Pipeline (Run After Upload)

```bash
# 1. Extract text & blocks (requires Unstructured library)
python scripts/run_text_structuring.py --document-id=<id>

# 2. Extract tables/figures with vision models
python scripts/run_caption_assets.py --document-id=<id>

# 3. Chunk & embed with OpenAI (required OPENAI_API_KEY)
python scripts/run_chunk_and_embed.py --document-id=<id> --model text-embedding-3-small

# Re-embed all after model changes:
python scripts/run_chunk_and_embed.py --overwrite
```

### Query Flow

1. Client posts `/api/ask` with question + optional document_id filter
2. Query embedded via OpenAI (must match VECTOR_DIM=1536)
3. Chunks retrieved via pgvector cosine distance (top_k default=6)
4. Context + chunks sent to LLM with system prompt (temp=0.2)
5. Answer includes source citations [Doc id p.page]

## Critical Configuration

### Environment Variables

Required in `.env`:
- `DATABASE_URL`: PostgreSQL connection (must support pgvector extension)
- `OPENAI_API_KEY`: For embeddings & chat
- `OPENAI_EMBEDDING_MODEL`: Default `text-embedding-3-small` (1536 dims)
- `OPENAI_CHAT_MODEL`: Default `gpt-4o-mini`
- `OPENAI_BASE_URL`: Optional, defaults to OpenAI API

### Database Setup

```bash
# Run migrations from backend/ directory:
cd backend
alembic upgrade head

# Create pgvector extension:
psql -d your_db -c "CREATE EXTENSION IF NOT EXISTS vector"
```

## Key Design Patterns

### Service Layer Independence

- **retrieval.py**: Low-level pgvector search (never modifies data)
- **rag_answer.py**: LLM prompt building & inference (stateless)
- **chunk_and_embed.py**: Batch embedding & storage (handles retries, incremental)
- Each service uses dependency injection (FastAPI `Depends(get_db)`)

### Error Handling

- HTTP 500 errors propagate from services with descriptive messages
- Document.status tracks processing state: `pending` → `parsed` → `captioned` → `chunked`
- Document.error_message stores failure details for debugging
- All file I/O uses pathlib Path objects (cross-platform safety)

### Vector Dimension Invariant

- **VECTOR_DIM = 1536** hardcoded across models, service logic, and migrations
- Mismatch causes runtime ValueError (not caught early)
- When changing models: must run `--overwrite` to re-embed all chunks

## API Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/documents/upload` | Register new PDF |
| GET | `/api/documents` | List all documents |
| POST | `/api/ask` | Query with RAG |
| POST | `/api/documents/{id}/add-dummy-chunk` | Testing only |
| GET | `/api/health` | Status check |

## Common Tasks

### Debugging Embedding Failures
Check `Document.error_message` and re-run with `--document-id`:
```python
# Direct Python check:
from app.services.chunk_and_embed import embed_and_store_chunks
with SessionLocal() as db:
    embed_and_store_chunks(document_id=1, db=db, model="text-embedding-3-small")
```

### Updating Asset Captions
Vision models (e.g., GPT-4V) store results in DocumentAsset.caption_text/table_content:
- Status field tracks: `pending` → `completed` or `failed`
- Re-caption via: `python scripts/run_caption_assets.py --overwrite`

### Adding New Routes
- Place in `app/api/routes/` with SQLAlchemy Session dependency
- Use Pydantic models for validation (`app/schemas/`)
- All routes return typed responses for OpenAPI docs

## File Organization

```
backend/app/
  core/          # Config, env loading
  api/           # FastAPI routes, dependencies
  services/      # Business logic (stateless, testable)
  db/            # SQLAlchemy models, session factory
  schemas/       # Pydantic request/response models
scripts/         # Batch processing entry points
```

## Debugging Tips

- FastAPI auto-generates `/docs` (Swagger UI) for endpoint testing
- Enable SQL logging: `logging.getLogger("sqlalchemy.engine").setLevel(DEBUG)`
- Check DB state: `SELECT status, COUNT(*) FROM documents GROUP BY status`
- Vector search test: `/api/documents/{id}/add-dummy-chunk` creates test data

