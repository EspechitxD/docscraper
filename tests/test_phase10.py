"""Fase 10: revisão refletida na exportação, tradução, imagens, layout e geometria."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

from docx import Document
from pypdf import PdfReader
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from sqlalchemy import create_engine, text

from cpmh_backend.db import _migrate_additive
from cpmh_backend.intelligence import Block, classify_blocks
from cpmh_backend.overlay_geometry import document_rect, misalignment, viewport_rect
from cpmh_backend.services.exporting import _add_docx_formula
from cpmh_backend.services.pipeline import run_job
from cpmh_backend.translation_modes import normalize_translation_mode
from test_pipeline import _project, _run_file, build_manual

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


def _fonts() -> None:
    if "DejaVu" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("DejaVu", FONT))


def build_title_body(path: Path) -> None:
    _fonts()
    c = canvas.Canvas(str(path), pagesize=A4)
    _w, height = A4
    c.setFont("DejaVu", 18)
    c.drawString(72, height - 80, "Manual tecnico de ancoragem")
    c.setFont("DejaVu", 12)
    c.drawString(72, height - 120, "A placa e o parafuso fixam o componente.")
    c.save()


def _export(client, document_id, out: Path, formats: list[str], translate_mode: str = "none") -> None:
    response = client.post(
        f"/api/documents/{document_id}/export",
        json={
            "formats": formats,
            "mode": "editable",
            "output_name": "revisado",
            "output_dir": str(out),
            "collision": "replace",
            "translate_mode": translate_mode,
        },
    )
    assert response.status_code == 200, response.text


def _texts(out: Path) -> dict[str, str]:
    docx = Document(out / "revisado.docx")
    docx_text = "\n".join(paragraph.text for paragraph in docx.paragraphs)
    pdf_text = "\n".join(page.extract_text() or "" for page in PdfReader(out / "revisado.pdf").pages)
    txt = (out / "revisado.txt").read_text(encoding="utf-8")
    payload = json.loads((out / "revisado.json").read_text(encoding="utf-8"))
    json_text = "\n".join(item["text"] for item in payload["elements"])
    with zipfile.ZipFile(out / "revisado.zip") as archive:
        packed = archive.read("revisado.txt").decode("utf-8")
    return {"docx": docx_text, "pdf": pdf_text, "txt": txt, "json": json_text, "package": packed, "payload": payload, "docx_doc": docx}


def test_review_reaches_every_export(client, tmp_path):
    source = tmp_path / "titulo.pdf"
    build_title_body(source)
    project_id = _project(client)
    document = _run_file(client, project_id, source)
    pages = client.get(f"/api/documents/{document['id']}/pages").json()
    regions = client.get(f"/api/pages/{pages[0]['id']}/regions").json()
    title = next(item for item in regions if "Manual tecnico" in item["text"])
    edited = client.patch(f"/api/regions/{title['id']}", json={"text": "Manual revisado de ancoragem"})
    assert edited.status_code == 200, edited.text
    out = tmp_path / "saida"
    out.mkdir()
    _export(client, document["id"], out, ["docx", "pdf", "txt", "json", "package"])
    texts = _texts(out)
    for name in ("docx", "pdf", "txt", "json", "package"):
        assert "Manual revisado de ancoragem" in texts[name], name
        assert "Manual tecnico de ancoragem" not in texts[name], name

    removed = client.delete(f"/api/regions/{title['id']}")
    assert removed.status_code == 200
    _export(client, document["id"], out, ["docx", "pdf", "txt", "json", "package"])
    texts = _texts(out)
    for name in ("docx", "pdf", "txt", "json", "package"):
        assert "Manual revisado de ancoragem" not in texts[name], name

    body = next(item for item in regions if "placa" in item["text"].lower())
    reclassified = client.patch(f"/api/regions/{body['id']}", json={"category": "title"})
    assert reclassified.status_code == 200
    _export(client, document["id"], out, ["docx"])
    styles = [paragraph.style.name for paragraph in Document(out / "revisado.docx").paragraphs if "placa" in paragraph.text.lower()]
    assert styles == ["Title"]

    created = client.post(
        f"/api/pages/{pages[0]['id']}/regions",
        json={"category": "paragraph", "text": "Nota criada na revisao.", "x": 0.1, "y": 0.6, "w": 0.5, "h": 0.04},
    )
    assert created.status_code == 200, created.text
    _export(client, document["id"], out, ["docx", "pdf", "txt", "json", "package"])
    texts = _texts(out)
    for name in ("docx", "pdf", "txt", "json", "package"):
        assert "Nota criada na revisao." in texts[name], name

    moved = client.patch(f"/api/regions/{created.json()['id']}", json={"x": 0.2, "y": 0.62, "w": 0.4, "h": 0.05})
    assert moved.status_code == 200
    _export(client, document["id"], out, ["json"])
    payload = json.loads((out / "revisado.json").read_text(encoding="utf-8"))
    region = next(item for item in payload["regions"] if item["text"] == "Nota criada na revisao.")
    assert region["bbox"][0] == 0.2
    assert region["bbox"][1] == 0.62

    restored = client.post(f"/api/regions/{title['id']}/restore")
    assert restored.status_code == 200
    assert restored.json()["text"] == title["original_text"]
    _export(client, document["id"], out, ["txt", "json"])
    txt = (out / "revisado.txt").read_text(encoding="utf-8")
    assert title["original_text"] in txt
    history = client.get(f"/api/documents/{document['id']}/revisions").json()
    operations = {item["operation"] for item in history}
    assert {"edit_text", "delete", "reclassify", "create", "move", "restore"} <= operations
    original = next(item for item in history if item["operation"] == "edit_text")
    assert original["original_text"] == title["original_text"]
    assert original["revised_text"] == "Manual revisado de ancoragem"


def test_translation_contract_selection_and_glossary(client, tmp_path):
    assert normalize_translation_mode("portuguese") == "document_pt_br"
    assert normalize_translation_mode("selected") == "selected_regions"
    assert normalize_translation_mode("side_by_side") == "bilingual"
    source = tmp_path / "titulo.pdf"
    build_title_body(source)
    project_id = _project(client)
    document = _run_file(client, project_id, source)
    pages = client.get(f"/api/documents/{document['id']}/pages").json()
    regions = client.get(f"/api/pages/{pages[0]['id']}/regions").json()
    body = next(item for item in regions if "plate" in item["text"].lower() or "placa" in item["text"].lower())
    other = client.post("/api/projects", json={"name": "Outro", "description": ""})
    other_doc = _run_file(client, other.json()["id"], source)
    other_pages = client.get(f"/api/documents/{other_doc['id']}/pages").json()
    foreign = client.get(f"/api/pages/{other_pages[0]['id']}/regions").json()[0]

    empty = client.post(f"/api/documents/{document['id']}/jobs", json={"translate_mode": "selected_regions", "selected_region_ids": []})
    assert empty.status_code == 400
    foreign_job = client.post(
        f"/api/documents/{document['id']}/jobs",
        json={"translate_mode": "selected", "selected_region_ids": [foreign["id"]]},
    )
    assert foreign_job.status_code == 400
    assert foreign_job.json()["detail"]["code"] == "region_not_in_document"

    glossary = client.post("/api/glossaries", json={"name": "Projeto A", "description": ""}).json()
    client.post(f"/api/glossaries/{glossary['id']}/terms", json={"source": "parafuso", "target": "PARAFUSO_REV"})
    other_glossary = client.post("/api/glossaries", json={"name": "Projeto B", "description": ""}).json()
    client.post(f"/api/glossaries/{other_glossary['id']}/terms", json={"source": "parafuso", "target": "OUTRO"})
    linked = client.patch(f"/api/projects/{project_id}", json={"glossary_id": glossary["id"]})
    assert linked.json()["glossary_id"] == glossary["id"]

    job = client.post(
        f"/api/documents/{document['id']}/jobs",
        json={"translate_mode": "selected_regions", "selected_region_ids": [body["id"]], "glossary_id": other_glossary["id"], "force_recapture": False},
    )
    assert job.status_code == 200, job.text
    assert job.json()["options"]["translate_mode"] == "selected_regions" if "options" in job.json() else True
    run_job(job.json()["id"])
    translations = client.get(f"/api/documents/{document['id']}/translations").json()
    assert translations
    assert all(item["state"] == "partial" for item in translations)
    assert all(item["provider"] == "glossary" for item in translations)
    joined = "\n".join(item["translated_text"] for item in translations)
    assert "PARAFUSO_REV" in joined
    assert "OUTRO" not in joined
    assert all("Manual" not in item["source_text"] for item in translations)

    out = tmp_path / "trad"
    out.mkdir()
    _export(client, document["id"], out, ["txt", "docx"], "bilingual")
    txt = (out / "revisado.txt").read_text(encoding="utf-8")
    assert "parafuso" in txt.lower()
    assert "PARAFUSO_REV" in txt

    cleared = client.patch(f"/api/projects/{project_id}", json={"glossary_id": None})
    assert cleared.json()["glossary_id"] is None
    again = client.post(
        f"/api/documents/{document['id']}/jobs",
        json={"translate_mode": "document_pt_br", "force_recapture": False},
    )
    run_job(again.json()["id"])
    after = client.get(f"/api/documents/{document['id']}/translations").json()
    assert "PARAFUSO_REV" not in "\n".join(item["translated_text"] for item in after)
    runtime = client.get("/api/translation/runtime").json()
    assert runtime["silent_download"] is False
    assert runtime["neural_ready"] is False


def test_layout_reference_set():
    def block(text: str, size: float, y: float, x: float = 0.12, width: float = 0.6) -> Block:
        return Block(text=text, bbox=(x, y, width, size), font_size=size, confidence=95, source="test")

    pages = {
        "titulo e corpo": (
            [
                block("Manual tecnico de ancoragem", 0.03, 0.08, x=0.18, width=0.64),
                block("A placa e o parafuso fixam o componente.", 0.016, 0.16),
            ],
            ["title", "paragraph"],
        ),
        "titulo centralizado": (
            [
                block("Capitulo de fixacao", 0.028, 0.07, x=0.2, width=0.6),
                block("O texto seguinte descreve o procedimento completo.", 0.015, 0.18),
            ],
            ["title", "paragraph"],
        ),
        "secao numerada": (
            [
                block("Procedimento geral de montagem", 0.016, 0.12),
                block("1.2 Aperto do parafuso", 0.018, 0.2),
                block("Aplique o torque indicado no manual.", 0.016, 0.28),
            ],
            ["paragraph", "subtitle", "paragraph"],
        ),
        "cabecalho e rodape": (
            [
                block("CPMH Document Intelligence", 0.012, 0.02),
                block("Texto principal da pagina de teste.", 0.016, 0.4),
                block("Documento de teste", 0.012, 0.95),
            ],
            ["header", "paragraph", "footer"],
        ),
        "legenda e formula": (
            [
                block("Descricao da peca principal.", 0.016, 0.3),
                block("Figura 1. Placa de referencia.", 0.014, 0.5),
                block("E = mc²", 0.016, 0.6),
            ],
            ["paragraph", "caption", "formula"],
        ),
    }
    correct = 0
    total = 0
    per_category: dict[str, dict[str, int]] = {}
    for _name, (blocks, expected) in pages.items():
        predicted = [item.category for item in classify_blocks(blocks)]
        assert len(predicted) == len(expected)
        for guess, truth in zip(predicted, expected):
            total += 1
            bucket = per_category.setdefault(truth, {"tp": 0, "fp": 0, "fn": 0})
            if guess == truth:
                correct += 1
                bucket["tp"] += 1
            else:
                bucket["fn"] += 1
                per_category.setdefault(guess, {"tp": 0, "fp": 0, "fn": 0})["fp"] += 1
    assert correct == total, (correct, total, per_category)
    assert per_category["title"]["tp"] == 2
    assert per_category["paragraph"]["fn"] == 0


def test_title_pdf_is_not_a_subtitle(client, tmp_path):
    source = tmp_path / "titulo.pdf"
    build_title_body(source)
    document = _run_file(client, _project(client), source)
    pages = client.get(f"/api/documents/{document['id']}/pages").json()
    regions = client.get(f"/api/pages/{pages[0]['id']}/regions").json()
    title = next(item for item in regions if "Manual tecnico" in item["text"])
    assert title["category"] == "title"
    assert title["evidence"]


def test_overlay_geometry_tolerance():
    bbox = (0.1, 0.2, 0.3, 0.05)
    page = (1000.0, 1400.0)
    expected = viewport_rect(bbox, page_width=page[0], page_height=page[1], scroll_x=40, scroll_y=80, zoom=1.25)
    measured = ((0.1 * 1000 - 40) * 1.25, (0.2 * 1400 - 80) * 1.25)
    assert misalignment(expected[:2], measured) <= 0.5
    doc = document_rect(bbox, *page)
    assert abs(doc[2] - 300) < 0.01
    for zoom in (0.5, 0.75, 1, 1.25, 1.5, 2):
        projected = viewport_rect(bbox, page_width=page[0], page_height=page[1], scroll_x=10, scroll_y=20, zoom=zoom)
        again = ((doc[0] - 10) * zoom, (doc[1] - 20) * zoom)
        assert misalignment(projected[:2], again) <= 0.5


def test_image_review_export_and_delete(client, tmp_path):
    source = tmp_path / "manual.pdf"
    build_manual(source)
    document = _run_file(client, _project(client), source)
    images = client.get(f"/api/documents/{document['id']}/images").json()
    assert images
    image = images[0]
    renamed = client.patch(f"/api/images/{image['id']}", json={"name": "placa.png", "category": "photograph", "caption": "Placa revisada"})
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["review_state"] == "reviewed"
    out = tmp_path / "imagens"
    out.mkdir()
    exported = client.post(
        f"/api/documents/{document['id']}/images/export",
        json={"ids": [image["id"]], "output_dir": str(out), "collision": None},
    )
    assert exported.status_code == 200, exported.text
    assert (out / "placa.png").exists()
    blocked = client.delete(f"/api/images/{image['id']}")
    assert blocked.status_code == 409
    removed = client.delete(f"/api/images/{image['id']}?confirm=true")
    assert removed.status_code == 200
    assert removed.json()["file_removed"] is True
    remaining = client.get(f"/api/documents/{document['id']}/images").json()
    assert all(item["id"] != image["id"] for item in remaining)
    docx_dir = tmp_path / "docx"
    docx_dir.mkdir()
    _export(client, document["id"], docx_dir, ["docx", "package"])
    package = zipfile.ZipFile(docx_dir / "revisado.zip")
    names = package.namelist()
    assert "revisado.docx" in names
    assert not any(name.endswith("placa.png") for name in names)


def test_simple_formula_is_omml_and_complex_is_not():
    class Formula:
        def __init__(self, text, reliable, notes="", image_path=""):
            self.text = text
            self.reliable = reliable
            self.notes = notes
            self.image_path = image_path

    simple = Document()
    _add_docx_formula(simple, Formula("E = mc²", True))
    markup = simple.element.body.xml
    assert "oMath" in markup
    assert "E = mc" in markup

    complex_doc = Document()
    _add_docx_formula(complex_doc, Formula("∫ F dx", False, "Fórmula com símbolos complexos."))
    assert "oMath" not in complex_doc.element.body.xml
    assert "símbolos complexos" in "\n".join(paragraph.text for paragraph in complex_doc.paragraphs)


def test_frontend_uses_the_same_translation_ids():
    root = Path(__file__).resolve().parents[1]
    labels = (root / "frontend" / "src" / "labels.ts").read_text(encoding="utf-8")
    electron = (root / "electron" / "main.ts").read_text(encoding="utf-8")
    for mode in ("none", "selected_regions", "document_pt_br", "bilingual"):
        assert mode in labels
    assert "o Python do sistema não será usado" in electron


def test_additive_migration_keeps_rows(tmp_path):
    database = tmp_path / "antigo.sqlite"
    engine = create_engine(f"sqlite:///{database}")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE ocr_regions (id TEXT PRIMARY KEY, text TEXT)"))
        connection.execute(text("INSERT INTO ocr_regions (id, text) VALUES ('r1', 'original')"))
    _migrate_additive(engine)
    with engine.connect() as connection:
        columns = {row[1] for row in connection.execute(text("PRAGMA table_info(ocr_regions)"))}
        row = connection.execute(text("SELECT text FROM ocr_regions WHERE id = 'r1'")).one()
    assert "evidence" in columns
    assert row[0] == "original"
