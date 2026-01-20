"""update chunk embedding dimension

Revision ID: 2026_01_24_chunk_embedding_dim
Revises: 2026_01_23_asset_captions
Create Date: 2026-01-24
"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "2026_01_24_chunk_embedding_dim"
down_revision = "2026_01_23_asset_captions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_chunks_embedding_hnsw;")
    op.execute("ALTER TABLE chunks ALTER COLUMN embedding TYPE vector(3072);")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_chunks_embedding_hnsw;")
    op.execute("ALTER TABLE chunks ALTER COLUMN embedding TYPE vector(768);")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_chunks_embedding_hnsw "
        "ON chunks USING hnsw (embedding vector_cosine_ops);"
    )
