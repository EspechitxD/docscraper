"""Relatório de um documento já processado: contagens reais e qualidade, lidas do banco."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from cpmh_backend.intelligence import NON_BODY_KINDS
from cpmh_backend.models import Document, DocumentPage, OCRRegion
from cpmh_backend.services.capture import looks_like_interface_text
from cpmh_backend.services.document_validator import validate_extraction


def build_document_report(db: Session, document: Document) -> dict:
    pages = db.scalars(
        select(DocumentPage).where(DocumentPage.document_id == document.id).order_by(DocumentPage.sequence)
    ).all()
    entries: list[dict] = []
    interface_by_page: dict[int, int] = {}
    for page in pages:
        regions = db.scalars(
            select(OCRRegion).where(OCRRegion.page_id == page.id, OCRRegion.deleted.is_(False))
        ).all()
        body = [region for region in regions if region.category not in NON_BODY_KINDS and (region.text or "").strip()]
        texts = [region.text.strip() for region in body]
        interface = looks_like_interface_text(texts)
        interface_chars = sum(len(text) for text in texts) if interface else 0
        interface_by_page[page.sequence] = interface_chars
        confidences = [region.confidence for region in body if region.source == "ocr"]
        methods = sorted({region.source for region in body})
        entries.append(
            {
                "sequence": page.sequence,
                "reported_number": page.reported_number,
                "text": "\n".join(texts),
                "interface_text": "\n".join(texts) if interface else "",
                "confidence": round(sum(confidences) / len(confidences), 1) if confidences else None,
                "method": "+".join(methods),
                "blank": page.blank,
            }
        )
    report = validate_extraction(entries, reported_pages=document.page_count_estimate)
    report["document_id"] = document.id
    report["title"] = document.title
    report["capture_status"] = document.capture_status
    report["note"] = (
        "Páginas informadas pelo site são metadado. 'processed' conta só as páginas que o sistema guardou."
    )
    return report
