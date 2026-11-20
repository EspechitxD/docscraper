"""Indexa o que o pipeline já extraiu. Não abre o PDF de novo."""

from __future__ import annotations

import hashlib
import logging
import re
import uuid

from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from cpmh_backend.knowledge.embeddings import MODEL_ID, embed
from cpmh_backend.knowledge.graph import rebuild_graph
from cpmh_backend.models import (
    Document,
    DocumentElement,
    DocumentPage,
    FormulaRecord,
    ImageAsset,
    KnowledgeChunk,
    KnowledgeEmbedding,
    KnowledgeLibrary,
    RegionRevision,
    TableRecord,
    utcnow,
)

logger = logging.getLogger("cpmh.knowledge")
_MAX_CHARS = 900


def ensure_library(session: Session, project_id: str, name: str = "") -> KnowledgeLibrary:
    library = session.scalar(select(KnowledgeLibrary).where(KnowledgeLibrary.project_id == project_id))
    if library is not None:
        return library
    library = KnowledgeLibrary(id=str(uuid.uuid4()), name=name or "Biblioteca do projeto", project_id=project_id)
    session.add(library)
    session.flush()
    return library


def index_document(session: Session, document: Document) -> dict:
    library = ensure_library(session, document.project_id)
    pages = {
        page.id: page.sequence
        for page in session.scalars(select(DocumentPage).where(DocumentPage.document_id == document.id)).all()
    }
    revisions = {}
    for row in session.scalars(select(RegionRevision).where(RegionRevision.document_id == document.id)).all():
        revisions[row.region_id] = revisions.get(row.region_id, 0) + 1
    desired = _desired_chunks(session, document, pages, revisions)
    existing = session.scalars(select(KnowledgeChunk).where(KnowledgeChunk.document_id == document.id)).all()
    by_source = {chunk.source_element_id: chunk for chunk in existing}
    seen: set[str] = set()
    created = 0
    kept = 0
    for spec in desired:
        seen.add(spec["source_element_id"])
        current = by_source.get(spec["source_element_id"])
        if current is not None and current.content_hash == spec["content_hash"] and not current.deleted:
            kept += 1
            continue
        if current is not None:
            _drop_chunk(session, current)
        chunk = KnowledgeChunk(
            id=str(uuid.uuid4()),
            library_id=library.id,
            document_id=document.id,
            updated_at=utcnow(),
            **spec,
        )
        session.add(chunk)
        session.flush()
        _store_embedding(session, chunk)
        _fts_upsert(session, chunk)
        created += 1
    removed = 0
    for source, chunk in by_source.items():
        if source not in seen:
            _drop_chunk(session, chunk)
            removed += 1
    session.flush()
    rebuild_graph(session, library.id, document.id)
    return {"library_id": library.id, "created": created, "kept": kept, "removed": removed, "chunks": created + kept}


def purge_document(session: Session, document_id: str) -> None:
    chunks = session.scalars(select(KnowledgeChunk).where(KnowledgeChunk.document_id == document_id)).all()
    for chunk in chunks:
        _drop_chunk(session, chunk)


