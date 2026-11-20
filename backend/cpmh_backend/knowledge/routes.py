"""API local do Knowledge AI. O frontend não acessa o banco nem o modelo."""

from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cpmh_backend.api import get_db, require_token
from cpmh_backend.config import get_settings
from cpmh_backend.errors import AppError, UrlRejected
from cpmh_backend.knowledge.index import index_document, purge_document
from cpmh_backend.knowledge.rag import ask
from cpmh_backend.knowledge.reports import compare_documents, write_report
from cpmh_backend.knowledge.runtime import status as runtime_status
from cpmh_backend.knowledge.security import clamp_question
from cpmh_backend.knowledge.training import add_example, status as training_status
from cpmh_backend.models import (
    Document,
    KnowledgeChunk,
    KnowledgeConversation,
    KnowledgeEntity,
    KnowledgeLibrary,
    KnowledgeMessage,
    KnowledgeModel,
    KnowledgeRelation,
    utcnow,
)
from cpmh_backend.security import assert_output_dir_allowed, safe_filename
from cpmh_backend.services.fetch import fetch_url

router = APIRouter(dependencies=[Depends(require_token)])


class AskIn(BaseModel):
    question: str
    scope: str = "project"
    project_id: str | None = None
    document_id: str | None = None
    library_id: str | None = None
    conversation_id: str | None = None


class ConversationIn(BaseModel):
    title: str = "Conversa"
    scope: str = "project"
    project_id: str | None = None
    document_id: str | None = None
    library_id: str | None = None


class ConversationPatch(BaseModel):
    title: str


class CompareIn(BaseModel):
    document_ids: list[str] = Field(min_length=2, max_length=8)
    question: str


class ReportIn(BaseModel):
    document_ids: list[str] = Field(min_length=1, max_length=8)
    question: str
    output_dir: str
    output_name: str = "relatorio_knowledge"


class DownloadIn(BaseModel):
    url: str
    name: str
    consent: bool = False
    sha256: str = ""
    license_name: str = ""
    quantization: str = ""
    kind: str = "llm"
    profile: str = "equilibrado"


class ExampleIn(BaseModel):
    kind: str = "qa"
    source: str = "user_reviewed"
    approved: bool = False
    document_id: str = ""
    payload: dict = Field(default_factory=dict)


def _scope(payload: AskIn) -> dict:
    if payload.scope == "document":
        if not payload.document_id:
            raise HTTPException(status_code=400, detail={"code": "scope", "message": "Escolha um documento."})
        return {"document_id": payload.document_id}
    if payload.scope == "project":
        if not payload.project_id:
            raise HTTPException(status_code=400, detail={"code": "scope", "message": "Escolha um projeto."})
        return {"project_id": payload.project_id}
    if payload.scope == "library":
        if not payload.library_id:
            raise HTTPException(status_code=400, detail={"code": "scope", "message": "Escolha uma biblioteca."})
        return {"library_id": payload.library_id}
    if payload.scope == "global":
        return {}
    raise HTTPException(status_code=400, detail={"code": "scope", "message": "Escopo desconhecido."})


@router.get("/knowledge/status")
def knowledge_status(db: Session = Depends(get_db)):
    documents = db.scalar(select(func.count(func.distinct(KnowledgeChunk.document_id)))) or 0
    chunks = db.scalar(select(func.count()).select_from(KnowledgeChunk).where(KnowledgeChunk.deleted.is_(False))) or 0
    return {
        "documents": int(documents),
        "chunks": int(chunks),
        "runtime": runtime_status(),
        "training": training_status(db),
    }


@router.get("/knowledge/libraries")
def list_libraries(db: Session = Depends(get_db)):
    rows = db.scalars(select(KnowledgeLibrary).order_by(KnowledgeLibrary.created_at)).all()
    return [{"id": item.id, "name": item.name, "project_id": item.project_id} for item in rows]


@router.post("/knowledge/documents/{document_id}/index")
def index_route(document_id: str, db: Session = Depends(get_db)):
    document = db.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Documento não encontrado."})
    return index_document(db, document)


@router.delete("/knowledge/documents/{document_id}")
def remove_from_library(document_id: str, db: Session = Depends(get_db)):
    purge_document(db, document_id)
    return {"removed": document_id}


@router.get("/knowledge/documents")
def indexed_documents(project_id: str = "", db: Session = Depends(get_db)):
    statement = select(KnowledgeChunk.document_id, func.count()).where(KnowledgeChunk.deleted.is_(False)).group_by(KnowledgeChunk.document_id)
    rows = db.execute(statement).all()
    items = []
    for document_id, count in rows:
        document = db.get(Document, document_id)
        if document is None:
            continue
        if project_id and document.project_id != project_id:
            continue
        items.append(
            {
                "document_id": document_id,
                "title": document.title,
                "project_id": document.project_id,
                "chunks": int(count),
                "pages": document.page_count or 0,
            }
        )
    return items


