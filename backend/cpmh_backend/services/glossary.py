from __future__ import annotations

import csv
import io
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from cpmh_backend.errors import AppError
from cpmh_backend.models import Glossary, GlossaryTerm, utcnow

STARTER_NAME = "Glossário inicial CPMH"
STARTER_TERMS = [
    ("Ti6Al4V", "", "liga de titânio", True),
    ("ISO 13485", "", "norma", True),
    ("CPMH", "", "nome próprio", True),
    ("screw", "parafuso", "componente mecânico", False),
    ("plate", "placa", "implante", False),
    ("bone cement", "cimento ósseo", "material", False),
    ("surgical guide", "guia cirúrgico", "dispositivo", False),
]


def ensure_starter_glossary(session: Session) -> Glossary:
    existing = session.scalar(select(Glossary).where(Glossary.name == STARTER_NAME))
    if existing is not None:
        return existing
    glossary = Glossary(
        id=str(uuid.uuid4()),
        name=STARTER_NAME,
        description="Glossário editável de exemplo. Não é um dicionário médico completo.",
        created_at=utcnow(),
    )
    session.add(glossary)
    session.flush()
    for source, target, context, locked in STARTER_TERMS:
        session.add(
            GlossaryTerm(
                id=str(uuid.uuid4()),
                glossary_id=glossary.id,
                source=source,
                target=target,
                context=context,
                do_not_translate=locked,
                created_at=utcnow(),
            )
        )
    return glossary


def import_terms(session: Session, glossary_id: str, content: str) -> int:
    glossary = session.get(Glossary, glossary_id)
    if glossary is None:
        raise AppError("Glossário não encontrado.", status_code=404, code="not_found")
    reader = csv.DictReader(io.StringIO(content))
    if reader.fieldnames is None:
        raise AppError("O glossário precisa de cabeçalho CSV.")
    fields = {name.strip().lower(): name for name in reader.fieldnames}
    source_key = fields.get("source") or fields.get("termo") or fields.get("origem")
    if not source_key:
        raise AppError("A coluna de termo de origem é obrigatória.")
    target_key = fields.get("target") or fields.get("traducao") or fields.get("tradução")
    context_key = fields.get("context") or fields.get("contexto")
    lock_key = fields.get("do_not_translate") or fields.get("nao_traduzir")
    count = 0
    for row in reader:
        source = (row.get(source_key) or "").strip()
        if not source:
            continue
        locked = str(row.get(lock_key) or "").strip().lower() in {"1", "true", "sim", "yes"}
        session.add(
            GlossaryTerm(
                id=str(uuid.uuid4()),
                glossary_id=glossary.id,
                source=source,
                target=(row.get(target_key) or "").strip() if target_key else "",
                context=(row.get(context_key) or "").strip() if context_key else "",
                do_not_translate=locked,
                created_at=utcnow(),
            )
        )
        count += 1
    return count


def export_terms_csv(session: Session, glossary_id: str) -> str:
    glossary = session.get(Glossary, glossary_id)
    if glossary is None:
        raise AppError("Glossário não encontrado.", status_code=404, code="not_found")
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["source", "target", "context", "do_not_translate"])
    terms = session.scalars(select(GlossaryTerm).where(GlossaryTerm.glossary_id == glossary_id)).all()
    for term in terms:
        writer.writerow([term.source, term.target, term.context, "sim" if term.do_not_translate else "nao"])
    return buffer.getvalue()
