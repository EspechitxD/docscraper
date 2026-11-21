from __future__ import annotations

import json
import zipfile
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Image as RLImage
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from reportlab.lib import colors
from sqlalchemy import select
from sqlalchemy.orm import Session

from cpmh_backend.config import Settings
from cpmh_backend.errors import AppError, CollisionError
from cpmh_backend.hashing import sha256_file
from cpmh_backend.models import (
    DocumentElement,
    DocumentPage,
    ExportedFile,
    FormulaRecord,
    ImageAsset,
    OCRRegion,
    RegionRevision,
    TableRecord,
    TranslationRecord,
    utcnow,
)
from cpmh_backend.security import prepare_output_dir, safe_filename

_FONT_READY = False


def resolve_output_path(directory: Path, filename: str, collision: str | None) -> Path:
    path = directory / safe_filename(filename)
    if not path.exists():
        return path
    if collision in {None, "", "cancel"}:
        raise CollisionError(str(path))
    if collision == "replace":
        return path
    if collision in {"version", "rename"}:
        for number in range(2, 1000):
            candidate = directory / f"{path.stem} ({number}){path.suffix}"
            if not candidate.exists():
                return candidate
    raise AppError("Não foi possível definir o nome do arquivo.")


def export_document(
    session: Session,
    document,
    settings: Settings,
    *,
    formats: list[str],
    mode: str,
    output_name: str,
    output_dir: str,
    collision: str | None,
    translate_mode: str = "none",
    job_id: str | None = None,
) -> list[dict]:
    from cpmh_backend.services.representation import refresh_document_representation
    from cpmh_backend.translation_modes import normalize_translation_mode

    if not formats:
        raise AppError("Escolha ao menos um formato de exportação.")
    if mode not in {"visual", "editable", "translated"}:
        raise AppError("Modo de exportação desconhecido.")
    try:
        translate_mode = normalize_translation_mode(translate_mode)
    except ValueError as exc:
        raise AppError("Modo de tradução desconhecido.") from exc
    refresh_document_representation(session, document)
    destination = prepare_output_dir(output_dir, install_dir=settings.install_dir)
    base_name = safe_filename(output_name)
    stem = Path(base_name).stem
    elements = session.scalars(
        select(DocumentElement)
        .where(DocumentElement.document_id == document.id)
        .order_by(DocumentElement.order_index)
    ).all()
    if not elements and mode != "visual":
        raise AppError("Não há estrutura documental para exportar. Processe o documento antes.")
    pages = session.scalars(
        select(DocumentPage).where(DocumentPage.document_id == document.id).order_by(DocumentPage.sequence)
    ).all()
    tables = session.scalars(select(TableRecord).where(TableRecord.document_id == document.id)).all()
    images = session.scalars(select(ImageAsset).where(ImageAsset.document_id == document.id)).all()
    formulas = session.scalars(select(FormulaRecord).where(FormulaRecord.document_id == document.id)).all()
    translations = session.scalars(select(TranslationRecord).where(TranslationRecord.document_id == document.id)).all()
    regions = session.scalars(
        select(OCRRegion).where(OCRRegion.document_id == document.id, OCRRegion.deleted.is_(False)).order_by(OCRRegion.y, OCRRegion.x)
    ).all()
    revisions = session.scalars(
        select(RegionRevision).where(RegionRevision.document_id == document.id).order_by(RegionRevision.created_at)
    ).all()
    produced: list[tuple[str, Path]] = []
    if "docx" in formats or "package" in formats:
        path = resolve_output_path(destination, f"{stem}.docx", collision)
        _write_docx(path, document, elements, pages, tables, images, formulas, translations, mode, translate_mode)
        produced.append(("docx", path))
    if "pdf" in formats or "package" in formats:
        path = resolve_output_path(destination, f"{stem}.pdf", collision)
        _write_pdf(path, document, elements, pages, tables, images, formulas, translations, mode, translate_mode)
        produced.append(("pdf", path))
    if "txt" in formats or "package" in formats:
        path = resolve_output_path(destination, f"{stem}.txt", collision)
        path.write_text(_plain_text(elements, translations, mode, translate_mode, images, tables), encoding="utf-8")
        produced.append(("txt", path))
    if "json" in formats or "package" in formats:
        path = resolve_output_path(destination, f"{stem}.json", collision)
        path.write_text(
            json.dumps(
                _json_payload(document, elements, pages, tables, images, formulas, translations, regions, revisions),
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        produced.append(("json", path))
    records = []
    for fmt, path in produced:
        record = ExportedFile(
            id=_new_id(),
            document_id=document.id,
            job_id=job_id,
            format=fmt,
            path=str(path),
            name=path.name,
            created_at=utcnow(),
            size=path.stat().st_size,
            mode=mode,
        )
        session.add(record)
        records.append(record)
    if "package" in formats:
        package = resolve_output_path(destination, f"{stem}.zip", collision)
        with zipfile.ZipFile(package, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for _fmt, path in produced:
                archive.write(path, arcname=path.name)
            for image in images:
                if image.path and Path(image.path).exists():
                    archive.write(image.path, arcname=f"imagens/{Path(image.path).name}")
            manifest = {
                "document_id": document.id,
                "title": document.title,
                "mode": mode,
                "files": [path.name for _fmt, path in produced],
                "sha256": {path.name: sha256_file(path) for _fmt, path in produced},
            }
            archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        record = ExportedFile(
            id=_new_id(),
            document_id=document.id,
            job_id=job_id,
            format="package",
            path=str(package),
            name=package.name,
            created_at=utcnow(),
            size=package.stat().st_size,
            mode=mode,
        )
        session.add(record)
        records.append(record)
    session.flush()
    return [
        {"id": item.id, "format": item.format, "path": item.path, "name": item.name, "size": item.size, "mode": item.mode}
        for item in records
    ]


def _new_id() -> str:
    import uuid

    return str(uuid.uuid4())


def _translation_map(translations) -> dict[str, TranslationRecord]:
    mapped = {}
    for item in translations:
        if item.element_id:
            mapped[item.element_id] = item
    return mapped


def _wants_translation(mode: str, translate_mode: str) -> bool:
    return mode == "translated" or translate_mode in {"document_pt_br", "selected_regions", "bilingual"}


def _text_for(element, translations: dict[str, TranslationRecord], mode: str, translate_mode: str) -> str:
    translated = translations.get(element.id)
    if translate_mode == "bilingual":
        return element.text
    if _wants_translation(mode, translate_mode) and translated is not None:
        return translated.translated_text
    return element.text


def _partial_note(translations) -> str | None:
    if any(item.partial for item in translations):
        return (
            "Tradução parcial: o motor neural local não estava disponível ou não cobre este trecho. "
            "Somente o glossário foi aplicado onde coube. O restante permanece no idioma de origem."
        )
    return None


def _write_docx(path, document, elements, pages, tables, images, formulas, translations, mode, translate_mode) -> None:
    doc = Document()
    normal = doc.styles["Normal"]
    normal.font.name = "Calibri"
    normal.font.size = Pt(11)
    _apply_header_footer(doc, elements)
    note = _partial_note(translations) if _wants_translation(mode, translate_mode) else None
    if note:
        paragraph = doc.add_paragraph(note)
        paragraph.runs[0].italic = True
    if mode == "visual":
        if not any(page.image_path for page in pages):
            raise AppError("O modo de fidelidade visual precisa das imagens das páginas.")
        for page in pages:
            if page.image_path and Path(page.image_path).exists():
                doc.add_picture(page.image_path, width=Cm(16))
                doc.add_paragraph(f"Página {page.sequence}", style="Caption")
        doc.save(path)
        return
    trans = _translation_map(translations)
    heading_elements = [element for element in elements if element.level or element.kind in {"title", "subtitle"}]
    if heading_elements:
        _add_toc(doc)
    page_of = {page.id: page.sequence for page in pages}
    grouped: dict[int, list] = {}
    for element in elements:
        if element.skip_export or element.kind in {"header", "footer", "page_number"}:
            continue
        sequence = page_of.get(element.page_ids[0], 0) if element.page_ids else 0
        grouped.setdefault(sequence, []).append(element)
    sequences = sorted(set(grouped) | {table.page_sequence for table in tables})
    for sequence in sequences:
        for element in grouped.get(sequence, []):
            if translate_mode == "bilingual" and element.id in trans:
                table = doc.add_table(rows=1, cols=2)
                table.style = "Table Grid"
                table.rows[0].cells[0].text = element.text
                table.rows[0].cells[1].text = trans[element.id].translated_text
                continue
            _add_docx_element(doc, element, _text_for(element, trans, mode, translate_mode))
        for table in tables:
            if table.page_sequence != sequence:
                continue
            _add_docx_table(doc, table)
        for image in images:
            image_page = page_of.get(image.page_id, -1)
            if image_page == sequence and image.path and Path(image.path).exists():
                doc.add_picture(image.path, width=Cm(12))
                if image.caption:
                    doc.add_paragraph(image.caption, style="Caption")
        for formula in formulas:
            formula_page = next((page.sequence for page in pages if page.id == formula.page_id), -1)
            if formula_page == sequence:
                _add_docx_formula(doc, formula)
    doc.save(path)


def _add_docx_element(doc: Document, element, text: str) -> None:
    if not text:
        return
    if element.kind == "title":
        doc.add_paragraph(text, style="Title")
    elif element.kind == "subtitle":
        doc.add_paragraph(text, style="Subtitle")
    elif element.level == 1:
        doc.add_paragraph(text, style="Heading 1")
    elif element.level == 2:
        doc.add_paragraph(text, style="Heading 2")
    elif element.level == 3:
        doc.add_paragraph(text, style="Heading 3")
    elif element.kind == "caption":
        doc.add_paragraph(text, style="Caption")
    else:
        doc.add_paragraph(text, style="Normal")


def _add_docx_table(doc: Document, table: TableRecord) -> None:
    usable = bool(table.rows) and (table.reliable or table.review_state == "reviewed")
    if not usable:
        if table.image_path and Path(table.image_path).exists():
            doc.add_picture(table.image_path, width=Cm(14))
        doc.add_paragraph("Tabela com reconhecimento incompleto — revisão necessária. Nenhuma célula foi inventada.", style="Caption")
        return
    width = len(table.rows[0])
    doc_table = doc.add_table(rows=len(table.rows), cols=width)
    doc_table.style = "Table Grid"
    for row_index, row in enumerate(table.rows):
        for col_index in range(width):
            value = row[col_index] if col_index < len(row) else ""
            doc_table.rows[row_index].cells[col_index].text = "" if value is None else str(value)


def _add_docx_formula(doc: Document, formula: FormulaRecord) -> None:
    if formula.reliable and formula.text and not any(char in formula.text for char in "∫∑∏√"):
        paragraph = doc.add_paragraph()
        paragraph._p.append(_omml(formula.text))
        if formula.image_path and Path(formula.image_path).exists():
            doc.add_picture(formula.image_path, width=Cm(6))
        return
    if formula.image_path and Path(formula.image_path).exists():
        doc.add_picture(formula.image_path, width=Cm(8))
    elif formula.text:
        doc.add_paragraph(formula.text)
    doc.add_paragraph(formula.notes or "Fórmula preservada para revisão.", style="Caption")


def _apply_header_footer(doc: Document, elements) -> None:
    headers = [element.text for element in elements if element.kind == "header" and element.text]
    footers = [element.text for element in elements if element.kind == "footer" and element.text]
    section = doc.sections[0]
    header = section.header.paragraphs[0]
    header.text = headers[0] if headers else "CPMH Document Intelligence"
    header.style = doc.styles["Header"]
    footer = section.footer.paragraphs[0]
    footer.text = footers[0] if footers else ""
    footer.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    footer.style = doc.styles["Footer"]


def _add_toc(doc: Document) -> None:
    paragraph = doc.add_paragraph()
    run = paragraph.add_run()
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = ' TOC \\o "1-3" \\h \\z \\u '
    separate = OxmlElement("w:fldChar")
    separate.set(qn("w:fldCharType"), "separate")
    placeholder = OxmlElement("w:t")
    placeholder.text = "Atualize o sumário no Word para preencher os números de página."
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    run._r.append(begin)
    run._r.append(instr)
    run._r.append(separate)
    run._r.append(placeholder)
    run._r.append(end)


def _ensure_font() -> str:
    global _FONT_READY
    path = Path("/usr/share/fonts/truetype/wqy/wqy-microhei.ttc")
    if path.exists():
        if not _FONT_READY:
            try:
                pdfmetrics.registerFont(TTFont("CPMHBody", str(path), subfontIndex=0))
                _FONT_READY = True
            except Exception:
                return "Helvetica"
        if _FONT_READY:
            return "CPMHBody"
    return "Helvetica"


def _write_pdf(path, document, elements, pages, tables, images, formulas, translations, mode, translate_mode) -> None:
    font = _ensure_font()
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="CPMHBody", parent=styles["Normal"], fontName=font, fontSize=11, leading=15))
    styles.add(ParagraphStyle(name="CPMHTitle", parent=styles["Title"], fontName=font, fontSize=18, leading=22, textColor=colors.HexColor("#29282A")))
    styles.add(ParagraphStyle(name="CPMHHeading", parent=styles["Heading2"], fontName=font, fontSize=13, leading=16, textColor=colors.HexColor("#F25620")))
    story = []
    note = _partial_note(translations) if _wants_translation(mode, translate_mode) else None
    if note:
        story.append(Paragraph(_xml(note), styles["CPMHBody"]))
        story.append(Spacer(1, 0.3 * cm))
    if mode == "visual":
        for page in pages:
            if page.image_path and Path(page.image_path).exists():
                story.append(RLImage(page.image_path, width=16 * cm, height=22 * cm, kind="proportional"))
                story.append(Paragraph(f"Página {page.sequence}", styles["Italic"]))
                story.append(Spacer(1, 0.4 * cm))
    else:
        trans = _translation_map(translations)
        for element in elements:
            if element.skip_export or element.kind in {"header", "footer", "page_number"}:
                continue
            text = _text_for(element, trans, mode, translate_mode)
            if not text:
                continue
            style = styles["CPMHTitle"] if element.kind == "title" else styles["CPMHHeading"] if element.level or element.kind == "subtitle" else styles["CPMHBody"]
            if translate_mode == "bilingual" and element.id in trans:
                data = [[Paragraph(_xml(element.text), styles["CPMHBody"]), Paragraph(_xml(trans[element.id].translated_text), styles["CPMHBody"])]]
                story.append(Table(data, colWidths=[8 * cm, 8 * cm]))
            else:
                story.append(Paragraph(_xml(text), style))
            story.append(Spacer(1, 0.15 * cm))
        for table in tables:
            if table.rows and (table.reliable or table.review_state == "reviewed"):
                data = [[Paragraph(_xml(str(cell or "")), styles["CPMHBody"]) for cell in row] for row in table.rows]
                story.append(Table(data, style=TableStyle([("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#29282A"))])))
                story.append(Spacer(1, 0.3 * cm))
            elif table.image_path and Path(table.image_path).exists():
                story.append(RLImage(table.image_path, width=14 * cm, height=6 * cm, kind="proportional"))
                story.append(Paragraph("Tabela com reconhecimento incompleto — revisão necessária.", styles["Italic"]))
        for image in images:
            if image.path and Path(image.path).exists():
                story.append(RLImage(image.path, width=12 * cm, height=8 * cm, kind="proportional"))
                if image.caption:
                    story.append(Paragraph(_xml(image.caption), styles["Italic"]))
        for formula in formulas:
            if formula.reliable and formula.text:
                story.append(Paragraph(_xml(formula.text), styles["CPMHBody"]))
            elif formula.image_path and Path(formula.image_path).exists():
                story.append(RLImage(formula.image_path, width=8 * cm, height=2 * cm, kind="proportional"))
                story.append(Paragraph(_xml(formula.notes or "Fórmula preservada para revisão."), styles["Italic"]))
    if not story:
        story.append(Paragraph("Documento sem conteúdo exportável.", styles["CPMHBody"]))
    pdf = SimpleDocTemplate(str(path), pagesize=A4, title=document.title or "CPMH Document Intelligence")
    pdf.build(story)