@router.post("/knowledge/ask")
def ask_route(payload: AskIn, db: Session = Depends(get_db)):
    try:
        question = clamp_question(payload.question)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "question", "message": str(exc)}) from exc
    scope = _scope(payload)
    result = ask(db, question, **scope)
    if payload.conversation_id:
        conversation = db.get(KnowledgeConversation, payload.conversation_id)
        if conversation is None:
            raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Conversa não encontrada."})
        if conversation.scope != payload.scope:
            raise HTTPException(status_code=400, detail={"code": "scope", "message": "A conversa pertence a outro escopo."})
        if conversation.scope == "document" and conversation.document_id and conversation.document_id != payload.document_id:
            raise HTTPException(status_code=400, detail={"code": "scope", "message": "A conversa está presa a outro documento."})
        if conversation.scope == "project" and conversation.project_id and conversation.project_id != payload.project_id:
            raise HTTPException(status_code=400, detail={"code": "scope", "message": "A conversa está presa a outro projeto."})
        db.add(KnowledgeMessage(id=str(uuid.uuid4()), conversation_id=conversation.id, role="user", content=question))
        db.add(
            KnowledgeMessage(
                id=str(uuid.uuid4()),
                conversation_id=conversation.id,
                role="assistant",
                content=result["answer"],
                citations=result["citations"],
                mode=result["mode"],
            )
        )
    return result


@router.get("/knowledge/conversations")
def list_conversations(db: Session = Depends(get_db)):
    rows = db.scalars(select(KnowledgeConversation).order_by(KnowledgeConversation.created_at.desc())).all()
    return [
        {
            "id": item.id,
            "title": item.title,
            "scope": item.scope,
            "project_id": item.project_id,
            "document_id": item.document_id,
            "library_id": item.library_id,
        }
        for item in rows
    ]


@router.post("/knowledge/conversations")
def create_conversation(payload: ConversationIn, db: Session = Depends(get_db)):
    if payload.scope not in {"document", "project", "library", "global"}:
        raise HTTPException(status_code=400, detail={"code": "scope", "message": "Escopo desconhecido."})
    item = KnowledgeConversation(
        id=str(uuid.uuid4()),
        title=payload.title.strip() or "Conversa",
        scope=payload.scope,
        project_id=payload.project_id,
        document_id=payload.document_id,
        library_id=payload.library_id,
        created_at=utcnow(),
    )
    db.add(item)
    db.flush()
    return {"id": item.id, "title": item.title, "scope": item.scope}


@router.patch("/knowledge/conversations/{conversation_id}")
def rename_conversation(conversation_id: str, payload: ConversationPatch, db: Session = Depends(get_db)):
    item = db.get(KnowledgeConversation, conversation_id)
    if item is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Conversa não encontrada."})
    item.title = payload.title.strip() or item.title
    return {"id": item.id, "title": item.title}


@router.delete("/knowledge/conversations/{conversation_id}")
def delete_conversation(conversation_id: str, db: Session = Depends(get_db)):
    item = db.get(KnowledgeConversation, conversation_id)
    if item is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Conversa não encontrada."})
    db.delete(item)
    return {"deleted": conversation_id}


@router.get("/knowledge/conversations/{conversation_id}/messages")
def list_messages(conversation_id: str, db: Session = Depends(get_db)):
    rows = db.scalars(
        select(KnowledgeMessage).where(KnowledgeMessage.conversation_id == conversation_id).order_by(KnowledgeMessage.created_at)
    ).all()
    return [
        {"id": item.id, "role": item.role, "content": item.content, "citations": item.citations, "mode": item.mode}
        for item in rows
    ]


@router.post("/knowledge/compare")
def compare_route(payload: CompareIn, db: Session = Depends(get_db)):
    try:
        question = clamp_question(payload.question)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "question", "message": str(exc)}) from exc
    return compare_documents(db, payload.document_ids, question)


@router.post("/knowledge/reports")
def report_route(payload: ReportIn, db: Session = Depends(get_db)):
    try:
        question = clamp_question(payload.question)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "question", "message": str(exc)}) from exc
    try:
        folder = assert_output_dir_allowed(Path(payload.output_dir), install_dir=get_settings().install_dir)
    except AppError as exc:
        raise HTTPException(status_code=400, detail={"code": "output_dir", "message": str(exc)}) from exc
    path = folder / f"{safe_filename(payload.output_name)}.docx"
    return write_report(db, payload.document_ids, question, path)