def _desired_chunks(session: Session, document: Document, pages: dict[str, int], revisions: dict[str, int]) -> list[dict]:
    elements = session.scalars(
        select(DocumentElement).where(DocumentElement.document_id == document.id).order_by(DocumentElement.order_index)
    ).all()
    section = ""
    specs: list[dict] = []
    for element in elements:
        if element.skip_export:
            continue
        if element.kind in {"title", "subtitle"} and element.text.strip():
            section = element.text.strip()
        text_value = (element.text or "").strip()
        if not text_value or element.kind in {"header", "footer", "page_number"}:
            continue
        region_id = (element.region_ids or [""])[0]
        page = pages.get((element.page_ids or [""])[0], 0)
        for index, piece in enumerate(_split(text_value)):
            source = f"region:{region_id}:{index}" if region_id else f"element:{element.id}:{index}"
            specs.append(
                _spec(
                    source=source,
                    content=piece,
                    element_type=element.kind,
                    section=section,
                    page=page,
                    region_id=region_id,
                    revision=revisions.get(region_id, 0),
                )
            )
    for table in session.scalars(select(TableRecord).where(TableRecord.document_id == document.id)).all():
        content = _table_text(table)
        if not content:
            continue
        specs.append(
            _spec(
                source=f"table:{table.id}",
                content=content,
                element_type="table",
                section=section,
                page=table.page_sequence or 0,
                region_id="",
                revision=0,
            )
        )
    for image in session.scalars(select(ImageAsset).where(ImageAsset.document_id == document.id)).all():
        caption = (image.caption or "").strip() or "Figura sem legenda."
        content = (
            f"Figura. Legenda: {caption}. "
            "O recorte foi armazenado. O modelo de texto não interpreta os pixels desta imagem."
        )
        page = pages.get(image.page_id or "", 0)
        specs.append(
            _spec(source=f"image:{image.id}", content=content, element_type="image", section=section, page=page, region_id="", revision=0)
        )
    for formula in session.scalars(select(FormulaRecord).where(FormulaRecord.document_id == document.id)).all():
        if (formula.text or "").strip():
            content = f"Fórmula. {formula.text.strip()}"
        else:
            content = "Fórmula preservada como recorte. Não há transcrição confiável."
        page = pages.get(formula.page_id or "", 0)
        specs.append(
            _spec(
                source=f"formula:{formula.id}",
                content=content,
                element_type="formula",
                section=section,
                page=page,
                region_id=formula.region_id or "",
                revision=revisions.get(formula.region_id or "", 0),
            )
        )
    return specs


def _spec(*, source: str, content: str, element_type: str, section: str, page: int, region_id: str, revision: int) -> dict:
    digest = hashlib.sha256(f"{element_type}|{page}|{section}|{content}".encode("utf-8")).hexdigest()
    return {
        "page_sequence": page,
        "section": section[:500],
        "element_type": element_type,
        "content": content,
        "source_region_id": region_id,
        "source_element_id": source,
        "revision_version": revision,
        "content_hash": digest,
        "deleted": False,
    }


def _split(text: str) -> list[str]:
    if len(text) <= _MAX_CHARS:
        return [text]
    sentences = re.split(r"(?<=[.!?])\s+", text)
    pieces: list[str] = []
    buffer = ""
    for sentence in sentences:
        if buffer and len(buffer) + len(sentence) + 1 > _MAX_CHARS:
            pieces.append(buffer.strip())
            buffer = sentence
        else:
            buffer = f"{buffer} {sentence}".strip()
    if buffer.strip():
        pieces.append(buffer.strip())
    return pieces or [text[:_MAX_CHARS]]


def _table_text(table: TableRecord) -> str:
    rows = table.rows or []
    if not rows:
        return ""
    header = [str(cell or "") for cell in rows[0]]
    lines = ["Tabela", "Colunas: " + " | ".join(header)]
    for row in rows[1:]:
        cells = [str(cell or "") for cell in row]
        paired = [f"{header[index] if index < len(header) else ''}: {cell}".strip(": ") for index, cell in enumerate(cells)]
        lines.append(" | ".join(paired))
    if table.notes:
        lines.append(table.notes)
    return "\n".join(lines)


def _store_embedding(session: Session, chunk: KnowledgeChunk) -> None:
    vector = embed(chunk.content)
    session.add(
        KnowledgeEmbedding(
            id=str(uuid.uuid4()),
            chunk_id=chunk.id,
            model_id=MODEL_ID,
            dimensions=len(vector),
            vector=vector,
        )
    )


def _drop_chunk(session: Session, chunk: KnowledgeChunk) -> None:
    session.execute(text("DELETE FROM knowledge_fts WHERE chunk_id = :chunk_id"), {"chunk_id": chunk.id})
    session.execute(delete(KnowledgeEmbedding).where(KnowledgeEmbedding.chunk_id == chunk.id))
    session.delete(chunk)


def _fts_upsert(session: Session, chunk: KnowledgeChunk) -> None:
    session.execute(text("DELETE FROM knowledge_fts WHERE chunk_id = :chunk_id"), {"chunk_id": chunk.id})
    session.execute(
        text("INSERT INTO knowledge_fts (chunk_id, content) VALUES (:chunk_id, :content)"),
        {"chunk_id": chunk.id, "content": chunk.content},
    )
