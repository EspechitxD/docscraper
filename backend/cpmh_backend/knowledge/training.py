"""Preparação de exemplos. Não executa fine-tuning."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cpmh_backend.models import TrainingExample


def add_example(session: Session, *, kind: str, source: str, approved: bool, payload: dict, document_id: str = "") -> TrainingExample:
    if source == "model_output" and not approved:
        raise ValueError("Resposta gerada pelo modelo não entra no conjunto sem revisão aprovada.")
    if not approved:
        raise ValueError("O exemplo precisa estar marcado como aprovado.")
    item = TrainingExample(
        id=str(uuid.uuid4()),
        kind=kind,
        document_id=document_id,
        source=source,
        approved=True,
        payload=payload,
    )
    session.add(item)
    session.flush()
    return item


def status(session: Session) -> dict:
    approved = session.scalar(select(func.count()).select_from(TrainingExample).where(TrainingExample.approved.is_(True))) or 0
    return {
        "training_executed": False,
        "approved_examples": int(approved),
        "note": "Indexar documentos não treina o modelo. Nenhum fine-tuning foi executado.",
    }
