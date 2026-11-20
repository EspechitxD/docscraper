from __future__ import annotations

import logging
import shutil
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image
from sqlalchemy import delete, select

from cpmh_backend.config import get_settings
from cpmh_backend.db import preference_value, session_scope
from cpmh_backend.errors import AppError, CollisionError, UrlRejected
from cpmh_backend.hashing import dhash, sha256_bytes, sha256_file
from cpmh_backend.intelligence import Block, FlowPiece, classify_blocks, detect_language, link_page_continuity, reading_order
from cpmh_backend.models import (
    Capture,
    Document,
    DocumentElement,
    DocumentPage,
    FormulaRecord,
    GlossaryTerm,
    ImageAsset,
    OCRRegion,
    ProcessingJob,
    ProcessingStep,
    TableRecord,
    TranslationRecord,
    utcnow,
)
from cpmh_backend.paths import document_dir
from cpmh_backend.services.exporting import export_document
from cpmh_backend.services.fetch import fetch_url
from cpmh_backend.services.ocr import recognize
from cpmh_backend.services.pdf_analysis import analyze_pdf
from cpmh_backend.services.translate import translate_text

logger = logging.getLogger("cpmh")
_claim_lock = threading.Lock()
TERMINAL_JOB_STATES = {"paused", "cancelled", "completed", "failed"}


def new_id() -> str:
    return str(uuid.uuid4())


def run_job(job_id: str) -> None:
    settings = get_settings()
    with session_scope() as session:
        job = session.get(ProcessingJob, job_id)
        if job is None or job.state in {"cancelled", "completed", "paused"}:
            return
        document = session.get(Document, job.document_id)
        if document is None:
            job.state = "failed"
            job.error = "Documento não encontrado."
            return
        job.attempts = (job.attempts or 0) + 1
        job.started_at = job.started_at or utcnow()
        job.error = ""
        try:
            _execute(session, settings, job, document)
        except CollisionError as exc:
            job.state = "awaiting_review"
            job.stage = "exporting"
            job.error = exc.message
            document.state = "awaiting_review"
            document.error_message = exc.message
            _step(session, job, "export", "collision", exc.message)
        except (AppError, UrlRejected) as exc:
            message = exc.message if hasattr(exc, "message") else str(exc)
            job.state = "failed"
            job.error = message[:500]
            job.finished_at = utcnow()
            document.state = "failed"
            document.error_message = job.error
            _step(session, job, "error", "failed", job.error)
            logger.warning("job %s falhou: %s", job_id, job.error)
        except Exception as exc:
            job.state = "failed"
            job.error = f"{type(exc).__name__}: {exc}"[:500]
            job.finished_at = utcnow()
            document.state = "failed"
            document.error_message = job.error
            _step(session, job, "error", "failed", job.error)
            logger.exception("job %s falhou", job_id)


def process_available() -> bool:
    settings = get_settings()
    with session_scope() as session:
        limit = int(preference_value(session, "max_concurrent_jobs") or 1)
    limit = max(1, min(limit, 4))
    ids = claim_jobs(limit)
    if not ids:
        return False
    if len(ids) == 1:
        run_job(ids[0])
    else:
        with ThreadPoolExecutor(max_workers=len(ids)) as pool:
            list(pool.map(run_job, ids))
    return True


def claim_jobs(limit: int) -> list[str]:
    with _claim_lock:
        with session_scope() as session:
            jobs = session.scalars(
                select(ProcessingJob)
                .where(ProcessingJob.state == "queued")
                .order_by(ProcessingJob.priority.desc(), ProcessingJob.created_at.asc())
                .limit(limit)
            ).all()
            ids = []
            for job in jobs:
                job.state = "validating"
                job.stage = "validating"
                document = session.get(Document, job.document_id)
                if document is not None:
                    document.state = "validating"
                ids.append(job.id)
            return ids


