"""add storage metadata fields for documents

Revision ID: 2026_01_19_doc_fields
Revises: 2026_01_18_add_file_data
Create Date: 2026-01-19
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "2026_01_19_doc_fields"
down_revision = "2026_01_18_add_file_data"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("pdf_url", sa.String(length=2048), nullable=True))
    op.add_column("documents", sa.Column("size_bytes", sa.Integer(), nullable=True))
    op.add_column("documents", sa.Column("mime_type", sa.String(length=128), nullable=True, server_default="application/pdf"))
    op.add_column("documents", sa.Column("scraped_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False))
    op.add_column("documents", sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.create_unique_constraint("uq_documents_source_url", "documents", ["source_url"])


def downgrade() -> None:
    op.drop_constraint("uq_documents_source_url", "documents", type_="unique")
    op.drop_column("documents", "metadata")
    op.drop_column("documents", "scraped_at")
    op.drop_column("documents", "mime_type")
    op.drop_column("documents", "size_bytes")
    op.drop_column("documents", "pdf_url")
