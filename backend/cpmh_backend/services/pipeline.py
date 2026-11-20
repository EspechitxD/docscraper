from __future__ import annotations

import logging
import shutil
import threading
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit

from PIL import Image
from sqlalchemy import delete, select

from cpmh_backend.access_flow import remember
from cpmh_backend.config import get_settings
from cpmh_backend.db import preference_value, session_scope
from cpmh_backend.errors import AccessPaused, AppError, CollisionError, UrlRejected
from cpmh_backend.recovery import declared_pdf, managed_fetch, timeout_for
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
        session.flush()
        try:
            _execute(session, settings, job, document)
        except AccessPaused as exc:
            verdict = exc.verdict if isinstance(exc.verdict, dict) else {}
            remember(session, job, document, verdict, source="capture")
            _step(session, job, "capturing", "paused", str(verdict.get("message") or "Acesso pausado.")[:500])
        except CollisionError as exc:
            job.state = "awaiting_review"
            job.stage = "exporting"
            job.error = exc.message
            document.state = "awaiting_review"
            document.error_message = exc.message
            _step(session, job, "export", "collision", exc.message)
        except (AppError, UrlRejected) as exc:
            session.refresh(job)
            if job.state in {"cancelled", "paused"}:
                return
            message = exc.message if hasattr(exc, "message") else str(exc)
            job.state = "failed"
            job.error = message[:500]
            job.finished_at = utcnow()
            job.started_at = job.started_at or job.finished_at
            job.attempts = job.attempts or 1
            document.state = "failed"
            document.error_message = job.error
            _step(session, job, "error", "failed", job.error)
            logger.warning("job %s falhou: %s", job_id, job.error)
        except Exception as exc:
            short, full = _failure_report(exc)
            stage = job.stage if job.stage in {"download", "browser", "pdf"} else ""
            if stage:
                short = f"Etapa {stage}: {short}"[:500]
                full = f"Etapa {stage}\n{full}"[:4000]
            job.state = "failed"
            job.error = full
            job.finished_at = utcnow()
            job.started_at = job.started_at or job.finished_at
            job.attempts = job.attempts or 1
            document.state = "failed"
            document.error_message = full
            _step(session, job, "error", "failed", short)
            logger.error("job %s falhou\n%s", job_id, full)


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
    host = urlsplit(document.normalized_url or document.url or "").hostname or ""
    configured = preference_value(session, "domain_timeouts") or {}
    timeout = timeout_for(host, timeout, configured if isinstance(configured, dict) else {})
    domain_limit = int(preference_value(session, "domain_concurrency") or 2)
    allow_local = bool(settings.allow_local_network or preference_value(session, "allow_local_network"))
    folder = document_dir(settings, document.project_id, document.id)
    force = bool(options.get("force_recapture"))
    checkpoint = dict(job.checkpoint or {})
    if force:
        _clear_working_files(session, document, folder)
        checkpoint = {}
        job.checkpoint = {}
    local = _ensure_source(session, settings, job, document, folder, allow_local, max_bytes, timeout, force, domain_limit)
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
        try:
            _persist_pdf(session, job, document, Path(local), languages, folder)
        except Exception as exc:
            if not _recover_html(session, job, document, folder, languages, exc):
                raise
    elif document.source_kind == "html":
        _capture_page(session, job, document, folder, languages, allow_local, max_pages, timeout)
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
    try:
        with session.begin_nested():
            from cpmh_backend.knowledge.index import index_document

            index_document(session, document)
    except Exception:
        logger.exception("A indexação da biblioteca não impediu o restante do processamento")
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


def _store_trace(job, trace: list[dict]) -> None:
    if not trace:
        return
    checkpoint = dict(job.checkpoint or {})
    rows = list(checkpoint.get("requests") or [])
    rows.extend(trace)
    checkpoint["requests"] = rows[-20:]
    job.checkpoint = checkpoint


