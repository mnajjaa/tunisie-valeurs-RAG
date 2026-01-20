"""add caption fields for document assets

Revision ID: 2026_01_23_asset_captions
Revises: 2026_01_22_document_columns
Create Date: 2026-01-23
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "2026_01_23_asset_captions"
down_revision = "2026_01_22_document_columns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("document_assets", sa.Column("caption_text", sa.Text(), nullable=True))
    op.add_column("document_assets", sa.Column("caption_model", sa.String(length=255), nullable=True))
    op.add_column("document_assets", sa.Column("table_content", sa.Text(), nullable=True))
    op.add_column("document_assets", sa.Column("table_model", sa.String(length=255), nullable=True))
    op.add_column(
        "document_assets",
        sa.Column("caption_status", sa.String(length=32), nullable=False, server_default="pending"),
    )
    op.add_column("document_assets", sa.Column("caption_error", sa.Text(), nullable=True))
    op.add_column("document_assets", sa.Column("captioned_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("document_assets", "captioned_at")
    op.drop_column("document_assets", "caption_error")
    op.drop_column("document_assets", "caption_status")
    op.drop_column("document_assets", "table_model")
    op.drop_column("document_assets", "table_content")
    op.drop_column("document_assets", "caption_model")
    op.drop_column("document_assets", "caption_text")
