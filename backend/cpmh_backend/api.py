from __future__ import annotations

import csv
import io
import json
import logging
import re
import secrets
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from cpmh_backend.config import get_settings
from cpmh_backend.db import preference_value, repair, session, set_preference
from cpmh_backend.db import DEFAULT_PREFERENCES, backup_now
from cpmh_backend.errors import AppError, UrlRejected
from cpmh_backend.hashing import clamp_bbox, crop_normalized
from cpmh_backend.intelligence import CATEGORIES
from cpmh_backend.models import (
    Document,
    DocumentElement,
    DocumentPage,
    ExportedFile,
    FormulaRecord,
    Glossary,
    GlossaryTerm,
    ImageAsset,
    LogEntry,
    OCRRegion,
    PreferenceProfile,
    RegionRevision,
    ProcessingJob,
    Project,
    TableRecord,
    TranslationRecord,
    UserPreference,
    as_utc_iso,
    utcnow,
)
from cpmh_backend.security import domain_of, normalize_url, safe_filename, validate_import_bytes, validate_url
from cpmh_backend.services.diagnostics import summary
from cpmh_backend.services.glossary import export_terms_csv, import_terms
from cpmh_backend.services.ocr import recognize
from cpmh_backend.services.pipeline import new_id

router = APIRouter()

ACTIVE_STATES = {
    "queued",
    "validating",
    "capturing",
    "processing",
    "ocr",
    "structuring",
    "extracting_images",
    "translating",
    "reconstructing",
    "exporting",
    "paused",
}


def get_db():
    current = session()
    try:
        yield current
        current.commit()
    except Exception:
        current.rollback()
        raise
    finally:
        current.close()


def require_token(request: Request) -> None:
    expected = get_settings().token.encode()
    provided = request.headers.get("x-cpmh-token", "").encode()
    if len(provided) != len(expected) or not secrets.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail={"code": "unauthorized", "message": "Token local ausente ou inválido."})


def raise_app(error: AppError) -> None:
    detail = {"code": error.code, "message": error.message}
    if hasattr(error, "path"):
        detail["path"] = error.path
    raise HTTPException(status_code=error.status_code, detail=detail)


class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""


class ProjectPatch(BaseModel):
    name: str | None = None
    description: str | None = None
    status: str | None = None
    glossary_id: str | None = None


class UrlIn(BaseModel):
    url: str
    priority: int = 0
    title: str = ""


class ImportTextIn(BaseModel):
    text: str
    filename: str = "lista.txt"


class DocumentPatch(BaseModel):
    url: str | None = None
    title: str | None = None
    priority: int | None = None
    confirm_reset: bool = False


class JobIn(BaseModel):
    translate_mode: str = "none"
    selected_region_ids: list[str] = []
    glossary_id: str | None = None
    export_formats: list[str] = []
    export_mode: str = "editable"
    output_name: str | None = None
    output_dir: str | None = None
    collision: str | None = None
    external_translation: bool = False
    external_consent: bool = False
    force_recapture: bool = False
    priority: int | None = None


class ExportIn(BaseModel):
    formats: list[str]
    mode: str = "editable"
    output_name: str
    output_dir: str
    collision: str | None = None
    translate_mode: str = "none"


class RegionIn(BaseModel):
    category: str
    text: str = ""
    x: float
    y: float
    w: float
    h: float


class RegionPatch(BaseModel):
    category: str | None = None
    text: str | None = None
    x: float | None = None
    y: float | None = None
    w: float | None = None
    h: float | None = None
    review_state: str | None = None


class PreferencesIn(BaseModel):
    values: dict


class ProfileIn(BaseModel):
    name: str = "Perfil de trabalho CPMH"


class GlossaryIn(BaseModel):
    name: str
    description: str = ""
    project_id: str | None = None


class AccessObservation(BaseModel):
    url: str = ""
    final_url: str = ""
    status: int = 0
    title: str = ""
    text: str = ""
    markers: list[str] = Field(default_factory=list)
    iframes: list[str] = Field(default_factory=list)
    scripts: list[str] = Field(default_factory=list)


class TermIn(BaseModel):
    source: str
    target: str = ""
    context: str = ""
    do_not_translate: bool = False


class ReorderIn(BaseModel):
    ids: list[str]


class ImagePatch(BaseModel):
    name: str | None = None
    category: str | None = None
    caption: str | None = None
    review_state: str | None = None


class ImageExportIn(BaseModel):
    ids: list[str] = []
    output_dir: str
    collision: str | None = None


def _dt(value):
    return as_utc_iso(value)


def project_out(item: Project, db: Session) -> dict:
    count = db.scalar(select(func.count()).select_from(Document).where(Document.project_id == item.id)) or 0
    return {
        "id": item.id,
        "name": item.name,
        "description": item.description,
        "status": item.status,
        "glossary_id": item.glossary_id,
        "document_count": count,
        "created_at": _dt(item.created_at),
        "updated_at": _dt(item.updated_at),
    }


def document_out(item: Document, db: Session | None = None) -> dict:
    exports = []
    if db is not None:
        rows = db.scalars(select(ExportedFile).where(ExportedFile.document_id == item.id)).all()
        exports = sorted({row.format for row in rows})
    return {
        "id": item.id,
        "project_id": item.project_id,
        "origin": item.origin,
        "url": item.url,
        "title": item.title,
        "domain": item.domain,
        "source_kind": item.source_kind,
        "state": item.state,
        "page_count_estimate": item.page_count_estimate,
        "page_count": item.page_count,
        "language": item.language,
        "progress": item.progress,
        "error_message": item.error_message,
        "priority": item.priority,
        "added_at": _dt(item.added_at),
        "completed_at": _dt(item.completed_at),
        "capture_status": item.capture_status,
        "exported_formats": exports,
    }


def region_out(item: OCRRegion) -> dict:
    return {
        "id": item.id,
        "page_id": item.page_id,
        "document_id": item.document_id,
        "category": item.category,
        "text": item.text,
        "confidence": item.confidence,
        "bbox": [item.x, item.y, item.w, item.h],
        "language": item.language,
        "review_state": item.review_state,
        "source": item.source,
        "deleted": item.deleted,
        "original_text": item.original_text,
        "original_category": item.original_category,
        "original_bbox": [item.original_x, item.original_y, item.original_w, item.original_h],
        "evidence": item.evidence or "",
    }


def _sync_region(db: Session, item: OCRRegion, operation: str, before: dict, origin: str = "user") -> None:
    from cpmh_backend.services.representation import record_revision, refresh_document_representation, snapshot_region

    document = db.get(Document, item.document_id)
    record_revision(
        db,
        region_id=item.id,
        document_id=item.document_id,
        operation=operation,
        origin=origin,
        before=before,
        after=snapshot_region(item),
    )
    if document is not None:
        refresh_document_representation(db, document)
        try:
            with db.begin_nested():
                from cpmh_backend.knowledge.index import index_document

                index_document(db, document)
        except Exception:
            logging.getLogger("cpmh").exception("A revisão foi salva, mas a reindexação falhou")


