from __future__ import annotations

import json
import zipfile
from pathlib import Path

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Mm, Pt, RGBColor
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
_ORANGE = "FF5000"
_ORANGE_DEEP = "EA2F14"
_INK = "29282A"
_STEEL = "434E54"
_SECONDARY = "575757"
_LINE = "D1D4D1"
_PAPER = "F7F7F7"
_SIDEBAR = "22272A"


def _rgb(value: str) -> RGBColor:
    return RGBColor.from_string(value)


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
    from cpmh_backend.services.pipeline import straighten_stored_pages

    straighten_stored_pages(session, document)
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
    try:
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
    except OSError as exc:
        raise AppError(
            f"Não consegui gravar em {destination}. {exc.strerror or 'O sistema recusou a gravação.'}"
        ) from exc
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
    try:
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
    except OSError as exc:
        raise AppError(
            f"Não consegui gravar em {destination}. {exc.strerror or 'O sistema recusou a gravação.'}"
        ) from exc
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
    _brand_docx(doc)
    _apply_header_footer(doc)
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
        for _y, kind, payload in _page_flow(sequence, grouped, tables, images, formulas, pages, page_of):
            if kind == "element":
                element = payload
                if translate_mode == "bilingual" and element.id in trans:
                    table = doc.add_table(rows=1, cols=2)
                    table.style = "Table Grid"
                    table.rows[0].cells[0].text = element.text
                    table.rows[0].cells[1].text = trans[element.id].translated_text
                    continue
                _add_docx_element(doc, element, _text_for(element, trans, mode, translate_mode))
            elif kind == "table":
                _add_docx_table(doc, payload)
            elif kind == "image":
                doc.add_picture(payload.path, width=Cm(12))
                if payload.caption:
                    doc.add_paragraph(payload.caption, style="Caption")
            elif kind == "formula":
                _add_docx_formula(doc, payload)
    doc.save(path)


def _flow_y(value) -> float:
    meta = getattr(value, "metadata_json", None)
    if isinstance(meta, dict) and meta.get("y") is not None:
        return float(meta["y"])
    return float(getattr(value, "y", 0) or 0)


def _page_flow(sequence, grouped, tables, images, formulas, pages, page_of) -> list[tuple[float, str, object]]:
    flow: list[tuple[float, str, object]] = []
    for element in grouped.get(sequence, []):
        flow.append((_flow_y(element), "element", element))
    for table in tables:
        if table.page_sequence == sequence:
            flow.append((float(table.y or 0), "table", table))
    for image in images:
        if page_of.get(image.page_id, -1) == sequence and image.path and Path(image.path).exists():
            flow.append((float(image.y or 0), "image", image))
    for formula in formulas:
        formula_page = next((page.sequence for page in pages if page.id == formula.page_id), -1)
        if formula_page == sequence:
            flow.append((0.5, "formula", formula))
    flow.sort(key=lambda item: item[0])
    return flow


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
    doc_table.autofit = True
    header = _table_has_header(table.rows)
    for row_index, row in enumerate(table.rows):
        for col_index in range(width):
            value = row[col_index] if col_index < len(row) else ""
            cell = doc_table.rows[row_index].cells[col_index]
            cell.text = "" if value is None else str(value)
            _paint_cell(cell, header=header and row_index == 0, band=row_index % 2 == 0)
    _tint_table_borders(doc_table)


def _table_has_header(rows: list) -> bool:
    if len(rows) < 2:
        return False
    def words(row) -> int:
        return sum(len(str(cell or "").split()) for cell in row)
    return words(rows[0]) <= max(6, int(statistics_median_words(rows[1:]) * 0.6))


