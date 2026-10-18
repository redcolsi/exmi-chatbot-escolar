"""
app/models/document.py
======================
Fase 2.1 — Modelos Document y DocumentChunk.

INTEGRACIÓN:
  Usa la Base declarativa que YA existe en tu proyecto.
  Ajusta la línea de import según dónde esté tu Base actual:

    Opción A (más común):
        from app.database.database import Base

    Opción B:
        from app.database.base import Base

    Opción C (si está en models/base.py):
        from app.models.base import Base

  Si no sabes cuál es la tuya, busca en tu proyecto:
      grep -r "DeclarativeBase|declarative_base" app/
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import List, Optional

from sqlalchemy import (
    Boolean, DateTime, Enum, ForeignKey,
    Integer, String, Text, func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

# ── AJUSTA ESTE IMPORT a tu configuración existente ──────────────────────────
from app.database.database import Base   # ← cambia si tu ruta es diferente
# ─────────────────────────────────────────────────────────────────────────────


class DocumentStatus(str, enum.Enum):
    PENDING    = "pending"
    PROCESSING = "processing"
    READY      = "ready"
    ERROR      = "error"


class DocumentCategory(str, enum.Enum):
    CONVIVENCIA    = "convivencia"
    ACADEMICO      = "academico"
    ADMINISTRATIVO = "administrativo"
    DOCENTES       = "docentes"
    EVENTOS        = "eventos"
    GENERAL        = "general"


class Document(Base):
    """
    Representa un documento institucional almacenado en el sistema.
    Un Document tiene N DocumentChunk (relación 1:N).
    """
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Metadata del documento
    name:        Mapped[str]           = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    category:    Mapped[DocumentCategory] = mapped_column(
        Enum(DocumentCategory, values_callable=lambda e: [m.value for m in e]),
        nullable=False, default=DocumentCategory.GENERAL, index=True
    )

    # Archivo de origen
    original_filename: Mapped[str]           = mapped_column(String(500), nullable=False)
    file_type:         Mapped[str]           = mapped_column(String(20), nullable=False, default="pdf")
    source_json_path:  Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)

    # Pipeline
    status:        Mapped[DocumentStatus] = mapped_column(
        Enum(DocumentStatus, values_callable=lambda e: [m.value for m in e]),
        nullable=False, default=DocumentStatus.PENDING, index=True
    )
    chunk_count:   Mapped[int]           = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active:     Mapped[bool]          = mapped_column(Boolean, nullable=False, default=True, index=True)

    # Auditoría
    uploaded_by: Mapped[Optional[str]] = mapped_column(String(150), nullable=True)
    created_at:  Mapped[datetime]      = mapped_column(DateTime, nullable=False, server_default=func.now())
    updated_at:  Mapped[datetime]      = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    # Relación 1:N — cascade elimina chunks al eliminar el documento
    chunks: Mapped[List["DocumentChunk"]] = relationship(
        "DocumentChunk",
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="DocumentChunk.chunk_index",
        lazy="select",
    )

    # ── Helpers ───────────────────────────────────────────────────────────
    def mark_processing(self) -> None:
        self.status = DocumentStatus.PROCESSING
        self.error_message = None

    def mark_ready(self, chunk_count: int) -> None:
        self.status = DocumentStatus.READY
        self.chunk_count = chunk_count
        self.error_message = None

    def mark_error(self, message: str) -> None:
        self.status = DocumentStatus.ERROR
        self.error_message = str(message)[:2000]

    def is_ready(self) -> bool:
        return self.status == DocumentStatus.READY and self.is_active

    def __repr__(self) -> str:
        return f"<Document id={self.id} name='{self.name}' status={self.status} chunks={self.chunk_count}>"


class DocumentChunk(Base):
    """
    Bloque de texto extraído de un Document.
    Es la unidad mínima que el RAGService recupera.

    Cada uno de los 161 bloques del Manual de Convivencia
    se almacena como un DocumentChunk independiente.
    """
    __tablename__ = "document_chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # FK al documento padre — CASCADE DELETE
    document_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document: Mapped["Document"] = relationship("Document", back_populates="chunks")

    # Posición y trazabilidad
    chunk_index:   Mapped[int]           = mapped_column(Integer, nullable=False)
    section_title: Mapped[Optional[str]] = mapped_column(String(500), nullable=True, index=True)
    article_title: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    page_number:   Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Contenido principal — fuente de verdad para el RAG
    content:        Mapped[str] = mapped_column(Text, nullable=False)
    content_length: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Clasificación del bloque (paragraph, list, table, title…)
    block_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # Palabras clave extraídas por pdf_to_json.py (guardadas como texto separado por comas)
    keywords: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Auditoría
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())

    # ── Helpers ───────────────────────────────────────────────────────────
    def preview(self, max_chars: int = 120) -> str:
        if len(self.content) <= max_chars:
            return self.content
        return self.content[:max_chars].rsplit(" ", 1)[0] + "…"

    def keywords_list(self) -> List[str]:
        if not self.keywords:
            return []
        return [k.strip() for k in self.keywords.split(",") if k.strip()]

    def __repr__(self) -> str:
        return (
            f"<DocumentChunk id={self.id} doc_id={self.document_id} "
            f"idx={self.chunk_index} len={self.content_length}>"
        )
