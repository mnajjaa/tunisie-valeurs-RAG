"""add document assets and page count

Revision ID: 2026_01_20_assets
Revises: 2026_01_19_doc_fields
Create Date: 2026-01-20
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "2026_01_20_assets"
down_revision = "2026_01_19_doc_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("page_count", sa.Integer(), nullable=True))

    op.create_table(
        "document_assets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("asset_type", sa.String(length=20), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("local_path", sa.String(length=1024), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_document_assets_document_id", "document_assets", ["document_id"])


def downgrade() -> None:
    op.drop_index("ix_document_assets_document_id", table_name="document_assets")
    op.drop_table("document_assets")
    op.drop_column("documents", "page_count")