def statistics_median_words(rows: list) -> float:
    counts = [sum(len(str(cell or "").split()) for cell in row) for row in rows]
    if not counts:
        return 0
    counts.sort()
    return counts[len(counts) // 2]


def _paint_cell(cell, *, header: bool, band: bool) -> None:
    shade = _ORANGE if header else (_PAPER if band else "FFFFFF")
    color = "FFFFFF" if header else _INK
    _shade_cell(cell, shade)
    for paragraph in cell.paragraphs:
        paragraph.paragraph_format.space_after = Pt(2)
        paragraph.paragraph_format.space_before = Pt(2)
        for run in paragraph.runs:
            run.font.name = "Calibri"
            run.font.size = Pt(10)
            run.font.bold = header
            run.font.color.rgb = _rgb(color)
            run._element.rPr.rFonts.set(qn("w:eastAsia"), "Calibri")


def _shade_cell(cell, fill: str) -> None:
    properties = cell._tc.get_or_add_tcPr()
    shade = OxmlElement("w:shd")
    shade.set(qn("w:val"), "clear")
    shade.set(qn("w:color"), "auto")
    shade.set(qn("w:fill"), fill)
    properties.append(shade)


def _tint_table_borders(table) -> None:
    borders = OxmlElement("w:tblBorders")
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        element = OxmlElement(f"w:{edge}")
        element.set(qn("w:val"), "single")
        element.set(qn("w:sz"), "4")
        element.set(qn("w:space"), "0")
        element.set(qn("w:color"), _LINE)
        borders.append(element)
    table._tbl.tblPr.append(borders)


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


def _brand_docx(doc: Document) -> None:
    _paint_style(doc.styles["Normal"], size=11, color=_INK, before=0, after=8)
    _paint_style(doc.styles["Title"], size=22, color=_INK, before=0, after=10, bold=True)
    _paint_style(doc.styles["Subtitle"], size=14, color=_ORANGE_DEEP, before=2, after=8)
    _paint_style(doc.styles["Heading 1"], size=16, color=_ORANGE, before=14, after=6, bold=True)
    _paint_style(doc.styles["Heading 2"], size=13, color=_ORANGE_DEEP, before=12, after=4, bold=True)
    _paint_style(doc.styles["Heading 3"], size=12, color=_STEEL, before=10, after=4, bold=True)
    _paint_style(doc.styles["Caption"], size=9, color=_SECONDARY, before=2, after=8)
    _paint_style(doc.styles["Header"], size=9, color=_STEEL, before=0, after=2)
    _paint_style(doc.styles["Footer"], size=8, color=_SECONDARY, before=0, after=0)
    section = doc.sections[0]
    section.page_width = Mm(210)
    section.page_height = Mm(297)
    section.left_margin = Mm(16)
    section.right_margin = Mm(16)
    section.top_margin = Mm(18)
    section.bottom_margin = Mm(16)
    section.header_distance = Mm(8)
    section.footer_distance = Mm(8)


def _paint_style(style, *, size: float, color: str, before: float, after: float, bold: bool = False) -> None:
    style.font.name = "Calibri"
    style.font.size = Pt(size)
    style.font.bold = bold
    style.font.color.rgb = _rgb(color)
    style.paragraph_format.space_before = Pt(before)
    style.paragraph_format.space_after = Pt(after)
    style.paragraph_format.line_spacing = 1.15
    style.element.rPr.rFonts.set(qn("w:eastAsia"), "Calibri")


def _apply_header_footer(doc: Document) -> None:
    section = doc.sections[0]
    header = section.header.paragraphs[0]
    header.clear()
    header.style = doc.styles["Header"]
    mark = header.add_run("CPMH")
    mark.bold = True
    mark.font.color.rgb = _rgb(_ORANGE)
    mark.font.size = Pt(11)
    mark.font.name = "Calibri"
    rest = header.add_run("   Document Intelligence")
    rest.font.color.rgb = _rgb(_STEEL)
    rest.font.size = Pt(9)
    rest.font.name = "Calibri"
    border = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), "12")
    bottom.set(qn("w:space"), "1")
    bottom.set(qn("w:color"), _ORANGE)
    border.append(bottom)
    header._p.get_or_add_pPr().append(border)
    footer = section.footer.paragraphs[0]
    footer.clear()
    footer.style = doc.styles["Footer"]
    brand = footer.add_run("CPMH Digital")
    brand.font.color.rgb = _rgb(_SECONDARY)
    brand.font.size = Pt(8)
    brand.font.name = "Calibri"
    footer.add_run("\t")
    _append_page_field(footer)