def _plain_text(elements, translations, mode, translate_mode, images=(), tables=()) -> str:
    trans = _translation_map(translations)
    lines = []
    note = _partial_note(translations) if _wants_translation(mode, translate_mode) else None
    if note:
        lines.append(note)
        lines.append("")
    for element in elements:
        if element.skip_export or element.kind in {"header", "footer", "page_number"}:
            continue
        if translate_mode == "bilingual" and element.id in trans:
            lines.append(element.text)
            lines.append(trans[element.id].translated_text)
        else:
            text = _text_for(element, trans, mode, translate_mode)
            if text:
                lines.append(text)
        lines.append("")
    written = {line.strip() for line in lines if line.strip()}
    for table in tables:
        for row in getattr(table, "rows", None) or []:
            line = " | ".join(str(cell or "").strip() for cell in row).strip(" |")
            if line and line not in written:
                lines.append(line)
                lines.append("")
                written.add(line)
    for image in images:
        caption = (getattr(image, "caption", "") or "").strip()
        if caption and caption not in written:
            lines.append(caption)
            lines.append("")
            written.add(caption)
    return "\n".join(lines).strip() + "\n"


def _json_payload(document, elements, pages, tables, images, formulas, translations, regions=(), revisions=()) -> dict:
    return {
        "document": {
            "id": document.id,
            "title": document.title,
            "url": document.url,
            "language": document.language,
            "source_kind": document.source_kind,
            "page_count": document.page_count,
        },
        "pages": [
            {
                "id": page.id,
                "sequence": page.sequence,
                "width": page.width,
                "height": page.height,
                "sha256": page.sha256,
                "state": page.state,
                "reported_number": page.reported_number,
            }
            for page in pages
        ],
        "elements": [
            {
                "id": element.id,
                "kind": element.kind,
                "order": element.order_index,
                "text": element.text,
                "confidence": element.confidence,
                "level": element.level,
                "page_ids": element.page_ids,
                "region_ids": element.region_ids,
                "continued_from": element.continued_from,
                "continued_in": element.continued_in,
                "skip_export": element.skip_export,
            }
            for element in elements
        ],
        "tables": [
            {
                "id": table.id,
                "rows": table.rows,
                "confidence": table.confidence,
                "reliable": table.reliable,
                "notes": table.notes,
                "page_ids": table.page_ids,
            }
            for table in tables
        ],
        "images": [
            {
                "id": image.id,
                "name": image.name,
                "category": image.category,
                "caption": image.caption,
                "sha256": image.sha256,
                "width": image.width,
                "height": image.height,
                "confidence": image.confidence,
                "bbox": [image.x, image.y, image.w, image.h],
            }
            for image in images
        ],
        "formulas": [
            {
                "id": formula.id,
                "text": formula.text,
                "latex": formula.latex,
                "reliable": formula.reliable,
                "confidence": formula.confidence,
                "notes": formula.notes,
            }
            for formula in formulas
        ],
        "translations": [
            {
                "id": item.id,
                "element_id": item.element_id,
                "mode": item.mode,
                "provider": item.provider,
                "partial": item.partial,
                "state": "partial" if item.partial or item.provider == "glossary" else "completed",
                "source_text": item.source_text,
                "translated_text": item.translated_text,
            }
            for item in translations
        ],
        "regions": [
            {
                "id": region.id,
                "page_id": region.page_id,
                "category": region.category,
                "text": region.text,
                "bbox": [region.x, region.y, region.w, region.h],
                "review_state": region.review_state,
                "evidence": region.evidence,
            }
            for region in regions
        ],
        "revisions": [
            {
                "id": revision.id,
                "region_id": revision.region_id,
                "operation": revision.operation,
                "origin": revision.origin,
                "original_text": revision.original_text,
                "revised_text": revision.revised_text,
                "original_category": revision.original_category,
                "revised_category": revision.revised_category,
                "created_at": revision.created_at.isoformat() if revision.created_at else "",
            }
            for revision in revisions
        ],
    }