def _execute(session, settings, job: ProcessingJob, document: Document) -> None:
    options = job.options or {}
    if not _stage(session, job, document, "validating", 5):
        return
    languages = preference_value(session, "ocr_languages") or ["por", "eng", "chi_sim", "chi_tra"]
    max_pages = int(preference_value(session, "max_pages") or 50)
    max_bytes = int(preference_value(session, "max_download_mb") or 80) * 1024 * 1024
    timeout = float(preference_value(session, "timeout_seconds") or 30)
    allow_local = bool(settings.allow_local_network or preference_value(session, "allow_local_network"))
    folder = document_dir(settings, document.project_id, document.id)
    force = bool(options.get("force_recapture"))
    checkpoint = dict(job.checkpoint or {})
    if force:
        _clear_working_files(session, document, folder)
        checkpoint = {}
        job.checkpoint = {}
    local = _ensure_source(session, settings, job, document, folder, allow_local, max_bytes, timeout, force)
    if not _stage(session, job, document, "capturing", 15):
        return
    existing_region = session.scalar(
        select(OCRRegion.id).where(OCRRegion.document_id == document.id, OCRRegion.deleted.is_(False)).limit(1)
    )
    resume = bool((job.checkpoint or {}).get("pages_done"))
    keep_review = existing_region is not None and not force and not resume
    if keep_review:
        _step(session, job, "ocr", "skipped", "Revisão existente preservada. A captura não foi refeita.")
    elif document.source_kind == "pdf":
        _persist_pdf(session, job, document, Path(local), languages, folder)
    elif document.source_kind == "html":
        from cpmh_backend.services.capture import capture_html

        captured = capture_html(
            document.normalized_url or document.url,
            folder / "pages",
            allow_local=allow_local,
            max_pages=max_pages,
            timeout=timeout,
        )
        document.capture_status = captured["status"]
        _persist_rendered_pages(session, job, document, captured["pages"], languages, folder)
        if captured["status"] != "complete":
            document.state = "inconclusive"
    else:
        _persist_rendered_pages(
            session,
            job,
            document,
            [_image_page(Path(local), languages)],
            languages,
            folder,
        )
    if _stopped(session, job):
        return
    if not _stage(session, job, document, "structuring", 70):
        return
    if not keep_review:
        _rebuild_elements(session, document)
    _continue_tables(session, document)
    _detect_document_language(session, document)
    if not _stage(session, job, document, "translating", 82):
        return
    _translate(session, job, document, options, allow_local, timeout)
    export_formats = options.get("export_formats") or []
    output_dir = options.get("output_dir") or preference_value(session, "default_output_dir") or ""
    if export_formats and output_dir:
        if not _stage(session, job, document, "exporting", 92):
            return
        export_document(
            session,
            document,
            settings,
            formats=export_formats,
            mode=options.get("export_mode") or "editable",
            output_name=options.get("output_name") or (document.title or "documento"),
            output_dir=output_dir,
            collision=options.get("collision"),
            translate_mode=options.get("translate_mode") or "none",
            job_id=job.id,
        )
        _finish(session, job, document, "completed", "Exportação concluída.")
        return
    final = "inconclusive" if document.capture_status == "inconclusive" else "awaiting_review"
    message = (
        "Captura inconclusiva. Revise as páginas antes de tratar o documento como completo."
        if final == "inconclusive"
        else "Processamento concluído e aguardando revisão ou exportação."
    )
    _finish(session, job, document, final, message)


def _ensure_source(session, settings, job, document, folder: Path, allow_local, max_bytes, timeout, force: bool) -> str:
    if document.local_path and Path(document.local_path).exists() and not force and document.source_kind != "html":
        return document.local_path
    if document.origin == "file" and document.local_path and Path(document.local_path).exists():
        return document.local_path
    if not document.url:
        raise AppError("O documento não possui arquivo local nem URL.")
    _step(session, job, "validating", "done", "URL validada para download autorizado.")
    result = fetch_url(document.url, allow_local=allow_local, max_bytes=max_bytes, timeout=timeout)
    if result.kind == "pdf":
        destination = folder / "original" / "source.pdf"
        destination.write_bytes(result.data)
        document.local_path = str(destination)
        document.source_kind = "pdf"
        document.content_sha256 = sha256_bytes(result.data)
        return str(destination)
    if result.kind in {"png", "jpeg", "webp"}:
        suffix = {"png": ".png", "jpeg": ".jpg", "webp": ".webp"}[result.kind]
        destination = folder / "original" / f"source{suffix}"
        destination.write_bytes(result.data)
        document.local_path = str(destination)
        document.source_kind = "image"
        document.content_sha256 = sha256_bytes(result.data)
        return str(destination)
    if result.kind == "html":
        document.source_kind = "html"
        document.local_path = ""
        return document.normalized_url or document.url
    raise AppError("O endereço não devolveu um PDF, uma imagem ou uma página HTML utilizável.")


