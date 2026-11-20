"""A representação documental é refeita a partir das regiões vivas.

Exportadores e a tela de estrutura leem `DocumentElement`. Uma revisão que
alterasse só `OCRRegion` deixaria o arquivo final desatualizado.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from cpmh_backend.models import Document, DocumentElement, RegionRevision, TranslationRecord, utcnow


def record_revision(
    session: Session,
    *,
    region_id: str,
    document_id: str,
    operation: str,
    origin: str,
    before: dict,
    after: dict,
) -> None:
    session.add(
        RegionRevision(
            id=_new_id(),
            region_id=region_id,
            document_id=document_id,
            operation=operation,
            origin=origin,
            original_text=before.get("text", ""),
            revised_text=after.get("text", ""),
            original_category=before.get("category", ""),
            revised_category=after.get("category", ""),
            original_bbox=list(before.get("bbox") or []),
            revised_bbox=list(after.get("bbox") or []),
            created_at=utcnow(),
        )
    )


def refresh_document_representation(session: Session, document: Document) -> None:
    from cpmh_backend.services.pipeline import _rebuild_elements

    translations = session.scalars(select(TranslationRecord).where(TranslationRecord.document_id == document.id)).all()
    elements = session.scalars(select(DocumentElement).where(DocumentElement.document_id == document.id)).all()
    by_element = {item.element_id: item for item in translations if item.element_id}
    carried: dict[str, TranslationRecord] = {}
    for element in elements:
        record = by_element.get(element.id)
        if record is None:
            continue
        for region_id in element.region_ids or []:
            carried[str(region_id)] = record
    _rebuild_elements(session, document)
    session.flush()
    rebuilt = session.scalars(select(DocumentElement).where(DocumentElement.document_id == document.id)).all()
    used: set[str] = set()
    for element in rebuilt:
        for region_id in element.region_ids or []:
            record = carried.get(str(region_id))
            if record is not None and record.id not in used:
                record.element_id = element.id
                used.add(record.id)
                break
    for record in translations:
        if record.id not in used and record.element_id:
            still = session.get(DocumentElement, record.element_id)
            if still is None:
                session.delete(record)


def snapshot_region(region) -> dict:
    return {
        "text": region.text,
        "category": region.category,
        "bbox": [region.x, region.y, region.w, region.h],
    }


def _new_id() -> str:
    import uuid

    return str(uuid.uuid4())