@router.get("/knowledge/models")
def list_models(db: Session = Depends(get_db)):
    rows = db.scalars(select(KnowledgeModel).order_by(KnowledgeModel.created_at)).all()
    return {
        "runtime": runtime_status(),
        "installed": [
            {
                "id": item.id,
                "kind": item.kind,
                "name": item.name,
                "sha256": item.sha256,
                "license": item.license_name,
                "quantization": item.quantization,
                "size_bytes": item.size_bytes,
                "profile": item.profile,
                "active": item.active,
            }
            for item in rows
        ],
        "catalog": [
            {
                "name": "Qwen2.5 3B Instruct Q4",
                "profile": "equilibrado",
                "license": "Apache-2.0, conferir o arquivo do modelo antes de distribuir",
                "note": "Sugestão. O aplicativo não baixa este arquivo sozinho.",
            },
            {
                "name": "Qwen2.5 0.5B Instruct Q4",
                "profile": "compacto",
                "license": "Apache-2.0, conferir o arquivo do modelo antes de distribuir",
                "note": "Sugestão para máquinas com pouca memória. Sem medição de RAM nesta instalação.",
            },
        ],
    }


@router.post("/knowledge/models/download")
def download_model(payload: DownloadIn, db: Session = Depends(get_db)):
    if payload.consent is not True:
        raise HTTPException(status_code=400, detail={"code": "consent", "message": "O download de modelo exige consentimento."})
    try:
        fetched = fetch_url(payload.url, allow_local=False, max_bytes=8 * 1024 * 1024 * 1024, timeout=60)
    except UrlRejected as exc:
        raise HTTPException(status_code=400, detail={"code": "url", "message": str(exc)}) from exc
    if fetched.kind == "html":
        raise HTTPException(status_code=400, detail={"code": "download", "message": "O endereço devolveu uma página, não um modelo."})
    folder = get_settings().data_dir / "models"
    folder.mkdir(parents=True, exist_ok=True)
    destination = folder / safe_filename(payload.name or "modelo.gguf")
    destination.write_bytes(fetched.data)
    sha = hashlib.sha256(fetched.data).hexdigest()
    size = len(fetched.data)
    if payload.sha256 and payload.sha256.lower() != sha:
        destination.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail={"code": "hash", "message": "O hash do arquivo não confere."})
    item = KnowledgeModel(
        id=str(uuid.uuid4()),
        kind=payload.kind,
        name=payload.name,
        path=str(destination),
        sha256=sha,
        license_name=payload.license_name,
        quantization=payload.quantization,
        size_bytes=size,
        profile=payload.profile,
        active=False,
    )
    db.add(item)
    db.flush()
    return {"id": item.id, "sha256": sha, "size_bytes": size, "loaded": False}


@router.post("/knowledge/models/{model_id}/activate")
def activate_model(model_id: str, db: Session = Depends(get_db)):
    item = db.get(KnowledgeModel, model_id)
    if item is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Modelo não encontrado."})
    for other in db.scalars(select(KnowledgeModel).where(KnowledgeModel.kind == item.kind)).all():
        other.active = other.id == item.id
    return {"id": item.id, "active": True, "llm_ready": runtime_status()["llm_ready"]}


@router.delete("/knowledge/models/{model_id}")
def delete_model(model_id: str, db: Session = Depends(get_db)):
    item = db.get(KnowledgeModel, model_id)
    if item is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Modelo não encontrado."})
    path = Path(item.path)
    root = (get_settings().data_dir / "models").resolve()
    if path.exists() and root in path.resolve().parents:
        path.unlink()
    db.delete(item)
    return {"deleted": model_id}


@router.get("/knowledge/graph")
def graph(library_id: str = "", db: Session = Depends(get_db)):
    entities = db.scalars(select(KnowledgeEntity).where(KnowledgeEntity.library_id == library_id) if library_id else select(KnowledgeEntity)).all()
    relations = db.scalars(select(KnowledgeRelation).where(KnowledgeRelation.library_id == library_id) if library_id else select(KnowledgeRelation)).all()
    return {
        "entities": [
            {"id": item.id, "name": item.name, "kind": item.kind, "origin": item.origin, "chunk_id": item.chunk_id, "document_id": item.document_id}
            for item in entities[:200]
        ],
        "relations": [
            {
                "id": item.id,
                "source_id": item.source_id,
                "target_id": item.target_id,
                "relation": item.relation,
                "origin": item.origin,
                "evidence": item.evidence,
                "chunk_id": item.chunk_id,
            }
            for item in relations[:200]
        ],
    }


@router.post("/knowledge/training/examples")
def create_example(payload: ExampleIn, db: Session = Depends(get_db)):
    try:
        item = add_example(
            db,
            kind=payload.kind,
            source=payload.source,
            approved=payload.approved,
            payload=payload.payload,
            document_id=payload.document_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "example", "message": str(exc)}) from exc
    return {"id": item.id, "approved": item.approved}


@router.get("/knowledge/training/status")
def training_route(db: Session = Depends(get_db)):
    return training_status(db)