def _persist_pdf(session, job, document, pdf_path: Path, languages, folder: Path) -> None:
    if not _stage(session, job, document, "ocr", 35):
        return
    existing_pages = session.scalars(select(DocumentPage).where(DocumentPage.document_id == document.id)).all()
    done = set((job.checkpoint or {}).get("pages_done") or [])
    kept = {
        page.sequence
        for page in existing_pages
        if page.sequence in done and page.image_path and Path(page.image_path).exists()
    }
    analysis = analyze_pdf(pdf_path, languages)
    document.page_count = analysis["page_count"]
    document.page_count_estimate = analysis["page_count"]
    document.capture_status = "complete"
    if not kept:
        _replace_pages(session, document)
    for page in analysis["pages"]:
        if page["sequence"] in kept:
            continue
        if _stopped(session, job):
            return
        _store_page(session, document, page, folder, document.url)
        done = list((job.checkpoint or {}).get("pages_done") or [])
        done.append(page["sequence"])
        job.checkpoint = {"pages_done": done, "stage": "ocr"}
        session.flush()
    _step(session, job, "ocr", "done", f"{analysis['page_count']} página(s) analisadas a partir do PDF.")


def _persist_rendered_pages(session, job, document, pages: list[dict], languages, folder: Path) -> None:
    if not _stage(session, job, document, "ocr", 40):
        return
    _replace_pages(session, document)
    for page in pages:
        if not page.get("blocks"):
            image = Image.open(page["path"]).convert("RGB")
            blocks, image, notes = recognize(image, languages)
            classify_blocks(blocks)
            image.save(page["path"], format="PNG")
            page["blocks"] = blocks
            page["width"], page["height"] = image.size
            page["notes"] = notes
            page["source"] = "ocr"
        _store_page(session, document, page, folder, page.get("source_url") or document.url)
    document.page_count = len(pages)
    document.page_count_estimate = len(pages)
    _step(session, job, "ocr", "done", f"{len(pages)} página(s) reconhecidas.")


def _image_page(path: Path, languages: list[str]) -> dict:
    image = Image.open(path).convert("RGB")
    blocks, prepared, notes = recognize(image, languages)
    classify_blocks(blocks)
    return {
        "sequence": 1,
        "image": prepared,
        "path": "",
        "width": prepared.width,
        "height": prepared.height,
        "blocks": blocks,
        "blank": False,
        "partial": False,
        "source": "ocr",
        "notes": notes,
        "reported_number": "",
        "table": None,
        "formulas": [],
        "images": [],
    }


