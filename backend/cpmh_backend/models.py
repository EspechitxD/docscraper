from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def as_utc_iso(value: dt.datetime | None) -> str | None:
    """Horário UTC com sufixo Z. O SQLite devolve datetimes sem fuso."""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=dt.timezone.utc)
    else:
        value = value.astimezone(dt.timezone.utc)
    return value.isoformat().replace("+00:00", "Z")


class Base(DeclarativeBase):
    pass


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="active")
    glossary_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    documents: Mapped[list[Document]] = relationship(back_populates="project", cascade="all, delete-orphan")


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (Index("ix_documents_project", "project_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    origin: Mapped[str] = mapped_column(String(16), default="url")
    url: Mapped[str] = mapped_column(Text, default="")
    normalized_url: Mapped[str] = mapped_column(Text, default="")
    title: Mapped[str] = mapped_column(String(500), default="")
    domain: Mapped[str] = mapped_column(String(255), default="")
    source_kind: Mapped[str] = mapped_column(String(32), default="unknown")
    state: Mapped[str] = mapped_column(String(32), default="draft")
    page_count_estimate: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    language: Mapped[str | None] = mapped_column(String(32), nullable=True)
    progress: Mapped[float] = mapped_column(Float, default=0)
    error_message: Mapped[str] = mapped_column(Text, default="")
    priority: Mapped[int] = mapped_column(Integer, default=0)
    added_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    local_path: Mapped[str] = mapped_column(Text, default="")
    content_sha256: Mapped[str] = mapped_column(String(64), default="")
    capture_status: Mapped[str] = mapped_column(String(32), default="")

    project: Mapped[Project] = relationship(back_populates="documents")
    pages: Mapped[list[DocumentPage]] = relationship(back_populates="document", cascade="all, delete-orphan")
    jobs: Mapped[list[ProcessingJob]] = relationship(back_populates="document", cascade="all, delete-orphan")


class DocumentPage(Base):
    __tablename__ = "document_pages"
    __table_args__ = (Index("ix_pages_document", "document_id", "sequence"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    sequence: Mapped[int] = mapped_column(Integer)
    reported_number: Mapped[str] = mapped_column(String(32), default="")
    image_path: Mapped[str] = mapped_column(Text, default="")
    width: Mapped[int] = mapped_column(Integer, default=0)
    height: Mapped[int] = mapped_column(Integer, default=0)
    captured_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    source_url: Mapped[str] = mapped_column(Text, default="")
    sha256: Mapped[str] = mapped_column(String(64), default="")
    phash: Mapped[str] = mapped_column(String(128), default="")
    state: Mapped[str] = mapped_column(String(32), default="captured")
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    blank: Mapped[bool] = mapped_column(Boolean, default=False)
    partial: Mapped[bool] = mapped_column(Boolean, default=False)

    document: Mapped[Document] = relationship(back_populates="pages")
    regions: Mapped[list[OCRRegion]] = relationship(back_populates="page", cascade="all, delete-orphan")


class Capture(Base):
    __tablename__ = "captures"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    page_id: Mapped[str | None] = mapped_column(ForeignKey("document_pages.id", ondelete="SET NULL"), nullable=True)
    kind: Mapped[str] = mapped_column(String(32), default="page")
    path: Mapped[str] = mapped_column(Text, default="")
    sha256: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)


class OCRRegion(Base):
    __tablename__ = "ocr_regions"
    __table_args__ = (Index("ix_regions_page", "page_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    page_id: Mapped[str] = mapped_column(ForeignKey("document_pages.id", ondelete="CASCADE"))
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    category: Mapped[str] = mapped_column(String(32), default="unknown")
    text: Mapped[str] = mapped_column(Text, default="")
    confidence: Mapped[float] = mapped_column(Float, default=0)
    x: Mapped[float] = mapped_column(Float, default=0)
    y: Mapped[float] = mapped_column(Float, default=0)
    w: Mapped[float] = mapped_column(Float, default=0)
    h: Mapped[float] = mapped_column(Float, default=0)
    language: Mapped[str] = mapped_column(String(32), default="")
    review_state: Mapped[str] = mapped_column(String(20), default="pending")
    original_text: Mapped[str] = mapped_column(Text, default="")
    original_category: Mapped[str] = mapped_column(String(32), default="")
    original_x: Mapped[float] = mapped_column(Float, default=0)
    original_y: Mapped[float] = mapped_column(Float, default=0)
    original_w: Mapped[float] = mapped_column(Float, default=0)
    original_h: Mapped[float] = mapped_column(Float, default=0)
    source: Mapped[str] = mapped_column(String(32), default="ocr")
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    evidence: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    page: Mapped[DocumentPage] = relationship(back_populates="regions")


class RegionRevision(Base):
    __tablename__ = "region_revisions"
    __table_args__ = (Index("ix_revisions_region", "region_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    region_id: Mapped[str] = mapped_column(String(36))
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    operation: Mapped[str] = mapped_column(String(32))
    origin: Mapped[str] = mapped_column(String(32), default="user")
    original_text: Mapped[str] = mapped_column(Text, default="")
    revised_text: Mapped[str] = mapped_column(Text, default="")
    original_category: Mapped[str] = mapped_column(String(32), default="")
    revised_category: Mapped[str] = mapped_column(String(32), default="")
    original_bbox: Mapped[list] = mapped_column(JSON, default=list)
    revised_bbox: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DocumentElement(Base):
    __tablename__ = "document_elements"
    __table_args__ = (Index("ix_elements_document", "document_id", "order_index"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(32), default="paragraph")
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    text: Mapped[str] = mapped_column(Text, default="")
    confidence: Mapped[float] = mapped_column(Float, default=0)
    level: Mapped[int] = mapped_column(Integer, default=0)
    page_ids: Mapped[list] = mapped_column(JSON, default=list)
    region_ids: Mapped[list] = mapped_column(JSON, default=list)
    continued_from: Mapped[str | None] = mapped_column(String(36), nullable=True)
    continued_in: Mapped[str | None] = mapped_column(String(36), nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    skip_export: Mapped[bool] = mapped_column(Boolean, default=False)


class ImageAsset(Base):
    __tablename__ = "images"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    page_id: Mapped[str | None] = mapped_column(ForeignKey("document_pages.id", ondelete="SET NULL"), nullable=True)
    name: Mapped[str] = mapped_column(String(255), default="")
    category: Mapped[str] = mapped_column(String(32), default="image")
    caption: Mapped[str] = mapped_column(Text, default="")
    x: Mapped[float] = mapped_column(Float, default=0)
    y: Mapped[float] = mapped_column(Float, default=0)
    w: Mapped[float] = mapped_column(Float, default=0)
    h: Mapped[float] = mapped_column(Float, default=0)
    path: Mapped[str] = mapped_column(Text, default="")
    sha256: Mapped[str] = mapped_column(String(64), default="")
    width: Mapped[int] = mapped_column(Integer, default=0)
    height: Mapped[int] = mapped_column(Integer, default=0)
    format: Mapped[str] = mapped_column(String(16), default="png")
    confidence: Mapped[float] = mapped_column(Float, default=0)
    review_state: Mapped[str] = mapped_column(String(20), default="pending")


class TableRecord(Base):
    __tablename__ = "tables"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    page_ids: Mapped[list] = mapped_column(JSON, default=list)
    rows: Mapped[list] = mapped_column(JSON, default=list)
    confidence: Mapped[float] = mapped_column(Float, default=0)
    image_path: Mapped[str] = mapped_column(Text, default="")
    review_state: Mapped[str] = mapped_column(String(20), default="pending")
    reliable: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str] = mapped_column(Text, default="")
    x: Mapped[float] = mapped_column(Float, default=0)
    y: Mapped[float] = mapped_column(Float, default=0)
    w: Mapped[float] = mapped_column(Float, default=0)
    h: Mapped[float] = mapped_column(Float, default=0)
    page_sequence: Mapped[int] = mapped_column(Integer, default=0)


class FormulaRecord(Base):
    __tablename__ = "formulas"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    page_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    region_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    text: Mapped[str] = mapped_column(Text, default="")
    latex: Mapped[str] = mapped_column(Text, default="")
    image_path: Mapped[str] = mapped_column(Text, default="")
    confidence: Mapped[float] = mapped_column(Float, default=0)
    reliable: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str] = mapped_column(Text, default="")


class TranslationRecord(Base):
    __tablename__ = "translations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    element_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    source_lang: Mapped[str] = mapped_column(String(32), default="")
    target_lang: Mapped[str] = mapped_column(String(32), default="pt")
    source_text: Mapped[str] = mapped_column(Text, default="")
    translated_text: Mapped[str] = mapped_column(Text, default="")
    mode: Mapped[str] = mapped_column(String(32), default="none")
    provider: Mapped[str] = mapped_column(String(32), default="glossary")
    glossary_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    partial: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Glossary(Base):
    __tablename__ = "glossaries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    project_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    terms: Mapped[list[GlossaryTerm]] = relationship(back_populates="glossary", cascade="all, delete-orphan")


class GlossaryTerm(Base):
    __tablename__ = "glossary_terms"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    glossary_id: Mapped[str] = mapped_column(ForeignKey("glossaries.id", ondelete="CASCADE"))
    source: Mapped[str] = mapped_column(String(500), default="")
    target: Mapped[str] = mapped_column(String(500), default="")
    context: Mapped[str] = mapped_column(String(500), default="")
    do_not_translate: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    glossary: Mapped[Glossary] = relationship(back_populates="terms")


class ProcessingJob(Base):
    __tablename__ = "processing_jobs"
    __table_args__ = (Index("ix_jobs_state", "state", "priority"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    priority: Mapped[int] = mapped_column(Integer, default=0)
    state: Mapped[str] = mapped_column(String(32), default="queued")
    stage: Mapped[str] = mapped_column(String(32), default="queued")
    progress: Mapped[float] = mapped_column(Float, default=0)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    checkpoint: Mapped[dict] = mapped_column(JSON, default=dict)
    options: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    document: Mapped[Document] = relationship(back_populates="jobs")
    steps: Mapped[list[ProcessingStep]] = relationship(back_populates="job", cascade="all, delete-orphan")


class AccessEvent(Base):
    __tablename__ = "access_events"
    __table_args__ = (Index("ix_access_events_job", "job_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("processing_jobs.id", ondelete="CASCADE"))
    document_id: Mapped[str] = mapped_column(String(36), default="")
    project_id: Mapped[str] = mapped_column(String(36), default="")
    state: Mapped[str] = mapped_column(String(40))
    provider: Mapped[str] = mapped_column(String(40), default="none")
    confidence: Mapped[float] = mapped_column(Float, default=0)
    url: Mapped[str] = mapped_column(Text, default="")
    evidence: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ProcessingStep(Base):
    __tablename__ = "processing_steps"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("processing_jobs.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(32), default="done")
    message: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    job: Mapped[ProcessingJob] = relationship(back_populates="steps")


class LogEntry(Base):
    __tablename__ = "logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    level: Mapped[str] = mapped_column(String(16), default="INFO")
    category: Mapped[str] = mapped_column(String(64), default="app")
    message: Mapped[str] = mapped_column(Text, default="")
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ExportedFile(Base):
    __tablename__ = "exported_files"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    job_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    format: Mapped[str] = mapped_column(String(16))
    path: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    size: Mapped[int] = mapped_column(Integer, default=0)
    mode: Mapped[str] = mapped_column(String(32), default="editable")


class UserPreference(Base):
    __tablename__ = "user_preferences"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PreferenceProfile(Base):
    __tablename__ = "preference_profiles"

    name: Mapped[str] = mapped_column(String(120), primary_key=True)
    values: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SchemaMigration(Base):
    __tablename__ = "schema_migrations"

    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    applied_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class KnowledgeLibrary(Base):
    __tablename__ = "knowledge_libraries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    project_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"
    __table_args__ = (Index("ix_knowledge_chunks_doc", "document_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    library_id: Mapped[str] = mapped_column(ForeignKey("knowledge_libraries.id", ondelete="CASCADE"))
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    page_sequence: Mapped[int] = mapped_column(Integer, default=0)
    section: Mapped[str] = mapped_column(Text, default="")
    element_type: Mapped[str] = mapped_column(String(32), default="paragraph")
    content: Mapped[str] = mapped_column(Text, default="")
    source_region_id: Mapped[str] = mapped_column(String(36), default="")
    source_element_id: Mapped[str] = mapped_column(String(36), default="")
    revision_version: Mapped[int] = mapped_column(Integer, default=0)
    content_hash: Mapped[str] = mapped_column(String(64), default="")
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class KnowledgeEmbedding(Base):
    __tablename__ = "knowledge_embeddings"
    __table_args__ = (Index("ix_knowledge_embeddings_chunk", "chunk_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    chunk_id: Mapped[str] = mapped_column(ForeignKey("knowledge_chunks.id", ondelete="CASCADE"))
    model_id: Mapped[str] = mapped_column(String(80))
    dimensions: Mapped[int] = mapped_column(Integer, default=0)
    vector: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class KnowledgeConversation(Base):
    __tablename__ = "knowledge_conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    title: Mapped[str] = mapped_column(String(200), default="Conversa")
    scope: Mapped[str] = mapped_column(String(16), default="project")
    project_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    document_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    library_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class KnowledgeMessage(Base):
    __tablename__ = "knowledge_messages"
    __table_args__ = (Index("ix_knowledge_messages_conversation", "conversation_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("knowledge_conversations.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text, default="")
    citations: Mapped[list] = mapped_column(JSON, default=list)
    mode: Mapped[str] = mapped_column(String(32), default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class KnowledgeEntity(Base):
    __tablename__ = "knowledge_entities"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    library_id: Mapped[str] = mapped_column(String(36))
    document_id: Mapped[str] = mapped_column(String(36), default="")
    chunk_id: Mapped[str] = mapped_column(String(36), default="")
    name: Mapped[str] = mapped_column(String(300))
    kind: Mapped[str] = mapped_column(String(32), default="concept")
    origin: Mapped[str] = mapped_column(String(16), default="extracted")


class KnowledgeRelation(Base):
    __tablename__ = "knowledge_relations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    library_id: Mapped[str] = mapped_column(String(36))
    source_id: Mapped[str] = mapped_column(String(36))
    target_id: Mapped[str] = mapped_column(String(36))
    relation: Mapped[str] = mapped_column(String(64))
    origin: Mapped[str] = mapped_column(String(16), default="extracted")
    chunk_id: Mapped[str] = mapped_column(String(36), default="")
    evidence: Mapped[str] = mapped_column(Text, default="")


class KnowledgeModel(Base):
    __tablename__ = "knowledge_models"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    kind: Mapped[str] = mapped_column(String(16))
    name: Mapped[str] = mapped_column(String(200))
    path: Mapped[str] = mapped_column(Text, default="")
    sha256: Mapped[str] = mapped_column(String(64), default="")
    license_name: Mapped[str] = mapped_column(String(120), default="")
    quantization: Mapped[str] = mapped_column(String(32), default="")
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    profile: Mapped[str] = mapped_column(String(32), default="")
    active: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TrainingExample(Base):
    __tablename__ = "knowledge_training_examples"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    kind: Mapped[str] = mapped_column(String(32))
    document_id: Mapped[str] = mapped_column(String(36), default="")
    source: Mapped[str] = mapped_column(String(32), default="user_reviewed")
    approved: Mapped[bool] = mapped_column(Boolean, default=False)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