def job_out(item: ProcessingJob) -> dict:
    return {
        "id": item.id,
        "document_id": item.document_id,
        "priority": item.priority,
        "state": item.state,
        "stage": item.stage,
        "progress": item.progress,
        "attempts": item.attempts,
        "error": item.error,
        "started_at": _dt(item.started_at),
        "finished_at": _dt(item.finished_at),
        "created_at": _dt(item.created_at),
        "checkpoint": item.checkpoint or {},
        "options": item.options or {},
        "steps": [
            {"name": step.name, "state": step.state, "message": step.message, "created_at": _dt(step.created_at)}
            for step in sorted(item.steps, key=lambda step: step.created_at)
        ],
    }


def audit(db: Session, category: str, message: str, details: dict | None = None, level: str = "INFO") -> None:
    redacted = {}
    for key, value in (details or {}).items():
        if key.lower() in {"token", "password", "authorization", "secret", "api_key", "cookie"}:
            redacted[key] = "***"
        else:
            redacted[key] = value
    db.add(LogEntry(id=new_id(), level=level, category=category, message=message[:500], details=redacted, created_at=utcnow()))


def _notify(request: Request) -> None:
    worker = getattr(request.app.state, "worker", None)
    if worker is not None:
        worker.notify()


def _prefs(db: Session) -> dict:
    return {key: preference_value(db, key) for key in DEFAULT_PREFERENCES}


def _domain_timeouts(value) -> dict:
    if not isinstance(value, dict):
        raise HTTPException(status_code=400, detail={"code": "domain_timeouts", "message": "Os timeouts por domínio precisam ser um mapa de host para segundos."})
    cleaned = {}
    if len(value) > 20:
        raise HTTPException(status_code=400, detail={"code": "domain_timeouts", "message": "Use no máximo 20 domínios."})
    for host, seconds in value.items():
        name = str(host).strip().lower()
        if not re.fullmatch(r"[a-z0-9.-]{1,253}", name) or name.startswith(".") or ".." in name:
            raise HTTPException(status_code=400, detail={"code": "domain_timeouts", "message": f"Domínio inválido: {host}"})
        try:
            cleaned[name] = max(3, min(int(float(seconds)), 120))
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail={"code": "domain_timeouts", "message": f"Timeout inválido para {name}."}) from exc
    return cleaned


def _network_allowed(db: Session) -> bool:
    return bool(get_settings().allow_local_network or preference_value(db, "allow_local_network"))


def _parse_urls(text: str) -> list[str]:
    stripped = text.strip()
    if not stripped:
        return []
    first = stripped.splitlines()[0]
    if "," in first or ";" in first:
        sample = first.lower()
        if any(token in sample for token in ["url", "link", "endereco", "endereço"]):
            reader = csv.DictReader(io.StringIO(stripped))
            fields = {name.strip().lower(): name for name in (reader.fieldnames or [])}
            key = fields.get("url") or fields.get("link") or fields.get("endereco") or fields.get("endereço")
            if key:
                return [(row.get(key) or "").strip() for row in reader if (row.get(key) or "").strip()]
    urls = []
    for line in stripped.splitlines():
        item = line.strip()
        if not item or item.startswith("#"):
            continue
        if "," in item and item.lower().startswith("http"):
            item = item.split(",")[0].strip()
        urls.append(item)
    return urls


@router.get("/health", dependencies=[Depends(require_token)])
def health(db: Session = Depends(get_db)):
    return {"ok": True, "app": "CPMH Document Intelligence", "version": get_settings().version}


@router.get("/diagnostics", dependencies=[Depends(require_token)])
def diagnostics(db: Session = Depends(get_db)):
    return summary(db, get_settings())


@router.post("/diagnostics/repair", dependencies=[Depends(require_token)])
def diagnostics_repair(db: Session = Depends(get_db)):
    result = repair(get_settings())
    audit(db, "diagnostics", "Reparo de diretórios executado.")
    return result


@router.post("/diagnostics/backup", dependencies=[Depends(require_token)])
def diagnostics_backup(db: Session = Depends(get_db)):
    path = backup_now(get_settings())
    audit(db, "diagnostics", "Backup do banco criado.", {"path": path})
    return {"path": path}


@router.post("/security/validate-url", dependencies=[Depends(require_token)])
def validate_url_route(payload: UrlIn, db: Session = Depends(get_db)):
    try:
        checked = validate_url(payload.url, allow_local=_network_allowed(db))
    except UrlRejected as exc:
        raise_app(exc)
    return {"url": checked.url, "host": checked.host, "accepted": True}


@router.get("/translation/disclosure", dependencies=[Depends(require_token)])
def translation_disclosure():
    return {
        "leaves_computer": True,
        "purpose": "Traduzir o texto selecionado para português.",
        "data": "Somente o texto das regiões ou elementos escolhidos é enviado. Imagens não são enviadas por este caminho.",
        "service": "O endereço configurado em external_translation_url. Nenhum serviço é contatado sem essa configuração.",
        "cost": "O provedor escolhido pode cobrar pelo uso. Este aplicativo não cobra.",
        "consent": "É necessário marcar o consentimento em cada envio. Não há envio automático.",
    }


@router.get("/preferences", dependencies=[Depends(require_token)])
def get_preferences(db: Session = Depends(get_db)):
    return {"values": _prefs(db), "profiles": [item.name for item in db.scalars(select(PreferenceProfile)).all()]}


@router.put("/preferences", dependencies=[Depends(require_token)])
def put_preferences(payload: PreferencesIn, db: Session = Depends(get_db)):
    for key, value in payload.values.items():
        if key not in DEFAULT_PREFERENCES:
            raise HTTPException(status_code=400, detail={"code": "unknown_preference", "message": f"Preferência desconhecida: {key}"})
        if key == "max_concurrent_jobs":
            value = max(1, min(int(value), 4))
        if key == "max_pages":
            value = max(1, min(int(value), 500))
        if key == "max_download_mb":
            value = max(1, min(int(value), 200))
        if key == "domain_concurrency":
            value = max(1, min(int(value), 4))
        if key == "domain_timeouts":
            value = _domain_timeouts(value)
        if key in {"confidence_high", "confidence_medium"}:
            value = max(0, min(float(value), 100))
        set_preference(db, key, value)
    high = float(preference_value(db, "confidence_high"))
    medium = float(preference_value(db, "confidence_medium"))
    if medium > high:
        raise HTTPException(status_code=400, detail={"code": "threshold", "message": "O limiar intermediário não pode ser maior que o limiar alto."})
    audit(db, "preferences", "Preferências atualizadas.")
    return {"values": _prefs(db)}


@router.post("/preferences/profiles", dependencies=[Depends(require_token)])
def save_profile(payload: ProfileIn, db: Session = Depends(get_db)):
    name = payload.name.strip() or "Perfil de trabalho CPMH"
    values = _prefs(db)
    row = db.get(PreferenceProfile, name)
    if row is None:
        db.add(PreferenceProfile(name=name, values=values, updated_at=utcnow()))
    else:
        row.values = values
        row.updated_at = utcnow()
    set_preference(db, "active_profile", name)
    return {"name": name, "values": values}


