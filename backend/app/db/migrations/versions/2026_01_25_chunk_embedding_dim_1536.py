"""update chunk embedding dimension to 1536

Revision ID: 2026_01_25_chunk_embedding_dim_1536
Revises: 2026_01_24_chunk_embedding_dim
Create Date: 2026-01-25
"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "2026_01_25_chunk_embedding_dim_1536"
down_revision = "2026_01_24_chunk_embedding_dim"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_chunks_embedding_hnsw;")
    op.execute("DROP INDEX IF EXISTS ix_chunks_embedding_ivfflat;")
    op.execute("ALTER TABLE chunks ALTER COLUMN embedding TYPE vector(1536);")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_chunks_embedding_hnsw "
        "ON chunks USING hnsw (embedding vector_cosine_ops);"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_chunks_embedding_hnsw;")
    op.execute("DROP INDEX IF EXISTS ix_chunks_embedding_ivfflat;")
    op.execute("ALTER TABLE chunks ALTER COLUMN embedding TYPE vector(3072);")