def _append_page_field(paragraph) -> None:
    run = paragraph.add_run()
    run.font.size = Pt(8)
    run.font.color.rgb = _rgb(_SECONDARY)
    run.font.name = "Calibri"
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = " PAGE "
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    run._r.append(begin)
    run._r.append(instr)
    run._r.append(end)


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


def _font_pair() -> tuple[str, str]:
    global _FONT_READY
    regular = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
    bold = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
    if regular.exists() and bold.exists():
        if not _FONT_READY:
            pdfmetrics.registerFont(TTFont("CPMHBody", str(regular)))
            pdfmetrics.registerFont(TTFont("CPMHDisplay", str(bold)))
            _FONT_READY = True
        return "CPMHBody", "CPMHDisplay"
    fallback = Path("/usr/share/fonts/truetype/wqy/wqy-microhei.ttc")
    if fallback.exists():
        if not _FONT_READY:
            try:
                pdfmetrics.registerFont(TTFont("CPMHBody", str(fallback), subfontIndex=0))
                _FONT_READY = True
            except Exception:
                return "Helvetica", "Helvetica"
        if _FONT_READY:
            return "CPMHBody", "CPMHBody"
    return "Helvetica", "Helvetica"


def _write_pdf(path, document, elements, pages, tables, images, formulas, translations, mode, translate_mode) -> None:
    body_font, display_font = _font_pair()
    styles = getSampleStyleSheet()
    ink = colors.HexColor("#29282A")
    orange = colors.HexColor("#FF5000")
    deep = colors.HexColor("#EA2F14")
    secondary = colors.HexColor("#575757")
    styles.add(ParagraphStyle(name="CPMHBody", parent=styles["Normal"], fontName=body_font, fontSize=10.5, leading=15, textColor=ink, spaceAfter=6))
    styles.add(ParagraphStyle(name="CPMHTitle", parent=styles["Title"], fontName=display_font, fontSize=18, leading=22, textColor=ink, spaceAfter=8))
    styles.add(ParagraphStyle(name="CPMHHeading", parent=styles["Heading2"], fontName=display_font, fontSize=13, leading=16, textColor=orange, spaceBefore=10, spaceAfter=4))
    styles.add(ParagraphStyle(name="CPMHSubhead", parent=styles["Heading3"], fontName=display_font, fontSize=11.5, leading=14, textColor=deep, spaceBefore=8, spaceAfter=3))
    styles.add(ParagraphStyle(name="CPMHCaption", parent=styles["Italic"], fontName=body_font, fontSize=8.5, leading=11, textColor=secondary, spaceAfter=6))
    styles.add(ParagraphStyle(name="CPMHCell", parent=styles["Normal"], fontName=body_font, fontSize=8.5, leading=11, textColor=ink))
    styles.add(ParagraphStyle(name="CPMHHeadCell", parent=styles["Normal"], fontName=display_font, fontSize=8.5, leading=11, textColor=colors.white))
    story = []
    note = _partial_note(translations) if _wants_translation(mode, translate_mode) else None
    if note:
        story.append(Paragraph(_xml(note), styles["CPMHCaption"]))
        story.append(Spacer(1, 0.2 * cm))
    if mode == "visual":
        for page in pages:
            if page.image_path and Path(page.image_path).exists():
                story.append(RLImage(page.image_path, width=16 * cm, height=22 * cm, kind="proportional"))
                story.append(Paragraph(f"Página {page.sequence}", styles["CPMHCaption"]))
                story.append(Spacer(1, 0.3 * cm))
    else:
        trans = _translation_map(translations)
        page_of = {page.id: page.sequence for page in pages}
        grouped: dict[int, list] = {}
        for element in elements:
            if element.skip_export or element.kind in {"header", "footer", "page_number"}:
                continue
            sequence = page_of.get(element.page_ids[0], 0) if element.page_ids else 0
            grouped.setdefault(sequence, []).append(element)
        sequences = sorted(set(grouped) | {table.page_sequence for table in tables})
        for sequence in sequences:
            for _y, kind, payload in _page_flow(sequence, grouped, tables, images, formulas, pages, page_of):
                if kind == "element":
                    element = payload
                    text = _text_for(element, trans, mode, translate_mode)
                    if not text:
                        continue
                    if element.kind == "title":
                        style = styles["CPMHTitle"]
                    elif element.level == 1:
                        style = styles["CPMHHeading"]
                    elif element.level or element.kind == "subtitle":
                        style = styles["CPMHSubhead"]
                    elif element.kind == "caption":
                        style = styles["CPMHCaption"]
                    else:
                        style = styles["CPMHBody"]
                    if translate_mode == "bilingual" and element.id in trans:
                        data = [[Paragraph(_xml(element.text), styles["CPMHCell"]), Paragraph(_xml(trans[element.id].translated_text), styles["CPMHCell"])]]
                        story.append(Table(data, colWidths=[8 * cm, 8 * cm]))
                    else:
                        story.append(Paragraph(_xml(text), style))
                elif kind == "table":
                    _add_pdf_table(story, payload, styles)
                elif kind == "image":
                    story.append(RLImage(payload.path, width=12 * cm, height=8 * cm, kind="proportional"))
                    if payload.caption:
                        story.append(Paragraph(_xml(payload.caption), styles["CPMHCaption"]))
                elif kind == "formula":
                    if payload.reliable and payload.text:
                        story.append(Paragraph(_xml(payload.text), styles["CPMHBody"]))
                    elif payload.image_path and Path(payload.image_path).exists():
                        story.append(RLImage(payload.image_path, width=8 * cm, height=2 * cm, kind="proportional"))
                        story.append(Paragraph(_xml(payload.notes or "Fórmula preservada para revisão."), styles["CPMHCaption"]))
    if not story:
        story.append(Paragraph("Documento sem conteúdo exportável.", styles["CPMHBody"]))

    def paint(canvas, pdf_doc):
        canvas.saveState()
        width, height = A4
        canvas.setFillColor(colors.HexColor("#FF5000"))
        canvas.rect(0, height - 8, width, 8, fill=1, stroke=0)
        canvas.setFillColor(colors.HexColor(f"#{_SIDEBAR}"))
        canvas.rect(0, 0, width, 26, fill=1, stroke=0)
        canvas.setFillColor(colors.white)
        canvas.setFont(body_font, 8)
        canvas.drawString(1.6 * cm, 10, "CPMH   Document Intelligence")
        canvas.drawRightString(width - 1.6 * cm, 10, str(pdf_doc.page))
        canvas.restoreState()

    pdf = SimpleDocTemplate(
        str(path),
        pagesize=A4,
        title=document.title or "CPMH Document Intelligence",
        leftMargin=1.6 * cm,
        rightMargin=1.6 * cm,
        topMargin=1.5 * cm,
        bottomMargin=1.4 * cm,
    )
    pdf.build(story, onFirstPage=paint, onLaterPages=paint)


def _add_pdf_table(story, table, styles) -> None:
    if table.rows and (table.reliable or table.review_state == "reviewed"):
        header = _table_has_header(table.rows)
        data = []
        for index, row in enumerate(table.rows):
            style = styles["CPMHHeadCell"] if header and index == 0 else styles["CPMHCell"]
            data.append([Paragraph(_xml(str(cell or "")), style) for cell in row])
        commands = [
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#D1D4D1")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("BACKGROUND", (0, 1), (-1, -1), colors.white),
        ]
        if header:
            commands.append(("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#FF5000")))
        else:
            commands.append(("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F7F7F7")))
        story.append(Table(data, style=TableStyle(commands)))
        story.append(Spacer(1, 0.3 * cm))
    elif table.image_path and Path(table.image_path).exists():
        story.append(RLImage(table.image_path, width=14 * cm, height=6 * cm, kind="proportional"))
        story.append(Paragraph("Tabela com reconhecimento incompleto — revisão necessária.", styles["CPMHCaption"]))


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