@router.post("/preferences/profiles/{name}/apply", dependencies=[Depends(require_token)])
def apply_profile(name: str, db: Session = Depends(get_db)):
    row = db.get(PreferenceProfile, name)
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Perfil não encontrado."})
    for key, value in (row.values or {}).items():
        if key in DEFAULT_PREFERENCES:
            set_preference(db, key, value)
    set_preference(db, "active_profile", name)
    return {"values": _prefs(db)}


@router.get("/projects", dependencies=[Depends(require_token)])
def list_projects(q: str = "", status: str = "", db: Session = Depends(get_db)):
    statement = select(Project).order_by(Project.updated_at.desc())
    if status:
        statement = statement.where(Project.status == status)
    if q:
        statement = statement.where(Project.name.contains(q))
    return [project_out(item, db) for item in db.scalars(statement).all()]


@router.post("/projects", dependencies=[Depends(require_token)])
def create_project(payload: ProjectIn, db: Session = Depends(get_db)):
    item = Project(
        id=str(uuid.uuid4()),
        name=payload.name.strip(),
        description=payload.description.strip(),
        status="active",
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    db.add(item)
    db.flush()
    audit(db, "project", "Projeto criado.", {"id": item.id})
    return project_out(item, db)


@router.get("/projects/{project_id}", dependencies=[Depends(require_token)])
def get_project(project_id: str, db: Session = Depends(get_db)):
    item = db.get(Project, project_id)
    if item is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Projeto não encontrado."})
    return project_out(item, db)


@router.patch("/projects/{project_id}", dependencies=[Depends(require_token)])
def patch_project(project_id: str, payload: ProjectPatch, db: Session = Depends(get_db)):
    item = db.get(Project, project_id)
    if item is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Projeto não encontrado."})
    if payload.name is not None:
        item.name = payload.name.strip()
    if payload.description is not None:
        item.description = payload.description
    if payload.status is not None:
        if payload.status not in {"active", "archived"}:
            raise HTTPException(status_code=400, detail={"code": "status", "message": "Estado de projeto inválido."})
        item.status = payload.status
    if "glossary_id" in payload.model_fields_set:
        item.glossary_id = payload.glossary_id or None
    item.updated_at = utcnow()
    return project_out(item, db)


@router.delete("/projects/{project_id}", dependencies=[Depends(require_token)])
def delete_project(project_id: str, confirm: bool = False, db: Session = Depends(get_db)):
    item = db.get(Project, project_id)
    if item is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Projeto não encontrado."})
    if not confirm:
        raise HTTPException(
            status_code=409,
            detail={"code": "confirmation_required", "message": "Confirme a exclusão. Arquivos já exportados para outras pastas não serão apagados."},
        )
    settings = get_settings()
    folder = settings.projects_dir / project_id
    db.delete(item)
    db.flush()
    if folder.exists():
        import shutil

        shutil.rmtree(folder, ignore_errors=True)
    audit(db, "project", "Projeto excluído da área de trabalho.", {"id": project_id})
    return {"deleted": project_id, "exports_preserved": True}


def _add_url(db: Session, project: Project, raw_url: str, priority: int, title: str) -> tuple[str, dict | None, dict | None]:
    try:
        checked = validate_url(raw_url, allow_local=_network_allowed(db))
    except UrlRejected as exc:
        return "rejected", None, {"url": raw_url, "message": exc.message}
    existing = db.scalar(
        select(Document).where(Document.project_id == project.id, Document.normalized_url == checked.url)
    )
    if existing is not None:
        return "duplicate", document_out(existing, db), None
    item = Document(
        id=str(uuid.uuid4()),
        project_id=project.id,
        origin="url",
        url=raw_url.strip(),
        normalized_url=checked.url,
        title=title.strip() or checked.url,
        domain=domain_of(checked.url),
        source_kind="unknown",
        state="draft",
        priority=max(0, min(priority, 100)),
        added_at=utcnow(),
        progress=0,
    )
    db.add(item)
    db.flush()
    return "added", document_out(item, db), None


@router.post("/projects/{project_id}/documents", dependencies=[Depends(require_token)])
def add_document(project_id: str, payload: UrlIn, db: Session = Depends(get_db)):
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Projeto não encontrado."})
    kind, document, rejected = _add_url(db, project, payload.url, payload.priority, payload.title)
    if kind == "rejected":
        raise HTTPException(status_code=400, detail={"code": "url_rejected", "message": rejected["message"]})
    return {"result": kind, "document": document}


@router.post("/projects/{project_id}/documents/import", dependencies=[Depends(require_token)])
def import_documents(project_id: str, payload: ImportTextIn, db: Session = Depends(get_db)):
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Projeto não encontrado."})
    if len(payload.text.encode()) > 2_000_000:
        raise HTTPException(status_code=400, detail={"code": "too_large", "message": "A lista excede o limite."})
    added, duplicates, rejected = [], [], []
    seen: set[str] = set()
    for raw in _parse_urls(payload.text):
        try:
            normalized = normalize_url(raw)
        except UrlRejected:
            normalized = raw.strip()
        if normalized in seen:
            duplicates.append({"url": raw, "message": "Repetido na própria lista."})
            continue
        seen.add(normalized)
        kind, document, problem = _add_url(db, project, raw, 0, "")
        if kind == "added":
            added.append(document)
        elif kind == "duplicate":
            duplicates.append({"url": raw, "id": document["id"]})
        else:
            rejected.append(problem)
    audit(db, "import", "Lista de endereços importada.", {"added": len(added), "duplicates": len(duplicates), "rejected": len(rejected)})
    return {"added": added, "duplicates": duplicates, "rejected": rejected}


@router.post("/projects/{project_id}/documents/file", dependencies=[Depends(require_token)])
async def import_file(project_id: str, request: Request, file: UploadFile = File(...), db: Session = Depends(get_db)):
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Projeto não encontrado."})
    data = await file.read()
    max_bytes = int(preference_value(db, "max_download_mb") or 80) * 1024 * 1024
    try:
        suffix = validate_import_bytes(file.filename or "arquivo", data, max_bytes=max_bytes)
    except AppError as exc:
        raise_app(exc)
    if suffix in {".txt", ".csv"}:
        return import_documents(project_id, ImportTextIn(text=data.decode("utf-8", errors="replace"), filename=file.filename or "lista.txt"), db)
    item = Document(
        id=str(uuid.uuid4()),
        project_id=project.id,
        origin="file",
        url="",
        normalized_url="",
        title=Path(file.filename or "documento").stem,
        domain="",
        source_kind="pdf" if suffix == ".pdf" else "image",
        state="draft",
        priority=0,
        added_at=utcnow(),
    )
    db.add(item)
    db.flush()
    from cpmh_backend.paths import document_dir

    folder = document_dir(get_settings(), project.id, item.id)
    destination = folder / "original" / safe_filename(file.filename or f"documento{suffix}")
    destination.write_bytes(data)
    item.local_path = str(destination)
    item.content_sha256 = __import__("hashlib").sha256(data).hexdigest()
    audit(db, "import", "Arquivo local importado.", {"id": item.id, "suffix": suffix})
    return document_out(item, db)


@router.get("/projects/{project_id}/documents", dependencies=[Depends(require_token)])
def list_documents(project_id: str, q: str = "", state: str = "", db: Session = Depends(get_db)):
    statement = select(Document).where(Document.project_id == project_id).order_by(Document.priority.desc(), Document.added_at.desc())
    if state:
        statement = statement.where(Document.state == state)
    if q:
        statement = statement.where(or_(Document.title.contains(q), Document.url.contains(q)))
    return [document_out(item, db) for item in db.scalars(statement).all()]


@router.get("/documents/recent", dependencies=[Depends(require_token)])
def recent_documents(db: Session = Depends(get_db)):
    rows = db.scalars(select(Document).order_by(Document.added_at.desc()).limit(8)).all()
    return [document_out(item, db) for item in rows]


@router.get("/documents/{document_id}", dependencies=[Depends(require_token)])
def get_document(document_id: str, db: Session = Depends(get_db)):
    item = db.get(Document, document_id)
    if item is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Documento não encontrado."})
    return document_out(item, db)


@router.patch("/documents/{document_id}", dependencies=[Depends(require_token)])
def patch_document(document_id: str, payload: DocumentPatch, db: Session = Depends(get_db)):
    item = db.get(Document, document_id)
    if item is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Documento não encontrado."})
    if item.state in ACTIVE_STATES - {"paused", "queued"}:
        raise HTTPException(status_code=409, detail={"code": "busy", "message": "O documento está em processamento."})
    if payload.priority is not None:
        item.priority = max(0, min(payload.priority, 100))
    if payload.title is not None:
        item.title = payload.title.strip()
    if payload.url is not None:
        pages = db.scalar(select(func.count()).select_from(DocumentPage).where(DocumentPage.document_id == item.id)) or 0
        if pages and not payload.confirm_reset:
            raise HTTPException(
                status_code=409,
                detail={"code": "url_change_resets_capture", "message": "Alterar a URL descarta as páginas já capturadas deste documento."},
            )
        try:
            checked = validate_url(payload.url, allow_local=_network_allowed(db))
        except UrlRejected as exc:
            raise_app(exc)
        item.url = payload.url.strip()
        item.normalized_url = checked.url
        item.domain = domain_of(checked.url)
        item.origin = "url"
        item.local_path = ""
        item.source_kind = "unknown"
        item.state = "draft"
        item.capture_status = ""
        if pages:
            from cpmh_backend.services.pipeline import _clear_working_files
            from cpmh_backend.paths import document_dir

            _clear_working_files(db, item, document_dir(get_settings(), item.project_id, item.id))
    return document_out(item, db)


@router.delete("/documents/{document_id}", dependencies=[Depends(require_token)])
def delete_document(document_id: str, db: Session = Depends(get_db)):
    item = db.get(Document, document_id)
    if item is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Documento não encontrado."})
    from cpmh_backend.paths import document_dir
    import shutil

    folder = document_dir(get_settings(), item.project_id, item.id)
    try:
        with db.begin_nested():
            from cpmh_backend.knowledge.index import purge_document

            purge_document(db, document_id)
    except Exception:
        logging.getLogger("cpmh").exception("Falha ao remover o documento da biblioteca de conhecimento")
    db.delete(item)
    if folder.exists():
        shutil.rmtree(folder, ignore_errors=True)
    return {"deleted": document_id}


@router.get("/dashboard", dependencies=[Depends(require_token)])
def dashboard(db: Session = Depends(get_db)):
    documents = db.scalars(select(Document)).all()
    def count(predicate):
        return sum(1 for item in documents if predicate(item))
    in_progress = {"queued", "validating", "capturing", "processing", "ocr", "structuring", "extracting_images", "translating", "reconstructing", "exporting", "paused"}
    jobs = db.scalars(select(ProcessingJob).where(ProcessingJob.state.in_(list(ACTIVE_STATES))).order_by(ProcessingJob.priority.desc())).all()
    recent = db.scalars(select(Document).order_by(Document.added_at.desc()).limit(6)).all()
    return {
        "documents_total": len(documents),
        "completed": count(lambda item: item.state == "completed"),
        "in_progress": count(lambda item: item.state in in_progress),
        "awaiting_review": count(lambda item: item.state == "awaiting_review"),
        "failed": count(lambda item: item.state == "failed"),
        "inconclusive": count(lambda item: item.state == "inconclusive"),
        "queue": [job_out(item) for item in jobs],
        "recent": [document_out(item, db) for item in recent],
    }


@router.post("/documents/{document_id}/jobs", dependencies=[Depends(require_token)])
def create_job(document_id: str, payload: JobIn, request: Request, db: Session = Depends(get_db)):
    item = db.get(Document, document_id)
    if item is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Documento não encontrado."})
    if payload.external_translation and not payload.external_consent:
        raise HTTPException(status_code=403, detail={"code": "consent_required", "message": "A tradução externa exige consentimento explícito."})
    from cpmh_backend.translation_modes import normalize_translation_mode

    try:
        mode = normalize_translation_mode(payload.translate_mode)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "translate_mode", "message": "Modo de tradução desconhecido."}) from exc
    selected = list(dict.fromkeys(payload.selected_region_ids))
    if mode == "selected_regions":
        if not selected:
            raise HTTPException(status_code=400, detail={"code": "selection_empty", "message": "Selecione ao menos uma região."})
        rows = db.scalars(select(OCRRegion).where(OCRRegion.id.in_(selected))).all()
        found = {row.id: row for row in rows}
        for region_id in selected:
            row = found.get(region_id)
            if row is None or row.document_id != item.id or row.deleted:
                raise HTTPException(
                    status_code=400,
                    detail={"code": "region_not_in_document", "message": "Uma região selecionada não pertence a este documento."},
                )
    if payload.glossary_id:
        if db.get(Glossary, payload.glossary_id) is None:
            raise HTTPException(status_code=400, detail={"code": "glossary", "message": "Glossário não encontrado."})
    options = payload.model_dump()
    options["translate_mode"] = mode
    options["selected_region_ids"] = selected
    job = ProcessingJob(
        id=str(uuid.uuid4()),
        document_id=item.id,
        priority=item.priority if payload.priority is None else payload.priority,
        state="queued",
        stage="queued",
        progress=0,
        attempts=0,
        checkpoint={},
        options=options,
        created_at=utcnow(),
    )
    item.state = "queued"
    db.add(job)
    db.flush()
    audit(db, "job", "Tarefa enfileirada.", {"job_id": job.id, "document_id": item.id})
    db.commit()
    _notify(request)
    return job_out(job)


