from sqlalchemy import String, Text, ForeignKey, DateTime, func, Integer, LargeBinary, Boolean, Float, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from pgvector.sqlalchemy import Vector
from app.db.session import Base

VECTOR_DIM = 768

class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Metadata from scraper
    source_url: Mapped[str | None] = mapped_column(String(2048), nullable=True, unique=True)
    pdf_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    details_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    published_at: Mapped["DateTime | None"] = mapped_column(DateTime(timezone=True), nullable=True)
    scraped_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)

    # File storage and integrity
    local_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    file_data: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True, index=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(128), nullable=True, default="application/pdf")

    # Processing state
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending", index=True)
    error_message: Mapped[str | None] = mapped_column(Text(), nullable=True)
    processed_at: Mapped["DateTime | None"] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    chunks: Mapped[list["Chunk"]] = relationship(back_populates="document", cascade="all, delete-orphan")
    assets: Mapped[list["DocumentAsset"]] = relationship(back_populates="document", cascade="all, delete-orphan")
    blocks: Mapped[list["DocumentBlock"]] = relationship(back_populates="document", cascade="all, delete-orphan")


class DocumentAsset(Base):
    __tablename__ = "document_assets"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True, nullable=False)
    asset_type: Mapped[str] = mapped_column(String(20), nullable=False)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    local_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    created_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    document: Mapped["Document"] = relationship(back_populates="assets")


class DocumentBlock(Base):
    __tablename__ = "document_blocks"
    __table_args__ = (
        UniqueConstraint("document_id", "block_index", name="uq_document_blocks_document_id_block_index"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True, nullable=False)
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    block_index: Mapped[int] = mapped_column(Integer, nullable=False)
    block_type: Mapped[str] = mapped_column(String(20), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    font_size: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_bold: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    created_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    document: Mapped["Document"] = relationship(back_populates="blocks")


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True, nullable=False)

    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(VECTOR_DIM), nullable=False)

    created_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    document: Mapped["Document"] = relationship(back_populates="chunks")
