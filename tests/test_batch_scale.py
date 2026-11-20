"""Lotes de 50 e 100 PDFs de uma página. Mede persistência, não precisão de OCR."""

from __future__ import annotations

from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from cpmh_backend.services.pipeline import run_job

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


def _tiny_pdf(path: Path, index: int) -> None:
    if "DejaVu" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("DejaVu", FONT))
    drawing = canvas.Canvas(str(path), pagesize=A4)
    drawing.setFont("DejaVu", 12)
    drawing.drawString(48, 760, f"Documento de lote {index}. Placa e parafuso.")
    drawing.save()


def _batch(client, tmp_path, count: int) -> None:
    project = client.post("/api/projects", json={"name": f"Lote {count}"}).json()
    ids = []
    for index in range(count):
        path = tmp_path / f"doc-{index}.pdf"
        _tiny_pdf(path, index)
        with path.open("rb") as handle:
            response = client.post(
                f"/api/projects/{project['id']}/documents/file",
                files={"file": (path.name, handle, "application/pdf")},
            )
        assert response.status_code == 200, response.text
        ids.append(response.json()["id"])
    jobs = []
    for document_id in ids:
        response = client.post(f"/api/documents/{document_id}/jobs", json={})
        assert response.status_code == 200, response.text
        jobs.append(response.json()["id"])
    for job_id in jobs:
        run_job(job_id)
    states = []
    for document_id in ids:
        current = client.get(f"/api/documents/{document_id}").json()
        states.append(current["state"])
        assert current["page_count"] == 1
        assert current["state"] in {"awaiting_review", "completed"}
    listed = client.get("/api/jobs").json()
    assert len([item for item in listed if item["document_id"] in set(ids) and item["state"] == "completed"]) == count
    assert states.count("awaiting_review") + states.count("completed") == count


def test_batch_50(client, tmp_path):
    _batch(client, tmp_path, 50)


def test_batch_100(client, tmp_path):
    _batch(client, tmp_path, 100)