def _store_page(session, document, page: dict, folder: Path, source_url: str) -> None:
    image = page.get("image")
    if image is not None:
        image_path = folder / "pages" / f"page-{page['sequence']:04d}.png"
        image.save(image_path, format="PNG")
        digest = sha256_file(image_path)
        perceptual = dhash(image)
        width, height = image.size
    else:
        image_path = Path(page["path"])
        digest = page.get("sha256") or sha256_file(image_path)
        perceptual = page.get("phash") or ""
        width = page["width"]
        height = page["height"]
    record = DocumentPage(
        id=new_id(),
        document_id=document.id,
        sequence=page["sequence"],
        reported_number=str(page.get("reported_number") or ""),
        image_path=str(image_path),
        width=width,
        height=height,
        captured_at=utcnow(),
        source_url=source_url,
        sha256=digest,
        phash=perceptual,
        state="partial" if page.get("partial") else ("blank" if page.get("blank") else "captured"),
        metadata_json={"source": page.get("source") or "", "notes": page.get("notes") or {}},
        blank=bool(page.get("blank")),
        partial=bool(page.get("partial")),
    )
    session.add(record)
    session.flush()
    session.add(
        Capture(
            id=new_id(),
            document_id=document.id,
            page_id=record.id,
            kind=page.get("source") or "page",
            path=str(image_path),
            sha256=digest,
            created_at=utcnow(),
            metadata_json={"sequence": page["sequence"]},
        )
    )
    ordered = reading_order(page.get("blocks") or [])
    for block in ordered:
        region = OCRRegion(
            id=new_id(),
            page_id=record.id,
            document_id=document.id,
            category=block.category if block.category else "unknown",
            text=block.text,
            confidence=float(block.confidence or 0),
            x=block.bbox[0],
            y=block.bbox[1],
            w=block.bbox[2],
            h=block.bbox[3],
            language=block.language or detect_language(block.text),
            review_state="pending",
            original_text=block.text,
            original_category=block.category,
            original_x=block.bbox[0],
            original_y=block.bbox[1],
            original_w=block.bbox[2],
            original_h=block.bbox[3],
            source=block.source,
            evidence=block.notes or "",
            deleted=False,
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        region.language = region.language or ""
        block.language = region.language
        session.add(region)
    table = page.get("table")
    if table:
        crop_path = ""
        if image is not None and table.get("bbox"):
            from cpmh_backend.hashing import crop_normalized

            crop = crop_normalized(image, tuple(table["bbox"]))
            if crop is not None:
                crop_path = str(folder / "images" / f"tabela-{page['sequence']:04d}.png")
                crop.save(crop_path, format="PNG")
        session.add(
            TableRecord(
                id=new_id(),
                document_id=document.id,
                page_ids=[record.id],
                rows=table.get("rows") or [],
                confidence=float(table.get("confidence") or 0),
                image_path=crop_path,
                review_state="pending",
                reliable=bool(table.get("reliable")),
                notes=table.get("notes") or "",
                x=table.get("bbox", (0, 0, 0, 0))[0],
                y=table.get("bbox", (0, 0, 0, 0))[1],
                w=table.get("bbox", (0, 0, 0, 0))[2],
                h=table.get("bbox", (0, 0, 0, 0))[3],
                page_sequence=page["sequence"],
            )
        )
    for image_info in page.get("images") or []:
        asset = image_info["image"]
        filename = f"imagem-{page['sequence']:04d}-{new_id()[:8]}.png"
        asset_path = folder / "images" / filename
        asset.save(asset_path, format="PNG")
        session.add(
            ImageAsset(
                id=new_id(),
                document_id=document.id,
                page_id=record.id,
                name=filename,
                category=image_info.get("category") or "image",
                caption=image_info.get("caption") or "",
                x=image_info["bbox"][0],
                y=image_info["bbox"][1],
                w=image_info["bbox"][2],
                h=image_info["bbox"][3],
                path=str(asset_path),
                sha256=sha256_file(asset_path),
                width=asset.width,
                height=asset.height,
                format="png",
                confidence=float(image_info.get("confidence") or 0),
                review_state="pending",
            )
        )
    for formula in page.get("formulas") or []:
        block = formula["block"]
        crop = formula.get("crop")
        crop_path = ""
        if crop is not None:
            crop_path = str(folder / "images" / f"formula-{page['sequence']:04d}-{new_id()[:8]}.png")
            crop.save(crop_path, format="PNG")
        session.add(
            FormulaRecord(
                id=new_id(),
                document_id=document.id,
                page_id=record.id,
                region_id=None,
                text=block.text,
                latex=block.text if formula.get("reliable") else "",
                image_path=crop_path,
                confidence=float(block.confidence or 0),
                reliable=bool(formula.get("reliable")),
                notes=formula.get("notes") or "",
            )
        )


def _rebuild_elements(session, document: Document) -> None:
    session.execute(delete(DocumentElement).where(DocumentElement.document_id == document.id))
    pages = session.scalars(
        select(DocumentPage).where(DocumentPage.document_id == document.id).order_by(DocumentPage.sequence)
    ).all()
    pieces: list[FlowPiece] = []
    order = 0
    for page in pages:
        regions = session.scalars(
            select(OCRRegion).where(OCRRegion.page_id == page.id, OCRRegion.deleted.is_(False))
        ).all()
        blocks: list[Block] = []
        by_identity: dict[int, OCRRegion] = {}
        for region in regions:
            block = Block(
                text=region.text,
                bbox=(region.x, region.y, region.w, region.h),
                confidence=region.confidence,
                category=region.category or "paragraph",
                source=region.source or "",
            )
            blocks.append(block)
            by_identity[id(block)] = region
        for block in reading_order(blocks):
            region = by_identity[id(block)]
            element_id = new_id()
            element = DocumentElement(
                id=element_id,
                document_id=document.id,
                kind=region.category or "paragraph",
                order_index=order,
                text=region.text,
                confidence=region.confidence,
                level=1 if region.category == "title" else (2 if region.category == "subtitle" else 0),
                page_ids=[page.id],
                region_ids=[region.id],
                metadata_json={"page_sequence": page.sequence, "evidence": region.evidence or ""},
                skip_export=False,
            )
            session.add(element)
            if region.category in {"paragraph", "running_text"}:
                pieces.append(
                    FlowPiece(
                        id=element_id,
                        kind=region.category,
                        text=region.text,
                        page_index=page.sequence,
                        bbox=(region.x, region.y, region.w, region.h),
                    )
                )
            order += 1
    session.flush()
    link_page_continuity(pieces)
    for piece in pieces:
        element = session.get(DocumentElement, piece.id)
        if element is None:
            continue
        element.text = piece.text
        element.skip_export = piece.skip
        element.continued_from = piece.continued_from
        element.continued_in = piece.continued_in
        if piece.continued_from:
            parent = session.get(DocumentElement, piece.continued_from)
            if parent is not None and element.page_ids:
                parent.page_ids = list(dict.fromkeys([*parent.page_ids, *element.page_ids]))


def _continue_tables(session, document: Document) -> None:
    tables = session.scalars(select(TableRecord).where(TableRecord.document_id == document.id)).all()
    tables = sorted(tables, key=lambda item: item.page_sequence)
    from cpmh_backend.intelligence import merge_table_rows, tables_can_continue

    for previous, nxt in zip(tables, tables[1:]):
        payload_prev = {"page_sequence": previous.page_sequence, "rows": previous.rows, "y": previous.y, "h": previous.h}
        payload_next = {"page_sequence": nxt.page_sequence, "rows": nxt.rows, "y": nxt.y, "h": nxt.h}
        if previous.rows and nxt.rows and tables_can_continue(payload_prev, payload_next):
            previous.rows = merge_table_rows(previous.rows, nxt.rows)
            previous.page_ids = list(dict.fromkeys([*previous.page_ids, *nxt.page_ids]))
            nxt.rows = []
            nxt.notes = "Continuação incorporada à tabela da página anterior."
            nxt.reliable = False


def _detect_document_language(session, document: Document) -> None:
    from cpmh_backend.intelligence import aggregate_language

    regions = session.scalars(select(OCRRegion).where(OCRRegion.document_id == document.id, OCRRegion.deleted.is_(False))).all()
    pairs = []
    for region in regions:
        if not region.language:
            region.language = detect_language(region.text)
        if region.category not in {"header", "footer", "page_number"}:
            pairs.append((region.language, region.text))
    document.language = aggregate_language(pairs)


def _translate(session, job, document, options, allow_local, timeout) -> None:
    from cpmh_backend.translation_modes import normalize_translation_mode

    try:
        mode = normalize_translation_mode(options.get("translate_mode") or "none")
    except ValueError:
        _step(session, job, "translating", "failed", "Modo de tradução desconhecido.")
        return
    if mode == "none":
        _step(session, job, "translating", "skipped", "Tradução não solicitada.")
        return
    session.execute(delete(TranslationRecord).where(TranslationRecord.document_id == document.id))
    project = document.project
    project_glossary = project.glossary_id if project is not None else None
    requested = options.get("glossary_id") or None
    glossary_id = project_glossary or requested
    terms = []
    if glossary_id:
        terms = session.scalars(select(GlossaryTerm).where(GlossaryTerm.glossary_id == glossary_id)).all()
    if not terms:
        from cpmh_backend.services.glossary import STARTER_NAME
        from cpmh_backend.models import Glossary

        starter = session.scalar(select(Glossary).where(Glossary.name == STARTER_NAME))
        if starter is not None:
            glossary_id = starter.id
            terms = session.scalars(select(GlossaryTerm).where(GlossaryTerm.glossary_id == starter.id)).all()
    selected = set(options.get("selected_region_ids") or [])
    elements = session.scalars(
        select(DocumentElement).where(DocumentElement.document_id == document.id).order_by(DocumentElement.order_index)
    ).all()
    endpoint = preference_value(session, "external_translation_url") or ""
    use_external = bool(options.get("external_translation"))
    consent = bool(options.get("external_consent"))
    count = 0
    for element in elements:
        if element.skip_export or element.kind in {"header", "footer", "page_number"}:
            continue
        if mode == "selected_regions" and not (selected & set(element.region_ids or [])):
            continue
        result = translate_text(
            element.text,
            list(terms),
            source_language=document.language or "en",
            use_external=use_external,
            consent=consent,
            endpoint=endpoint,
            timeout=timeout,
            allow_local=allow_local,
        )
        session.add(
            TranslationRecord(
                id=new_id(),
                document_id=document.id,
                element_id=element.id,
                source_lang=document.language or "",
                target_lang="pt",
                source_text=result["source_text"],
                translated_text=result["translated_text"],
                mode=mode,
                provider=result["provider"],
                glossary_id=glossary_id,
                partial=result["partial"],
                created_at=utcnow(),
            )
        )
        count += 1
    provider = "external" if use_external else "local"
    _step(session, job, "translating", "done", f"{count} elemento(s) processados pelo tradutor {provider}.")


def _replace_pages(session, document: Document) -> None:
    session.execute(delete(FormulaRecord).where(FormulaRecord.document_id == document.id))
    session.execute(delete(TableRecord).where(TableRecord.document_id == document.id))
    session.execute(delete(ImageAsset).where(ImageAsset.document_id == document.id))
    session.execute(delete(OCRRegion).where(OCRRegion.document_id == document.id))
    session.execute(delete(Capture).where(Capture.document_id == document.id))
    session.execute(delete(DocumentElement).where(DocumentElement.document_id == document.id))
    session.execute(delete(DocumentPage).where(DocumentPage.document_id == document.id))
    session.flush()


def _clear_working_files(session, document: Document, folder: Path) -> None:
    _replace_pages(session, document)
    for name in ("pages", "images"):
        target = folder / name
        if target.exists():
            shutil.rmtree(target)
        target.mkdir(parents=True, exist_ok=True)


def _stage(session, job, document, stage: str, progress: float) -> bool:
    session.refresh(job)
    if job.state in {"paused", "cancelled"}:
        return False
    job.state = stage
    job.stage = stage
    job.progress = progress
    document.state = stage
    document.progress = progress
    session.flush()
    return True


def _stopped(session, job) -> bool:
    session.refresh(job)
    return job.state in {"paused", "cancelled"}


def _finish(session, job, document, state: str, message: str) -> None:
    session.refresh(job)
    if job.state in {"paused", "cancelled"}:
        return
    job.state = "completed" if state in {"completed", "awaiting_review", "inconclusive"} else state
    if state == "awaiting_review":
        job.state = "completed"
        document.state = "awaiting_review"
    elif state == "inconclusive":
        job.state = "completed"
        document.state = "inconclusive"
    else:
        document.state = state
    job.stage = document.state
    job.progress = 100
    job.finished_at = utcnow()
    job.error = "" if state != "failed" else message
    document.progress = 100
    document.error_message = "" if state in {"completed", "awaiting_review"} else message
    if document.state in {"completed", "awaiting_review"}:
        document.completed_at = utcnow()
    _step(session, job, document.state, "done", message)


class QueueWorker:
    def __init__(self) -> None:
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="cpmh-queue", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)

    def notify(self) -> None:
        self._wake.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                ran = process_available()
            except Exception:
                logger.exception("falha na fila")
                ran = False
            if not ran:
                self._wake.wait(1.2)
                self._wake.clear()


def _step(session, job, name: str, state: str, message: str) -> None:
    session.add(
        ProcessingStep(
            id=new_id(),
            job_id=job.id,
            name=name,
            state=state,
            message=message[:500],
            created_at=utcnow(),
        )
    )
    logger.info("job %s %s %s", job.id, name, state)
