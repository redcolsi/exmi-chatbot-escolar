"""
app/schemas/document.py
========================
Fase 2.2 — Schemas Pydantic para Document y DocumentChunk.
Pydantic v2.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field

from app.models.document import DocumentCategory, DocumentStatus


# ─────────────────────────────────────────────────────────────────────────────
# DOCUMENT
# ─────────────────────────────────────────────────────────────────────────────

class DocumentCreate(BaseModel):
    name:        str              = Field(..., min_length=1, max_length=255)
    description: Optional[str]   = None
    category:    DocumentCategory = DocumentCategory.GENERAL
    is_active:   bool             = True


class DocumentUpdate(BaseModel):
    name:        Optional[str]             = None
    description: Optional[str]            = None
    category:    Optional[DocumentCategory] = None
    is_active:   Optional[bool]           = None


class DocumentOut(BaseModel):
    id:                int
    name:              str
    description:       Optional[str]
    category:          DocumentCategory
    original_filename: str
    file_type:         str
    status:            DocumentStatus
    chunk_count:       int
    is_active:         bool
    uploaded_by:       Optional[str]
    created_at:        datetime
    updated_at:        datetime
    error_message:     Optional[str] = None

    class Config:
        from_attributes = True


class DocumentListOut(BaseModel):
    items: List[DocumentOut]
    total: int
    page:  int
    size:  int


# ─────────────────────────────────────────────────────────────────────────────
# DOCUMENT CHUNK
# ─────────────────────────────────────────────────────────────────────────────

class ChunkOut(BaseModel):
    id:             int
    document_id:    int
    chunk_index:    int
    section_title:  Optional[str]
    article_title:  Optional[str]
    page_number:    Optional[int]
    content:        str
    content_length: int
    block_type:     Optional[str]
    keywords:       Optional[str]
    preview:        Optional[str] = None

    class Config:
        from_attributes = True


class ChunkListOut(BaseModel):
    items:       List[ChunkOut]
    total:       int
    document_id: int


# ─────────────────────────────────────────────────────────────────────────────
# RAG / CHAT  (placeholders para Fase 3 — no modifiques aún)
# ─────────────────────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    conversation_id: Optional[str] = None


class ChatResponse(BaseModel):
    answer:          str
    sources:         List[str] = []
    conversation_id: Optional[str] = None
    mode:            str = "rag"
