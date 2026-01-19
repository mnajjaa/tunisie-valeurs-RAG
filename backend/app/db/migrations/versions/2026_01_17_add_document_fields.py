"""add document metadata and tracking columns

Revision ID: 2026_01_17_add_document_fields
Revises: da8561d3d88f
Create Date: 2026-01-17
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "2026_01_17_add_document_fields"
down_revision = "da8561d3d88f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add new columns to documents table
    op.add_column("documents", sa.Column("source_url", sa.String(length=2048), nullable=True))
    op.add_column("documents", sa.Column("details_url", sa.String(length=2048), nullable=True))
    op.add_column("documents", sa.Column("title", sa.String(length=512), nullable=True))
    op.add_column("documents", sa.Column("published_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("documents", sa.Column("local_path", sa.String(length=1024), nullable=True))
    op.add_column("documents", sa.Column("sha256", sa.String(length=64), nullable=True))
    op.add_column("documents", sa.Column("status", sa.String(length=50), nullable=False, server_default="pending"))
    op.add_column("documents", sa.Column("error_message", sa.Text(), nullable=True))
    op.add_column("documents", sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True))
    
    # Create unique constraint on sha256
    op.create_unique_constraint("uq_documents_sha256", "documents", ["sha256"])
    
    # Create index on source_url for quick lookups
    op.create_index("ix_documents_source_url", "documents", ["source_url"])
    
    # Create index on status for filtering
    op.create_index("ix_documents_status", "documents", ["status"])
    
    # Create index on published_at for sorting
    op.create_index("ix_documents_published_at", "documents", ["published_at"])


def downgrade() -> None:
    op.drop_index("ix_documents_published_at", table_name="documents")
    op.drop_index("ix_documents_status", table_name="documents")
    op.drop_index("ix_documents_source_url", table_name="documents")
    op.drop_constraint("uq_documents_sha256", "documents", type_="unique")
    op.drop_column("documents", "processed_at")
    op.drop_column("documents", "error_message")
    op.drop_column("documents", "status")
    op.drop_column("documents", "sha256")
    op.drop_column("documents", "local_path")
    op.drop_column("documents", "published_at")
    op.drop_column("documents", "title")
    op.drop_column("documents", "details_url")
    op.drop_column("documents", "source_url")
