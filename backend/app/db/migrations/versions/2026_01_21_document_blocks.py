"""add document blocks

Revision ID: 2026_01_21_document_blocks
Revises: 2026_01_20_assets
Create Date: 2026-01-21
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "2026_01_21_document_blocks"
down_revision = "2026_01_20_assets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "document_blocks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("block_index", sa.Integer(), nullable=False),
        sa.Column("block_type", sa.String(length=20), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("font_size", sa.Float(), nullable=True),
        sa.Column("is_bold", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint(
            "document_id",
            "block_index",
            name="uq_document_blocks_document_id_block_index",
        ),
    )
    op.create_index("ix_document_blocks_document_id", "document_blocks", ["document_id"])


def downgrade() -> None:
    op.drop_index("ix_document_blocks_document_id", table_name="document_blocks")
    op.drop_table("document_blocks")