def _ensure_source(session, settings, job, document, folder: Path, allow_local, max_bytes, timeout, force: bool, domain_limit: int) -> str:
    if document.local_path and Path(document.local_path).exists() and not force and document.source_kind != "html":
        return document.local_path
    if document.origin == "file" and document.local_path and Path(document.local_path).exists():
        return document.local_path
    if not document.url:
        raise AppError("O documento não possui arquivo local nem URL.")
    _step(session, job, "validating", "done", "URL validada para download autorizado.")
    _step(session, job, "download", "running", "Baixando o endereço.")
    job.stage = "download"
    _release_db(session)
    logger.info("job %s etapa download início %s", job.id, document.url)
    trace: list[dict] = []

    def stopped() -> bool:
        _reload_job(session, job)
        return job.state in {"cancelled", "paused"}

    try:
        result, _cached = managed_fetch(
            document.url,
            allow_local=allow_local,
            max_bytes=max_bytes,
            timeout=timeout,
            domain_limit=domain_limit,
            should_stop=stopped,
            trace=trace,
        )
    except AccessPaused:
        _store_trace(job, trace)
        raise
    except Exception:
        _store_trace(job, trace)
        _step(session, job, "download", "failed", "O download falhou.")
        raise
    if result.kind == "html":
        text = result.data.decode("utf-8", errors="replace")
        (folder / "original" / "source.html").write_bytes(result.data)
        declared = declared_pdf(text, result.final_url)
        if declared:
            _release_db(session)
            try:
                pdf_result, _pdf_cached = managed_fetch(
                    declared["url"],
                    allow_local=allow_local,
                    max_bytes=max_bytes,
                    timeout=timeout,
                    domain_limit=domain_limit,
                    should_stop=stopped,
                    trace=trace,
                )
            except AccessPaused:
                _step(session, job, "validating", "done", "O PDF indicado pela página não foi baixado. A extração continua na página HTML.")
            except (AppError, UrlRejected) as exc:
                if "cancelada" in str(getattr(exc, "message", exc)).lower():
                    _store_trace(job, trace)
                    raise
                _step(session, job, "validating", "done", "O PDF indicado pela página não foi baixado. A extração continua na página HTML.")
            except Exception:
                _store_trace(job, trace)
                _step(session, job, "download", "failed", "O download do PDF indicado pela página falhou.")
                raise
            else:
                if pdf_result.kind == "pdf":
                    result = pdf_result
    _store_trace(job, trace)
    logger.info("job %s etapa download fim kind=%s", job.id, result.kind)
    _step(session, job, "download", "done", f"Download concluído ({result.kind}).")
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


def _failure_report(exc: BaseException) -> tuple[str, str]:
    """Resumo de uma linha para a etapa e o traceback completo para o documento."""
    formatted = traceback.format_exc().strip()
    frames = traceback.extract_tb(exc.__traceback__)
    own = [frame for frame in frames if "cpmh_backend" in frame.filename.replace("\\", "/")]
    frame = (own or frames)[-1] if frames else None
    where = f"{Path(frame.filename).name}:{frame.lineno} em {frame.name}" if frame else "sem rastreio"
    short = f"{type(exc).__name__}: {exc} ({where})"
    if len(formatted) > 3400:
        formatted = formatted[:1500] + "\n...\n" + formatted[-1700:]
    return short[:500], f"{short}\n{formatted}"[:4000]


def _browser_gave_up(captured: dict) -> bool:
    access = captured.get("access") if isinstance(captured.get("access"), dict) else {}
    state = str(access.get("state") or "")
    pages = [page for page in (captured.get("pages") or []) if isinstance(page, dict)]
    if pages and captured.get("status") != "blocked":
        return False
    if captured.get("status") == "blocked" and state not in {"BROWSER_ERROR", "NAVIGATION_ERROR"}:
        return False
    return True


def _read_saved_html(folder: Path, url: str) -> dict | None:
    html_file = folder / "original" / "source.html"
    if not html_file.exists() or html_file.stat().st_size == 0:
        return None
    from cpmh_backend.services.capture import pages_from_downloaded_html

    return pages_from_downloaded_html(html_file.read_text(encoding="utf-8", errors="replace"), url, folder / "pages")


def _pause_capture(session, job, document, captured: dict) -> None:
    access = captured.get("access") if isinstance(captured.get("access"), dict) else {}
    remember(session, job, document, access, source="capture")
    _step(session, job, "capturing", "paused", str(access.get("message") or "A captura foi pausada.")[:500])


def _capture_page(session, job, document, folder: Path, languages, allow_local, max_pages, timeout) -> None:
    from cpmh_backend.services.capture import capture_html

    _step(session, job, "browser", "running", "Lendo a página no navegador.")
    job.stage = "browser"
    logger.info("job %s etapa browser início", job.id)
    _release_db(session)
    browser_error: BaseException | None = None
    try:
        captured = capture_html(
            document.normalized_url or document.url,
            folder / "pages",
            allow_local=allow_local,
            max_pages=max_pages,
            timeout=timeout,
        )
    except Exception as exc:
        browser_error = exc
        short, full = _failure_report(exc)
        logger.error("job %s etapa browser falhou\n%s", job.id, full)
        _step(session, job, "browser", "failed", short)
        captured = {"status": "browser_failed", "pages": [], "error": full}
    else:
        logger.info("job %s etapa browser fim status=%s", job.id, captured.get("status") if isinstance(captured, dict) else type(captured).__name__)
    if not isinstance(captured, dict):
        captured = {"status": "browser_failed", "pages": []}
    if _browser_gave_up(captured):
        fallback = _read_saved_html(folder, document.normalized_url or document.url or "")
        if fallback and (fallback.get("pages") or fallback.get("status") == "blocked"):
            if fallback.get("pages"):
                _step(session, job, "capturing", "done", "O navegador não leu a página. O texto foi extraído do HTML recebido.")
            captured = fallback
    if captured.get("status") == "blocked":
        _pause_capture(session, job, document, captured)
        return
    pages = [page for page in (captured.get("pages") or []) if isinstance(page, dict)]
    if not pages:
        if browser_error is not None:
            raise browser_error
        raise AppError("A página foi recebida, mas não havia texto para extrair.")
    document.capture_status = "complete" if captured.get("source") == "html_text" else (captured.get("status") or "inconclusive")
    _persist_rendered_pages(session, job, document, pages, languages, folder)
    if document.capture_status != "complete":
        document.state = "inconclusive"