@router.get("/jobs", dependencies=[Depends(require_token)])
def list_jobs(db: Session = Depends(get_db)):
    rows = db.scalars(select(ProcessingJob).order_by(ProcessingJob.priority.desc(), ProcessingJob.created_at.asc())).all()
    return [job_out(item) for item in rows]


@router.get("/jobs/{job_id}", dependencies=[Depends(require_token)])
def get_job(job_id: str, db: Session = Depends(get_db)):
    item = db.get(ProcessingJob, job_id)
    if item is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Tarefa não encontrada."})
    return job_out(item)


@router.post("/jobs/{job_id}/pause", dependencies=[Depends(require_token)])
def pause_job(job_id: str, db: Session = Depends(get_db)):
    item = _job(db, job_id)
    item.state = "paused"
    document = db.get(Document, item.document_id)
    if document is not None:
        document.state = "paused"
    return job_out(item)


@router.get("/jobs/{job_id}/access", dependencies=[Depends(require_token)])
def access_history(job_id: str, db: Session = Depends(get_db)):
    item = _job(db, job_id)
    from cpmh_backend.access_flow import resume_reason
    from cpmh_backend.models import AccessEvent

    rows = db.scalars(select(AccessEvent).where(AccessEvent.job_id == item.id).order_by(AccessEvent.created_at)).all()
    access = (item.checkpoint or {}).get("access") or {}
    return {
        "access": access,
        "resumable": resume_reason(item.checkpoint) is None,
        "reason": resume_reason(item.checkpoint) or "",
        "events": [
            {
                "id": row.id,
                "state": row.state,
                "provider": row.provider,
                "confidence": row.confidence,
                "url": row.url,
                "evidence": row.evidence or [],
                "created_at": _dt(row.created_at),
            }
            for row in rows
        ],
    }