def _omml(text: str):
    from docx.oxml import parse_xml

    supers = {"²": "2", "³": "3", "¹": "1"}
    chunks: list[tuple[str, str]] = []
    buffer: list[str] = []

    def flush() -> None:
        if buffer:
            chunks.append(("t", "".join(buffer)))
            buffer.clear()

    index = 0
    while index < len(text):
        char = text[index]
        if char in supers:
            flush()
            chunks.append(("sup", supers[char]))
            index += 1
            continue
        if char == "^" and index + 1 < len(text) and text[index + 1].isdigit():
            flush()
            chunks.append(("sup", text[index + 1]))
            index += 2
            continue
        buffer.append(char)
        index += 1
    flush()
    body: list[str] = []
    for kind, value in chunks:
        safe = _xml(value)
        if kind == "sup" and body:
            previous = body.pop()
            body.append(f"<m:sSup><m:e>{previous}</m:e><m:sup><m:r><m:t>{safe}</m:t></m:r></m:sup></m:sSup>")
        elif kind == "sup":
            body.append(f"<m:sSup><m:e><m:r><m:t></m:t></m:r></m:e><m:sup><m:r><m:t>{safe}</m:t></m:r></m:sup></m:sSup>")
        else:
            body.append(f'<m:r><m:t xml:space="preserve">{safe}</m:t></m:r>')
    markup = (
        '<m:oMath xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math">'
        + "".join(body)
        + "</m:oMath>"
    )
    return parse_xml(markup)


def _xml(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\n", "<br/>")
    )
