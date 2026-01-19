"""add document file data column

Revision ID: 2026_01_18_add_file_data
Revises: 2026_01_17_add_document_fields
Create Date: 2026-01-18
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "2026_01_18_add_file_data"
down_revision = "2026_01_17_add_document_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("file_data", sa.LargeBinary(), nullable=True))


def downgrade() -> None:
    op.drop_column("documents", "file_data")