@router.post("/jobs/{job_id}/access/recheck", dependencies=[Depends(require_token)])
def recheck_access(job_id: str, db: Session = Depends(get_db)):
    item = _job(db, job_id)
    document = db.get(Document, item.document_id)
    if document is None or not (document.normalized_url or document.url):
        raise HTTPException(status_code=400, detail={"code": "url", "message": "Esta tarefa não tem URL para checar."})
    from cpmh_backend.access_flow import remember, resume_reason
    from cpmh_backend.services.capture import probe_html

    timeout = float(preference_value(db, "timeout_seconds") or 30)
    verdict = probe_html(document.normalized_url or document.url, allow_local=_network_allowed(db), timeout=timeout)
    remember(db, item, document, verdict, source="recheck")
    audit(db, "access", verdict.get("message", "")[:500], {"job_id": item.id, "state": verdict.get("state"), "provider": verdict.get("provider")})
    return {"access": (item.checkpoint or {}).get("access") or {}, "resumable": resume_reason(item.checkpoint) is None}


@router.post("/jobs/{job_id}/access/observation", dependencies=[Depends(require_token)])
def observe_access(job_id: str, payload: AccessObservation, db: Session = Depends(get_db)):
    item = _job(db, job_id)
    document = db.get(Document, item.document_id)
    if document is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Documento não encontrado."})
    from cpmh_backend.access import classify
    from cpmh_backend.access_flow import remember

    verdict = classify(
        {
            "url": payload.url[:500],
            "final_url": payload.final_url[:500],
            "status": payload.status,
            "title": payload.title[:300],
            "text": payload.text[:1500],
            "markers": payload.markers[:20],
            "iframes": payload.iframes[:20],
            "scripts": payload.scripts[:30],
        }
    )
    remember(db, item, document, verdict, source="browser")
    return {"access": (item.checkpoint or {}).get("access") or {}, "observed": verdict["state"]}


@router.post("/jobs/{job_id}/access/close", dependencies=[Depends(require_token)])
def close_access_session(job_id: str, db: Session = Depends(get_db)):
    item = _job(db, job_id)
    checkpoint = dict(item.checkpoint or {})
    access = dict(checkpoint.get("access") or {})
    access["session_closed"] = True
    access["cleared"] = False
    access["cleared_at"] = ""
    checkpoint["access"] = access
    item.checkpoint = checkpoint
    audit(db, "access", "Sessão de verificação encerrada.", {"job_id": item.id, "partition": access.get("partition") or ""})
    return {"partition": access.get("partition") or "", "closed": True}


@router.post("/jobs/{job_id}/access/alternative", dependencies=[Depends(require_token)])
def use_public_alternative(job_id: str, db: Session = Depends(get_db)):
    item = _job(db, job_id)
    document = db.get(Document, item.document_id)
    access = dict((item.checkpoint or {}).get("access") or {})
    alternative = access.get("alternative") or {}
    target = str(alternative.get("url") or "")
    if document is None or alternative.get("kind") != "public_pdf" or not target:
        raise HTTPException(status_code=409, detail={"code": "no_alternative", "message": "Não há um PDF público indicado pela própria página."})
    from cpmh_backend.access_flow import remember
    from cpmh_backend.errors import AccessPaused
    from cpmh_backend.hashing import sha256_bytes
    from cpmh_backend.paths import document_dir
    from cpmh_backend.recovery import managed_fetch, timeout_for
    from urllib.parse import urlsplit

    settings = get_settings()
    host = urlsplit(target).hostname or ""
    configured = preference_value(db, "domain_timeouts") or {}
    timeout = timeout_for(host, float(preference_value(db, "timeout_seconds") or 30), configured if isinstance(configured, dict) else {})
    limit = int(preference_value(db, "domain_concurrency") or 2)
    max_bytes = int(preference_value(db, "max_download_mb") or 80) * 1024 * 1024
    try:
        result, _cached = managed_fetch(
            target,
            allow_local=_network_allowed(db),
            max_bytes=max_bytes,
            timeout=timeout,
            domain_limit=limit,
        )
    except AccessPaused as exc:
        remember(db, item, document, exc.verdict, source="alternative")
        raise HTTPException(status_code=409, detail={"code": "access_blocked", "message": exc.verdict.get("message")}) from exc
    if result.kind != "pdf":
        raise HTTPException(status_code=409, detail={"code": "not_pdf", "message": "O endereço público não devolveu um PDF. Nada foi extraído."})
    folder = document_dir(settings, document.project_id, document.id)
    destination = folder / "original" / "source.pdf"
    destination.write_bytes(result.data)
    document.local_path = str(destination)
    document.source_kind = "pdf"
    document.content_sha256 = sha256_bytes(result.data)
    document.error_message = ""
    verdict = {
        "state": "ACCESS_GRANTED",
        "provider": "none",
        "confidence": 0.9,
        "url": target,
        "final_url": result.final_url,
        "evidence": ["PDF público indicado pela própria página"],
        "message": "O PDF público indicado pela página foi salvo. A retomada usa esse arquivo e não volta ao endereço bloqueado.",
        "http_status": 200,
        "alternative": alternative,
    }
    remember(db, item, document, verdict, source="recheck")
    audit(db, "access", "PDF público indicado pela página foi salvo.", {"job_id": item.id, "domain": host})
    return {"access": (item.checkpoint or {}).get("access") or {}, "source_kind": document.source_kind}


@router.post("/jobs/{job_id}/resume", dependencies=[Depends(require_token)])
def resume_job(job_id: str, request: Request, db: Session = Depends(get_db)):
    item = _job(db, job_id)
    from cpmh_backend.access_flow import resume_reason

    reason = resume_reason(item.checkpoint)
    if reason:
        if "expirou" in reason:
            checkpoint = dict(item.checkpoint or {})
            access = dict(checkpoint.get("access") or {})
            access["cleared"] = False
            access["cleared_at"] = ""
            access["message"] = reason
            checkpoint["access"] = access
            item.checkpoint = checkpoint
        raise HTTPException(status_code=409, detail={"code": "access_blocked", "message": reason})
    item.state = "queued"
    document = db.get(Document, item.document_id)
    if document is not None:
        document.state = "queued"
    db.commit()
    _notify(request)
    return job_out(item)


