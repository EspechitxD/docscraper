from pathlib import Path

import pypdfium2 as pdfium
from docx import Document
from pypdf import PdfReader
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from reportlab.lib import colors
from PIL import Image as PILImage
from reportlab.pdfgen import canvas

from cpmh_backend.services.fetch import fetch_url
from cpmh_backend.services.pipeline import run_job
import httpx


FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
CJK = "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc"


def _fonts():
    if "DejaVu" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("DejaVu", FONT))
    if Path(CJK).exists() and "WQY" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("WQY", CJK, subfontIndex=0))


def build_manual(path: Path) -> None:
    _fonts()
    styles = getSampleStyleSheet()
    styles["Title"].fontName = "DejaVu"
    styles["Normal"].fontName = "DejaVu"
    styles["Heading2"].fontName = "DejaVu"
    image_path = path.parent / "figura.png"
    PILImage.new("RGB", (120, 70), (255, 80, 0)).save(image_path)
    doc = SimpleDocTemplate(str(path), pagesize=A4, title="Manual técnico de ancoragem")
    story = [
        Paragraph("Manual técnico de ancoragem", styles["Title"]),
        Spacer(1, 0.4 * cm),
        Paragraph("Este procedimento descreve a placa e o parafuso em titânio para fixação.", styles["Normal"]),
        Spacer(1, 0.3 * cm),
        Paragraph("Equação de tensão", styles["Heading2"]),
        Paragraph("E = mc²", styles["Normal"]),
        Spacer(1, 0.3 * cm),
        Table(
            [["Código", "Peça", "Medida"], ["A1", "Placa", "30"], ["B2", "Parafuso", "2,0 mm"]],
            colWidths=[4 * cm, 5 * cm, 4 * cm],
            style=TableStyle([("GRID", (0, 0), (-1, -1), 0.6, colors.black), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EDEDED"))]),
        ),
        Spacer(1, 0.4 * cm),
        Paragraph("Figura 1. Placa de referência.", styles["Normal"]),
    ]
    # A imagem entra pelo canvas depois, para o pdfium enxergar o objeto.
    doc.build(story, onFirstPage=lambda canv, _doc: canv.drawImage(str(image_path), 72, 180, 120, 70), onLaterPages=lambda canv, _doc: None)


def build_split_paragraph(path: Path) -> None:
    _fonts()
    c = canvas.Canvas(str(path), pagesize=A4)
    width, height = A4
    c.setFont("DejaVu", 9)
    c.drawString(72, height - 36, "CPMH Document Intelligence")
    c.drawString(72, 28, "Documento de teste")
    c.setFont("DejaVu", 12)
    c.drawString(72, 80, "O dispositivo foi")
    c.showPage()
    c.setFont("DejaVu", 9)
    c.drawString(72, height - 36, "CPMH Document Intelligence")
    c.drawString(72, 28, "Documento de teste")
    c.setFont("DejaVu", 12)
    c.drawString(72, height - 90, "posicionado no leito ósseo.")
    c.save()


def build_columns(path: Path) -> None:
    _fonts()
    c = canvas.Canvas(str(path), pagesize=A4)
    _w, height = A4
    c.setFont("DejaVu", 11)
    c.drawString(48, height - 150, "COLUNA_ESQUERDA_A descreve o parafuso.")
    c.drawString(48, height - 180, "COLUNA_ESQUERDA_B permanece à esquerda.")
    c.drawString(340, height - 150, "COLUNA_DIREITA_A descreve a placa.")
    c.drawString(340, height - 180, "COLUNA_DIREITA_B permanece à direita.")
    c.save()


def build_cjk(path: Path, text: str) -> None:
    _fonts()
    c = canvas.Canvas(str(path), pagesize=A4)
    _w, height = A4
    c.setFont("WQY", 16)
    c.drawString(72, height - 120, text)
    c.save()


def build_scanned(path: Path) -> None:
    _fonts()
    source = path.parent / "digital.pdf"
    c = canvas.Canvas(str(source), pagesize=A4)
    _w, height = A4
    c.setFont("DejaVu", 28)
    c.drawString(72, height - 200, "ANCORAGEM")
    c.save()
    pdf = pdfium.PdfDocument(str(source))
    page = pdf[0]
    bitmap = page.render(scale=2)
    image = bitmap.to_pil()
    bitmap.close()
    page.close()
    pdf.close()
    image_path = path.parent / "scan.png"
    image.save(image_path)
    c = canvas.Canvas(str(path), pagesize=A4)
    c.drawImage(str(image_path), 0, 0, A4[0], A4[1])
    c.save()


def _project(client) -> str:
    response = client.post("/api/projects", json={"name": "Casos de teste", "description": "Projeto real de validação"})
    assert response.status_code == 200, response.text
    return response.json()["id"]


def _run_file(client, project_id, path: Path) -> dict:
    with path.open("rb") as handle:
        response = client.post(f"/api/projects/{project_id}/documents/file", files={"file": (path.name, handle, "application/pdf")})
    assert response.status_code == 200, response.text
    document = response.json()
    job = client.post(f"/api/documents/{document['id']}/jobs", json={"translate_mode": "none"})
    assert job.status_code == 200, job.text
    run_job(job.json()["id"])
    current = client.get(f"/api/documents/{document['id']}")
    assert current.status_code == 200
    return current.json()


def test_fetch_blocks_redirect_to_loopback():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "example.com":
            return httpx.Response(302, headers={"location": "http://127.0.0.1/secret"})
        return httpx.Response(200, content=b"no")

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        try:
            fetch_url(
                "http://example.com/doc",
                allow_local=False,
                max_bytes=1000,
                timeout=5,
                client=http,
                resolver=lambda host: ["93.184.216.34"] if host == "example.com" else ["127.0.0.1"],
            )
        except Exception as exc:
            assert "bloqueada" in str(exc).lower() or "redirecion" in str(exc).lower() or "rede" in str(exc).lower()
        else:
            raise AssertionError("o redirecionamento para loopback deveria ser recusado")


def test_digital_manual_pipeline(client, tmp_path):
    manual = tmp_path / "manual.pdf"
    build_manual(manual)
    project_id = _project(client)
    document = _run_file(client, project_id, manual)
    assert document["state"] in {"awaiting_review", "completed", "inconclusive"}
    assert document["page_count"] == 1
    elements = client.get(f"/api/documents/{document['id']}/elements").json()
    text = "\n".join(item["text"] for item in elements)
    assert "ancoragem" in text.lower()
    assert any(item["kind"] == "title" for item in elements)
    tables = client.get(f"/api/documents/{document['id']}/tables").json()
    assert tables and any("Placa" in str(table["rows"]) for table in tables)
    images = client.get(f"/api/documents/{document['id']}/images").json()
    assert images
    formulas = client.get(f"/api/documents/{document['id']}/formulas").json()
    assert any("E = mc" in item["text"] for item in formulas)
    out = tmp_path / "saida"
    out.mkdir()
    exported = client.post(
        f"/api/documents/{document['id']}/export",
        json={"formats": ["docx", "pdf", "txt", "json"], "mode": "editable", "output_name": "Manual_Tecnico", "output_dir": str(out), "collision": None},
    )
    assert exported.status_code == 200, exported.text
    docx = Document(out / "Manual_Tecnico.docx")
    joined = "\n".join(paragraph.text for paragraph in docx.paragraphs)
    assert "ancoragem" in joined.lower()
    assert docx.tables
    again = client.post(
        f"/api/documents/{document['id']}/export",
        json={"formats": ["docx"], "mode": "editable", "output_name": "Manual_Tecnico", "output_dir": str(out), "collision": None},
    )
    assert again.status_code == 409
    versioned = client.post(
        f"/api/documents/{document['id']}/export",
        json={"formats": ["docx"], "mode": "editable", "output_name": "Manual_Tecnico", "output_dir": str(out), "collision": "version"},
    )
    assert versioned.status_code == 200
    assert (out / "Manual_Tecnico (2).docx").exists()
    pdf_text = "\n".join(page.extract_text() or "" for page in PdfReader(out / "Manual_Tecnico.pdf").pages)
    assert "ancoragem" in pdf_text.lower()
    downloaded = client.post(
        f"/api/documents/{document['id']}/export/download",
        json={"formats": ["docx"], "mode": "editable", "output_name": "Manual_Tecnico"},
    )
    assert downloaded.status_code == 200, downloaded.text
    assert downloaded.content.startswith(b"PK")
    assert "attachment" in downloaded.headers.get("content-disposition", "")


def test_split_paragraph_and_columns(client, tmp_path):
    split = tmp_path / "split.pdf"
    columns = tmp_path / "columns.pdf"
    build_split_paragraph(split)
    build_columns(columns)
    project_id = _project(client)
    split_doc = _run_file(client, project_id, split)
    elements = client.get(f"/api/documents/{split_doc['id']}/elements").json()
    merged = [item for item in elements if "posicionado" in item["text"] and "dispositivo" in item["text"]]
    assert merged, elements
    assert merged[0]["continued_in"]
    column_doc = _run_file(client, project_id, columns)
    ordered = [item["text"] for item in client.get(f"/api/documents/{column_doc['id']}/elements").json()]
    left_b = next(index for index, text in enumerate(ordered) if "COLUNA_ESQUERDA_B" in text)
    right_a = next(index for index, text in enumerate(ordered) if "COLUNA_DIREITA_A" in text)
    assert left_b < right_a


def test_scanned_ocr_and_cjk(client, tmp_path):
    scanned = tmp_path / "scanned.pdf"
    build_scanned(scanned)
    project_id = _project(client)
    document = _run_file(client, project_id, scanned)
    elements = client.get(f"/api/documents/{document['id']}/elements").json()
    assert any("ANCORAGEM" in item["text"].upper() for item in elements), elements
    for label, text in (("simp", "钛合金植入物的技术手册"), ("trad", "鈦合金植入物的技術手冊")):
        path = tmp_path / f"{label}.pdf"
        build_cjk(path, text)
        current = _run_file(client, project_id, path)
        found = " ".join(item["text"] for item in client.get(f"/api/documents/{current['id']}/elements").json())
        assert text[:2] in found
        assert current["language"] in {"chi_sim", "chi_tra", "zh", "mul"}


def test_queue_recovery_and_batch(client, tmp_path):
    project_id = _project(client)
    ids = []
    for index in range(10):
        path = tmp_path / f"lote-{index}.pdf"
        build_columns(path)
        with path.open("rb") as handle:
            response = client.post(f"/api/projects/{project_id}/documents/file", files={"file": (path.name, handle, "application/pdf")})
        assert response.status_code == 200
        ids.append(response.json()["id"])
    jobs = []
    for document_id in ids:
        response = client.post(f"/api/documents/{document_id}/jobs", json={})
        jobs.append(response.json()["id"])
    # Interrompe a primeira antes de executar e recupera a fila na nova inicialização.
    from cpmh_backend.db import init_db, reset_db
    from cpmh_backend.config import get_settings
    from cpmh_backend.models import ProcessingJob

    settings = get_settings()
    from cpmh_backend.db import session_scope

    with session_scope() as db:
        job = db.get(ProcessingJob, jobs[0])
        job.state = "ocr"
        job.checkpoint = {"pages_done": [1], "stage": "ocr"}
    reset_db()
    init_db(settings)
    with session_scope() as db:
        job = db.get(ProcessingJob, jobs[0])
        assert job.state == "paused"
        assert job.checkpoint.get("pages_done") == [1]
    resumed = client.post(f"/api/jobs/{jobs[0]}/resume")
    assert resumed.status_code == 200
    for job_id in jobs:
        run_job(job_id)
    done = 0
    for document_id in ids:
        current = client.get(f"/api/documents/{document_id}").json()
        assert current["state"] in {"awaiting_review", "completed"}
        assert current["page_count"] == 1
        done += 1
    assert done == 10