def _recover_html(session, job, document, folder: Path, languages, exc: BaseException) -> bool:
    fallback = _read_saved_html(folder, document.normalized_url or document.url or "")
    if not fallback or not fallback.get("pages"):
        return False
    logger.exception("leitura do pdf indicado pela página: %s", exc)
    checkpoint = dict(job.checkpoint or {})
    checkpoint["pages_done"] = []
    job.checkpoint = checkpoint
    document.source_kind = "html"
    document.local_path = ""
    document.capture_status = "complete"
    _step(session, job, "capturing", "done", "O PDF indicado pela página não pôde ser lido. O texto foi extraído do HTML recebido.")
    _persist_rendered_pages(session, job, document, fallback["pages"], languages, folder)
    return True


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
    _step(session, job, "pdf", "running", "Lendo o PDF.")
    job.stage = "pdf"
    logger.info("job %s etapa pdf início %s", job.id, pdf_path)
    _release_db(session)
    try:
        analysis = analyze_pdf(pdf_path, languages)
    except Exception:
        _step(session, job, "pdf", "failed", "A leitura do PDF falhou.")
        raise
    logger.info("job %s etapa pdf fim páginas=%s", job.id, len(analysis.get("pages") or []))
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
        checkpoint = dict(job.checkpoint or {})
        done = list(checkpoint.get("pages_done") or [])
        done.append(page["sequence"])
        checkpoint["pages_done"] = done
        checkpoint["stage"] = "ocr"
        job.checkpoint = checkpoint
        session.flush()
    _step(session, job, "ocr", "done", f"{analysis['page_count']} página(s) analisadas a partir do PDF.")


def _persist_rendered_pages(session, job, document, pages: list[dict], languages, folder: Path) -> None:
    logger.info("job %s etapa gravação início páginas=%s", job.id, len(pages))
    if not _stage(session, job, document, "ocr", 40):
        return
    checkpoint = dict(job.checkpoint or {})
    done = set(checkpoint.get("pages_done") or [])
    if not done:
        _replace_pages(session, document)
    for page in pages:
        if not isinstance(page, dict):
            continue
        if page.get("sequence") in done:
            continue
        if not page.get("blocks"):
            _release_db(session)
            image = Image.open(page["path"]).convert("RGB")
            blocks, image, notes = recognize(image, languages)
            classify_blocks(blocks)
            image.save(page["path"], format="PNG")
            page["blocks"] = blocks
            page["width"], page["height"] = image.size
            page["notes"] = notes
            page["source"] = "ocr"
        _store_page(session, document, page, folder, page.get("source_url") or document.url)
        done.add(page["sequence"])
        checkpoint = dict(job.checkpoint or {})
        checkpoint["pages_done"] = sorted(done)
        checkpoint["stage"] = "ocr"
        job.checkpoint = checkpoint
    document.page_count = len(done) or len(pages)
    document.page_count_estimate = document.page_count
    logger.info("job %s etapa gravação fim páginas=%s", job.id, document.page_count)
    _step(session, job, "ocr", "done", f"{document.page_count} página(s) reconhecidas.")


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
    if isinstance(table, dict) and table:
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
        if not isinstance(image_info, dict) or image_info.get("image") is None or not image_info.get("bbox"):
            continue
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
        if not isinstance(formula, dict) or formula.get("block") is None:
            continue
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


def _release_db(session) -> None:
    """Encerra a transação antes de rede, navegador ou PDF.

    O SQLite só deixa uma escrita por vez. Segurar a transação durante o
    download faz o botão Extrair responder 500.
    """
    session.commit()


def _reload_job(session, job) -> None:
    session.commit()
    session.refresh(job)


def _stage(session, job, document, stage: str, progress: float) -> bool:
    _reload_job(session, job)
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
    _reload_job(session, job)
    return job.state in {"paused", "cancelled"}


def _finish(session, job, document, state: str, message: str) -> None:
    _reload_job(session, job)
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