@router.post("/jobs/{job_id}/cancel", dependencies=[Depends(require_token)])
def cancel_job(job_id: str, db: Session = Depends(get_db)):
    item = _job(db, job_id)
    item.state = "cancelled"
    item.finished_at = utcnow()
    document = db.get(Document, item.document_id)
    if document is not None:
        document.state = "cancelled"
    return job_out(item)


@router.post("/jobs/{job_id}/retry", dependencies=[Depends(require_token)])
def retry_job(job_id: str, request: Request, db: Session = Depends(get_db)):
    item = _job(db, job_id)
    item.state = "queued"
    item.error = ""
    item.finished_at = None
    options = dict(item.options or {})
    options["force_recapture"] = False
    item.options = options
    document = db.get(Document, item.document_id)
    if document is not None:
        document.state = "queued"
        document.error_message = ""
    db.commit()
    _notify(request)
    return job_out(item)


@router.post("/jobs/reorder", dependencies=[Depends(require_token)])
def reorder_jobs(payload: ReorderIn, db: Session = Depends(get_db)):
    for index, job_id in enumerate(payload.ids):
        item = db.get(ProcessingJob, job_id)
        if item is not None:
            item.priority = len(payload.ids) - index
    return {"updated": len(payload.ids)}


def _job(db: Session, job_id: str) -> ProcessingJob:
    item = db.get(ProcessingJob, job_id)
    if item is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Tarefa não encontrada."})
    return item


@router.get("/documents/{document_id}/pages", dependencies=[Depends(require_token)])
def list_pages(document_id: str, db: Session = Depends(get_db)):
    rows = db.scalars(select(DocumentPage).where(DocumentPage.document_id == document_id).order_by(DocumentPage.sequence)).all()
    return [
        {
            "id": item.id,
            "sequence": item.sequence,
            "reported_number": item.reported_number,
            "width": item.width,
            "height": item.height,
            "sha256": item.sha256,
            "phash": item.phash,
            "state": item.state,
            "blank": item.blank,
            "partial": item.partial,
            "captured_at": _dt(item.captured_at),
            "source_url": item.source_url,
        }
        for item in rows
    ]


@router.get("/pages/{page_id}/image", dependencies=[Depends(require_token)])
def page_image(page_id: str, db: Session = Depends(get_db)):
    item = db.get(DocumentPage, page_id)
    if item is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Página não encontrada."})
    path = _inside_data(item.image_path)
    return FileResponse(path)


@router.get("/pages/{page_id}/regions", dependencies=[Depends(require_token)])
def list_regions(page_id: str, db: Session = Depends(get_db)):
    rows = db.scalars(select(OCRRegion).where(OCRRegion.page_id == page_id, OCRRegion.deleted.is_(False)).order_by(OCRRegion.y, OCRRegion.x)).all()
    return [region_out(item) for item in rows]


