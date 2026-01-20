"""ensure hnsw index on chunks.embedding

Revision ID: 2026_01_26_add_hnsw_index
Revises: 2026_01_25_chunk_embedding_dim_1536
Create Date: 2026-01-26
"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "2026_01_26_add_hnsw_index"
down_revision = "2026_01_25_chunk_embedding_dim_1536"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_chunks_embedding_hnsw;")
    op.execute(
        "CREATE INDEX ix_chunks_embedding_hnsw "
        "ON chunks USING hnsw (embedding vector_cosine_ops);"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_chunks_embedding_hnsw;")
