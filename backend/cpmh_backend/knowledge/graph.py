"""Relações extraídas do texto indexado. Inferência fica marcada como inferida."""

from __future__ import annotations

import re
import uuid

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from cpmh_backend.models import KnowledgeChunk, KnowledgeEntity, KnowledgeRelation

_UNIVERSITY = re.compile(r"Universidade de [A-ZÁÉÍÓÚÂÊÔÃÕÇ][\wÁÉÍÓÚÂÊÔÃÕÇ-]{2,}")
_DOI = re.compile(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.IGNORECASE)


def rebuild_graph(session: Session, library_id: str, document_id: str) -> None:
    old_entities = session.scalars(
        select(KnowledgeEntity).where(KnowledgeEntity.library_id == library_id, KnowledgeEntity.document_id == document_id)
    ).all()
    old_ids = [item.id for item in old_entities]
    if old_ids:
        session.execute(delete(KnowledgeRelation).where(KnowledgeRelation.source_id.in_(old_ids)))
        session.execute(delete(KnowledgeRelation).where(KnowledgeRelation.target_id.in_(old_ids)))
    session.execute(delete(KnowledgeEntity).where(KnowledgeEntity.library_id == library_id, KnowledgeEntity.document_id == document_id))
    chunks = session.scalars(
        select(KnowledgeChunk).where(KnowledgeChunk.document_id == document_id, KnowledgeChunk.deleted.is_(False))
    ).all()
    entities: list[KnowledgeEntity] = []
    for chunk in chunks:
        found: list[tuple[str, str]] = []
        if chunk.section and chunk.element_type in {"title", "subtitle"}:
            found.append((chunk.section[:180], "concept"))
        for match in _UNIVERSITY.findall(chunk.content):
            found.append((match, "institution"))
        for match in _DOI.findall(chunk.content):
            found.append((match, "reference"))
        for name, kind in found:
            entity = KnowledgeEntity(
                id=str(uuid.uuid4()),
                library_id=library_id,
                document_id=document_id,
                chunk_id=chunk.id,
                name=name,
                kind=kind,
                origin="extracted",
            )
            session.add(entity)
            entities.append(entity)
    session.flush()
    by_chunk: dict[str, list[KnowledgeEntity]] = {}
    for entity in entities:
        by_chunk.setdefault(entity.chunk_id, []).append(entity)
    for grouped in by_chunk.values():
        if len(grouped) < 2:
            continue
        first, second = grouped[0], grouped[1]
        session.add(
            KnowledgeRelation(
                id=str(uuid.uuid4()),
                library_id=library_id,
                source_id=first.id,
                target_id=second.id,
                relation="coocorrência",
                origin="inferred",
                chunk_id=first.chunk_id,
                evidence="As duas entidades aparecem no mesmo trecho. Isso não prova uma relação além da coocorrência.",
            )
        )