@router.post("/pages/{page_id}/regions", dependencies=[Depends(require_token)])
def add_region(page_id: str, payload: RegionIn, db: Session = Depends(get_db)):
    page = db.get(DocumentPage, page_id)
    if page is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Página não encontrada."})
    if payload.category not in CATEGORIES:
        raise HTTPException(status_code=400, detail={"code": "category", "message": "Classificação desconhecida."})
    x, y, w, h = clamp_bbox(payload.x, payload.y, payload.w, payload.h)
    item = OCRRegion(
        id=str(uuid.uuid4()),
        page_id=page.id,
        document_id=page.document_id,
        category=payload.category,
        text=payload.text,
        confidence=100,
        x=x,
        y=y,
        w=w,
        h=h,
        language="",
        review_state="reviewed",
        original_text=payload.text,
        original_category=payload.category,
        original_x=x,
        original_y=y,
        original_w=w,
        original_h=h,
        source="manual",
        deleted=False,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    db.add(item)
    db.flush()
    _sync_region(db, item, "create", {"text": "", "category": "", "bbox": []}, origin="user")
    return region_out(item)


@router.patch("/regions/{region_id}", dependencies=[Depends(require_token)])
def patch_region(region_id: str, payload: RegionPatch, db: Session = Depends(get_db)):
    item = db.get(OCRRegion, region_id)
    if item is None or item.deleted:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Região não encontrada."})
    from cpmh_backend.services.representation import snapshot_region

    before = snapshot_region(item)
    text_changed = payload.text is not None and payload.text != item.text
    category_changed = payload.category is not None and payload.category != item.category
    bbox_changed = None not in {payload.x, payload.y, payload.w, payload.h} and [payload.x, payload.y, payload.w, payload.h] != before["bbox"]
    if payload.category is not None:
        if payload.category not in CATEGORIES:
            raise HTTPException(status_code=400, detail={"code": "category", "message": "Classificação desconhecida."})
        item.category = payload.category
    if payload.text is not None:
        item.text = payload.text
    if None not in {payload.x, payload.y, payload.w, payload.h}:
        item.x, item.y, item.w, item.h = clamp_bbox(payload.x, payload.y, payload.w, payload.h)
    if payload.review_state is not None:
        item.review_state = payload.review_state
    elif text_changed or category_changed or bbox_changed:
        item.review_state = "edited"
    changes = [name for name, flag in (("edit_text", text_changed), ("reclassify", category_changed), ("move", bbox_changed)) if flag]
    if payload.review_state == "reviewed" and not changes:
        operation = "mark_reviewed"
    elif len(changes) == 1:
        operation = changes[0]
    elif changes:
        operation = "edit"
    else:
        operation = "mark_reviewed"
    item.updated_at = utcnow()
    _sync_region(db, item, operation, before)
    return region_out(item)


@router.delete("/regions/{region_id}", dependencies=[Depends(require_token)])
def delete_region(region_id: str, db: Session = Depends(get_db)):
    item = db.get(OCRRegion, region_id)
    if item is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Região não encontrada."})
    from cpmh_backend.services.representation import snapshot_region

    before = snapshot_region(item)
    item.deleted = True
    item.review_state = "edited"
    item.updated_at = utcnow()
    _sync_region(db, item, "delete", before)
    return {"deleted": True}


@router.post("/regions/{region_id}/restore", dependencies=[Depends(require_token)])
def restore_region(region_id: str, db: Session = Depends(get_db)):
    item = db.get(OCRRegion, region_id)
    if item is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Região não encontrada."})
    from cpmh_backend.services.representation import snapshot_region

    before = snapshot_region(item)
    item.text = item.original_text
    item.category = item.original_category
    item.x, item.y, item.w, item.h = item.original_x, item.original_y, item.original_w, item.original_h
    item.deleted = False
    item.review_state = "pending"
    item.source = "restored"
    item.updated_at = utcnow()
    _sync_region(db, item, "restore", before, origin="restore")
    return region_out(item)


@router.post("/regions/{region_id}/reprocess", dependencies=[Depends(require_token)])
def reprocess_region(region_id: str, db: Session = Depends(get_db)):
    item = db.get(OCRRegion, region_id)
    if item is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Região não encontrada."})
    page = db.get(DocumentPage, item.page_id)
    if page is None or not page.image_path:
        raise HTTPException(status_code=400, detail={"code": "no_image", "message": "A página não tem imagem para reprocessar."})
    from PIL import Image

    image = Image.open(_inside_data(page.image_path))
    crop = crop_normalized(image, (item.original_x, item.original_y, item.original_w, item.original_h))
    if crop is None:
        raise HTTPException(status_code=400, detail={"code": "bbox", "message": "A região original não recorta a imagem."})
    languages = preference_value(db, "ocr_languages") or ["por", "eng"]
    blocks, _prepared, _notes = recognize(crop, languages)
    if not blocks:
        raise HTTPException(status_code=422, detail={"code": "ocr_empty", "message": "O OCR não leu texto nessa região."})
    from cpmh_backend.services.representation import snapshot_region

    before = snapshot_region(item)
    item.text = " ".join(block.text for block in blocks)
    item.confidence = round(sum(block.confidence for block in blocks) / len(blocks), 2)
    item.review_state = "edited"
    item.source = "reprocessed"
    item.updated_at = utcnow()
    _sync_region(db, item, "reprocess", before, origin="reprocess")
    return region_out(item)


@router.get("/documents/{document_id}/elements", dependencies=[Depends(require_token)])
def list_elements(document_id: str, db: Session = Depends(get_db)):
    rows = db.scalars(select(DocumentElement).where(DocumentElement.document_id == document_id).order_by(DocumentElement.order_index)).all()
    return [
        {
            "id": item.id,
            "kind": item.kind,
            "order": item.order_index,
            "text": item.text,
            "confidence": item.confidence,
            "level": item.level,
            "page_ids": item.page_ids,
            "region_ids": item.region_ids,
            "continued_from": item.continued_from,
            "continued_in": item.continued_in,
            "skip_export": item.skip_export,
        }
        for item in rows
    ]


@router.get("/documents/{document_id}/images", dependencies=[Depends(require_token)])
def list_images(document_id: str, db: Session = Depends(get_db)):
    rows = db.scalars(select(ImageAsset).where(ImageAsset.document_id == document_id)).all()
    return [
        {
            "id": item.id,
            "name": item.name,
            "category": item.category,
            "caption": item.caption,
            "page_id": item.page_id,
            "bbox": [item.x, item.y, item.w, item.h],
            "sha256": item.sha256,
            "width": item.width,
            "height": item.height,
            "confidence": item.confidence,
            "format": item.format,
            "review_state": item.review_state,
            "page_sequence": db.get(DocumentPage, item.page_id).sequence if item.page_id and db.get(DocumentPage, item.page_id) else None,
        }
        for item in rows
    ]


@router.get("/images/{image_id}/file", dependencies=[Depends(require_token)])
def image_file(image_id: str, db: Session = Depends(get_db)):
    item = db.get(ImageAsset, image_id)
    if item is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Imagem não encontrada."})
    return FileResponse(_inside_data(item.path))


@router.patch("/images/{image_id}", dependencies=[Depends(require_token)])
def patch_image(image_id: str, payload: ImagePatch, db: Session = Depends(get_db)):
    item = db.get(ImageAsset, image_id)
    if item is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Imagem não encontrada."})
    changed = False
    if payload.name is not None:
        item.name = safe_filename(payload.name)
        changed = True
    if payload.category is not None:
        item.category = payload.category
        changed = True
    if payload.caption is not None:
        item.caption = payload.caption
        changed = True
    if payload.review_state is not None:
        item.review_state = payload.review_state
    elif changed:
        item.review_state = "reviewed"
    return {
        "id": item.id,
        "name": item.name,
        "category": item.category,
        "caption": item.caption,
        "review_state": item.review_state,
    }


@router.delete("/images/{image_id}", dependencies=[Depends(require_token)])
def delete_image(image_id: str, confirm: bool = False, db: Session = Depends(get_db)):
    item = db.get(ImageAsset, image_id)
    if item is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Imagem não encontrada."})
    if not confirm:
        raise HTTPException(status_code=409, detail={"code": "confirm_required", "message": "Confirme a exclusão da imagem."})
    path = item.path
    referenced = 0
    if path:
        referenced += db.scalar(select(func.count()).select_from(ImageAsset).where(ImageAsset.path == path, ImageAsset.id != item.id)) or 0
        referenced += db.scalar(select(func.count()).select_from(FormulaRecord).where(FormulaRecord.image_path == path)) or 0
        referenced += db.scalar(select(func.count()).select_from(TableRecord).where(TableRecord.image_path == path)) or 0
    removed_file = False
    db.delete(item)
    db.flush()
    if path and referenced == 0:
        file_path = Path(path)
        if file_path.exists():
            file_path.unlink()
            removed_file = True
    return {"deleted": True, "file_removed": removed_file}


@router.post("/documents/{document_id}/images/export", dependencies=[Depends(require_token)])
def export_images(document_id: str, payload: ImageExportIn, db: Session = Depends(get_db)):
    import shutil

    from cpmh_backend.security import prepare_output_dir
    from cpmh_backend.services.exporting import resolve_output_path

    document = db.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Documento não encontrado."})
    try:
        destination = prepare_output_dir(payload.output_dir, install_dir=get_settings().install_dir)
    except AppError as exc:
        raise HTTPException(status_code=400, detail={"code": exc.code, "message": exc.message}) from exc
    rows = db.scalars(select(ImageAsset).where(ImageAsset.document_id == document_id)).all()
    if payload.ids:
        wanted = set(payload.ids)
        rows = [row for row in rows if row.id in wanted]
        if len(rows) != len(wanted):
            raise HTTPException(status_code=400, detail={"code": "image_not_in_document", "message": "Uma imagem não pertence a este documento."})
    copied = []
    try:
        for image in rows:
            source = Path(image.path)
            if not source.exists():
                continue
            target = resolve_output_path(destination, image.name or f"{image.id}.{image.format or 'png'}", payload.collision)
            shutil.copy2(source, target)
            copied.append({"id": image.id, "path": str(target), "name": target.name})
    except AppError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.message}) from exc
    return {"files": copied}


@router.get("/documents/{document_id}/revisions", dependencies=[Depends(require_token)])
def list_revisions(document_id: str, db: Session = Depends(get_db)):
    rows = db.scalars(select(RegionRevision).where(RegionRevision.document_id == document_id).order_by(RegionRevision.created_at)).all()
    return [
        {
            "id": item.id,
            "region_id": item.region_id,
            "operation": item.operation,
            "origin": item.origin,
            "original_text": item.original_text,
            "revised_text": item.revised_text,
            "original_category": item.original_category,
            "revised_category": item.revised_category,
            "original_bbox": item.original_bbox,
            "revised_bbox": item.revised_bbox,
            "created_at": _dt(item.created_at),
        }
        for item in rows
    ]


@router.get("/documents/{document_id}/translations", dependencies=[Depends(require_token)])
def list_translations(document_id: str, db: Session = Depends(get_db)):
    from cpmh_backend.translation_modes import translation_state

    rows = db.scalars(select(TranslationRecord).where(TranslationRecord.document_id == document_id)).all()
    return [
        {
            "id": item.id,
            "element_id": item.element_id,
            "mode": item.mode,
            "provider": item.provider,
            "partial": item.partial,
            "state": translation_state(provider=item.provider, partial=item.partial),
            "source_text": item.source_text,
            "translated_text": item.translated_text,
            "glossary_id": item.glossary_id,
        }
        for item in rows
    ]


