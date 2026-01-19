"""add missing document columns

Revision ID: 2026_01_22_document_columns
Revises: 2026_01_21_document_blocks
Create Date: 2026-01-22
"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "2026_01_22_document_columns"
down_revision = "2026_01_21_document_blocks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS pdf_url VARCHAR(2048);")
    op.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS size_bytes INTEGER;")
    op.execute(
        "ALTER TABLE documents ADD COLUMN IF NOT EXISTS mime_type VARCHAR(128) "
        "DEFAULT 'application/pdf';"
    )
    op.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS page_count INTEGER;")
    op.execute(
        "ALTER TABLE documents ADD COLUMN IF NOT EXISTS scraped_at TIMESTAMPTZ "
        "DEFAULT now();"
    )
    op.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS metadata JSONB;")
    op.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS processed_at TIMESTAMPTZ;")
    op.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS error_message TEXT;")


def downgrade() -> None:
    op.execute("ALTER TABLE documents DROP COLUMN IF EXISTS error_message;")
    op.execute("ALTER TABLE documents DROP COLUMN IF EXISTS processed_at;")
    op.execute("ALTER TABLE documents DROP COLUMN IF EXISTS metadata;")
    op.execute("ALTER TABLE documents DROP COLUMN IF EXISTS scraped_at;")
    op.execute("ALTER TABLE documents DROP COLUMN IF EXISTS page_count;")
    op.execute("ALTER TABLE documents DROP COLUMN IF EXISTS mime_type;")
    op.execute("ALTER TABLE documents DROP COLUMN IF EXISTS size_bytes;")
    op.execute("ALTER TABLE documents DROP COLUMN IF EXISTS pdf_url;")