@router.get("/translation/runtime", dependencies=[Depends(require_token)])
def translation_runtime_route():
    from cpmh_backend.services.translate import translation_runtime

    return translation_runtime()


@router.get("/documents/{document_id}/tables", dependencies=[Depends(require_token)])
def list_tables(document_id: str, db: Session = Depends(get_db)):
    rows = db.scalars(select(TableRecord).where(TableRecord.document_id == document_id)).all()
    return [
        {
            "id": item.id,
            "rows": item.rows,
            "confidence": item.confidence,
            "reliable": item.reliable,
            "notes": item.notes,
            "review_state": item.review_state,
            "page_sequence": item.page_sequence,
            "bbox": [item.x, item.y, item.w, item.h],
        }
        for item in rows
    ]


@router.post("/tables/{table_id}/review", dependencies=[Depends(require_token)])
def review_table(table_id: str, db: Session = Depends(get_db)):
    item = db.get(TableRecord, table_id)
    if item is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Tabela não encontrada."})
    item.review_state = "reviewed"
    item.reliable = bool(item.rows)
    return {"id": item.id, "reliable": item.reliable, "review_state": item.review_state}


@router.get("/documents/{document_id}/formulas", dependencies=[Depends(require_token)])
def list_formulas(document_id: str, db: Session = Depends(get_db)):
    rows = db.scalars(select(FormulaRecord).where(FormulaRecord.document_id == document_id)).all()
    return [
        {
            "id": item.id,
            "text": item.text,
            "latex": item.latex,
            "reliable": item.reliable,
            "confidence": item.confidence,
            "notes": item.notes,
            "page_id": item.page_id,
        }
        for item in rows
    ]


@router.post("/documents/{document_id}/export", dependencies=[Depends(require_token)])
def export_route(document_id: str, payload: ExportIn, db: Session = Depends(get_db)):
    item = db.get(Document, document_id)
    if item is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Documento não encontrado."})
    from cpmh_backend.services.exporting import export_document

    try:
        files = export_document(
            db,
            item,
            get_settings(),
            formats=payload.formats,
            mode=payload.mode,
            output_name=payload.output_name,
            output_dir=payload.output_dir,
            collision=payload.collision,
            translate_mode=payload.translate_mode,
        )
    except AppError as exc:
        raise_app(exc)
    audit(db, "export", "Documento exportado.", {"id": item.id, "formats": payload.formats})
    return {"files": files}


@router.get("/documents/{document_id}/exports", dependencies=[Depends(require_token)])
def list_exports(document_id: str, db: Session = Depends(get_db)):
    rows = db.scalars(select(ExportedFile).where(ExportedFile.document_id == document_id).order_by(ExportedFile.created_at.desc())).all()
    return [
        {"id": item.id, "format": item.format, "path": item.path, "name": item.name, "size": item.size, "mode": item.mode, "created_at": _dt(item.created_at)}
        for item in rows
    ]


@router.get("/glossaries", dependencies=[Depends(require_token)])
def list_glossaries(db: Session = Depends(get_db)):
    rows = db.scalars(select(Glossary).order_by(Glossary.created_at)).all()
    return [{"id": item.id, "name": item.name, "description": item.description, "project_id": item.project_id} for item in rows]


@router.post("/glossaries", dependencies=[Depends(require_token)])
def create_glossary(payload: GlossaryIn, db: Session = Depends(get_db)):
    item = Glossary(id=str(uuid.uuid4()), name=payload.name.strip(), description=payload.description, project_id=payload.project_id, created_at=utcnow())
    db.add(item)
    db.flush()
    return {"id": item.id, "name": item.name, "description": item.description}


@router.get("/glossaries/{glossary_id}/terms", dependencies=[Depends(require_token)])
def list_terms(glossary_id: str, db: Session = Depends(get_db)):
    rows = db.scalars(select(GlossaryTerm).where(GlossaryTerm.glossary_id == glossary_id)).all()
    return [
        {"id": item.id, "source": item.source, "target": item.target, "context": item.context, "do_not_translate": item.do_not_translate}
        for item in rows
    ]


@router.post("/glossaries/{glossary_id}/terms", dependencies=[Depends(require_token)])
def add_term(glossary_id: str, payload: TermIn, db: Session = Depends(get_db)):
    if db.get(Glossary, glossary_id) is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Glossário não encontrado."})
    item = GlossaryTerm(
        id=str(uuid.uuid4()),
        glossary_id=glossary_id,
        source=payload.source.strip(),
        target=payload.target.strip(),
        context=payload.context.strip(),
        do_not_translate=payload.do_not_translate,
        created_at=utcnow(),
    )
    db.add(item)
    db.flush()
    return {"id": item.id, "source": item.source, "target": item.target, "do_not_translate": item.do_not_translate}


@router.delete("/terms/{term_id}", dependencies=[Depends(require_token)])
def delete_term(term_id: str, db: Session = Depends(get_db)):
    item = db.get(GlossaryTerm, term_id)
    if item is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Termo não encontrado."})
    db.delete(item)
    return {"deleted": term_id}


@router.post("/glossaries/{glossary_id}/import", dependencies=[Depends(require_token)])
async def import_glossary(glossary_id: str, file: UploadFile = File(...), db: Session = Depends(get_db)):
    content = (await file.read()).decode("utf-8", errors="replace")
    try:
        count = import_terms(db, glossary_id, content)
    except AppError as exc:
        raise_app(exc)
    return {"imported": count}


@router.get("/glossaries/{glossary_id}/export", dependencies=[Depends(require_token)])
def export_glossary(glossary_id: str, db: Session = Depends(get_db)):
    try:
        content = export_terms_csv(db, glossary_id)
    except AppError as exc:
        raise_app(exc)
    return PlainTextResponse(content, media_type="text/csv")


@router.get("/logs", dependencies=[Depends(require_token)])
def list_logs(db: Session = Depends(get_db)):
    rows = db.scalars(select(LogEntry).order_by(LogEntry.created_at.desc()).limit(200)).all()
    return [
        {"id": item.id, "level": item.level, "category": item.category, "message": item.message, "created_at": _dt(item.created_at)}
        for item in rows
    ]


@router.post("/logs/report", dependencies=[Depends(require_token)])
def log_report(redact_document_text: bool = True, db: Session = Depends(get_db)):
    payload = summary(db, get_settings())
    payload["logs"] = [
        {"level": item.level, "category": item.category, "message": item.message, "created_at": _dt(item.created_at)}
        for item in db.scalars(select(LogEntry).order_by(LogEntry.created_at.desc()).limit(100)).all()
    ]
    if redact_document_text:
        payload["note"] = "O relatório não inclui o texto dos documentos."
    return payload


def _inside_data(path: str) -> Path:
    resolved = Path(path).resolve()
    root = get_settings().data_dir.resolve()
    if resolved != root and root not in resolved.parents:
        raise HTTPException(status_code=403, detail={"code": "path", "message": "Arquivo fora da área de dados."})
    if not resolved.is_file():
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Arquivo não encontrado."})
    return resolved


_ = json
