"""Captura sequencial de um visualizador HTML local, com rede local explicitamente permitida."""

from __future__ import annotations

import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from cpmh_backend.config import get_settings
from cpmh_backend.services.capture import pages_from_downloaded_html
from cpmh_backend.services.fetch import FetchResult
from cpmh_backend.services.pipeline import run_job

PAGE_1 = """<!doctype html><html><head><title>Página 1</title></head><body>
<h1>Manual de ancoragem</h1>
<p>Página 1 de 2</p>
<p>A placa é posicionada no leito ósseo.</p>
<a rel="next" aria-label="próxima página" href="/page-2">próxima página</a>
</body></html>"""

PAGE_2 = """<!doctype html><html><head><title>Página 2</title></head><body>
<h1>Parafuso</h1>
<p>Página 2 de 2</p>
<p>O parafuso completa a fixação.</p>
<a rel="next" aria-label="próxima página" aria-disabled="true" href="/page-2">próxima página</a>
</body></html>"""


def test_html_viewer_stops_at_declared_last_page(client):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            body = PAGE_2 if self.path.startswith("/page-2") else PAGE_1
            data = body.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, _format, *_args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client.put("/api/preferences", json={"values": {"allow_local_network": True, "max_pages": 5}})
        project = client.post("/api/projects", json={"name": "Captura HTML"}).json()
        added = client.post(
            f"/api/projects/{project['id']}/documents",
            json={"url": f"http://127.0.0.1:{port}/page-1"},
        )
        assert added.status_code == 200, added.text
        document_id = added.json()["document"]["id"]
        job = client.post(f"/api/documents/{document_id}/jobs", json={}).json()
        run_job(job["id"])
        finished = client.get(f"/api/jobs/{job['id']}").json()
        assert finished["attempts"] == 1
        assert finished["started_at"].endswith("Z")
        assert "AttributeError" not in (finished["error"] or "")
        document = client.get(f"/api/documents/{document_id}").json()
        pages = client.get(f"/api/documents/{document_id}/pages").json()
        assert document["capture_status"] == "complete", document
        assert document["page_count"] == 2, pages
        assert len(pages) == 2
        elements = client.get(f"/api/documents/{document_id}/elements").json()
        text = " ".join(item["text"] for item in elements)
        assert "placa" in text.lower()
        assert "parafuso" in text.lower()
        for page in pages:
            assert len(page["sha256"]) == 64
            assert page["width"] > 0
    finally:
        server.shutdown()
        server.server_close()


ARTICLE = """<!doctype html><html><head><title>Manual</title>
<script>var vazio = null; vazio.get("nada")</script>
</head><body><h1>Manual de ancoragem</h1><p>A placa fica no leito osseo.</p></body></html>"""

CHALLENGE = """<!doctype html><html><head><title>Verificação</title></head>
<body><div class="h-captcha"></div><p>Confirme que você é humano.</p></body></html>"""


def _serve(body: str):
    payload = body.encode()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, _format, *_args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


THEN_TRAP = """<!doctype html><html><head><title>ASTM</title>
<script>Object.prototype.then = function (resolve) { resolve(undefined); };</script>
</head><body><h1>ASTM F 3127</h1><p>Texto visivel do documento.</p></body></html>"""


CANVAS_VIEWER = """<!doctype html><html><head><title>Visor</title></head><body>
<canvas id="sheet" width="800" height="900"></canvas>
<a id="nextPageButton" title="下一页" href="#">seguinte</a>
<script>
const canvas = document.getElementById('sheet');
const ctx = canvas.getContext('2d');
function draw(step) {
  ctx.fillStyle = '#fff';
  ctx.fillRect(0, 0, 800, 900);
  ctx.fillStyle = step === 1 ? '#222' : '#0a4';
  ctx.fillRect(30, 30, 740, 500);
  ctx.fillStyle = '#fff';
  ctx.font = '64px sans-serif';
  ctx.fillText('FOLHA ' + step, 80, 280);
}
draw(1);
document.getElementById('nextPageButton').addEventListener('click', (event) => {
  event.preventDefault();
  draw(2);
});
</script>
<p>Texto ao redor que não é a folha.</p>
</body></html>"""


def test_painted_canvas_is_captured_page_by_page(tmp_path):
    from cpmh_backend.services.capture import capture_html

    server = _serve(CANVAS_VIEWER)
    port = server.server_address[1]
    try:
        captured = capture_html(
            f"http://127.0.0.1:{port}/visor",
            tmp_path / "pages",
            allow_local=True,
            max_pages=2,
            timeout=10,
        )
    finally:
        server.shutdown()
        server.server_close()
    assert len(captured["pages"]) == 2, captured.get("status")
    hashes = [page["sha256"] for page in captured["pages"]]
    assert len(set(hashes)) == 2
    for page in captured["pages"]:
        assert page["blank"] is False
        assert page["blocks"] == []


def test_thenable_page_object_is_read_instead_of_attribute_error(tmp_path):
    from cpmh_backend.services.capture import capture_html

    server = _serve(THEN_TRAP)
    port = server.server_address[1]
    try:
        captured = capture_html(
            f"http://127.0.0.1:{port}/manual",
            tmp_path / "pages",
            allow_local=True,
            max_pages=1,
            timeout=15,
        )
    finally:
        server.shutdown()
        server.server_close()
    assert captured["status"] != "blocked", captured.get("access") or captured.get("error")
    text = " ".join(block.text for page in captured["pages"] for block in page["blocks"])
    assert "Texto visivel do documento" in text
    assert "AttributeError" not in str(captured.get("error") or "")


def test_downloaded_html_keeps_visible_text_and_skips_script(tmp_path):
    result = pages_from_downloaded_html(ARTICLE, "http://exemplo.test/manual", tmp_path)
    assert result["status"] == "complete"
    text = " ".join(block.text for block in result["pages"][0]["blocks"])
    assert "placa fica no leito" in text
    assert "vazio.get" not in text
    blocked = pages_from_downloaded_html(CHALLENGE, "http://exemplo.test/desafio", tmp_path)
    assert blocked["status"] == "blocked"
    assert blocked["access"]["state"] == "CAPTCHA_DETECTED"


def test_browser_attribute_error_still_extracts_the_downloaded_html(client, monkeypatch):
    def boom(*_args, **_kwargs):
        raise AttributeError("'NoneType' object has no attribute 'get'")

    monkeypatch.setattr("cpmh_backend.services.capture.capture_html", boom)
    server = _serve(ARTICLE)
    port = server.server_address[1]
    try:
        client.put("/api/preferences", json={"values": {"allow_local_network": True, "max_pages": 2}})
        project = client.post("/api/projects", json={"name": "HTML direto"}).json()
        added = client.post(f"/api/projects/{project['id']}/documents", json={"url": f"http://127.0.0.1:{port}/manual"})
        assert added.status_code == 200, added.text
        document_id = added.json()["document"]["id"]
        job = client.post(f"/api/documents/{document_id}/jobs", json={}).json()
        run_job(job["id"])
        finished = client.get(f"/api/jobs/{job['id']}").json()
        document = client.get(f"/api/documents/{document_id}").json()
        assert finished["state"] == "completed", finished
        assert "AttributeError" not in (finished["error"] or "")
        assert document["source_kind"] == "html"
        elements = client.get(f"/api/documents/{document_id}/elements").json()
        text = " ".join(item["text"] for item in elements)
        assert "placa fica no leito" in text
        steps = " ".join(step["message"] for step in finished["steps"])
        assert "texto foi extraído do HTML recebido" in steps
    finally:
        server.shutdown()
        server.server_close()


def test_browser_crash_does_not_learn_a_challenge_page(client, monkeypatch):
    def boom(*_args, **_kwargs):
        raise AttributeError("'NoneType' object has no attribute 'get'")

    monkeypatch.setattr("cpmh_backend.services.capture.capture_html", boom)
    server = _serve(CHALLENGE)
    port = server.server_address[1]
    try:
        client.put("/api/preferences", json={"values": {"allow_local_network": True}})
        project = client.post("/api/projects", json={"name": "Desafio"}).json()
        added = client.post(f"/api/projects/{project['id']}/documents", json={"url": f"http://127.0.0.1:{port}/desafio"})
        document_id = added.json()["document"]["id"]
        job = client.post(f"/api/documents/{document_id}/jobs", json={}).json()
        run_job(job["id"])
        finished = client.get(f"/api/jobs/{job['id']}").json()
        assert finished["state"] == "paused", finished
        assert finished["checkpoint"]["access"]["state"] == "CAPTCHA_DETECTED"
        assert "AttributeError" not in (finished["error"] or "")
        assert client.get(f"/api/documents/{document_id}/pages").json() == []
    finally:
        server.shutdown()
        server.server_close()


def test_unreadable_declared_pdf_falls_back_to_page_text(client, monkeypatch):
    from io import BytesIO

    from reportlab.pdfgen import canvas

    buffer = BytesIO()
    pdf = canvas.Canvas(buffer)
    pdf.drawString(72, 720, "Texto interno do pdf")
    pdf.save()
    pdf_bytes = buffer.getvalue()
    html = """<!doctype html><html><head>
<meta name="citation_pdf_url" content="/artigo.pdf"><title>Artigo</title>
</head><body><p>Resumo visivel da pagina.</p></body></html>""".encode()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            if self.path.startswith("/artigo.pdf"):
                body, ctype = pdf_bytes, "application/pdf"
            else:
                body, ctype = html, "text/html"
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format, *_args):
            return

    def boom(*_args, **_kwargs):
        raise AttributeError("'NoneType' object has no attribute 'get'")

    monkeypatch.setattr("cpmh_backend.services.pipeline.analyze_pdf", boom)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]
    try:
        client.put("/api/preferences", json={"values": {"allow_local_network": True}})
        project = client.post("/api/projects", json={"name": "PDF ilegivel"}).json()
        added = client.post(f"/api/projects/{project['id']}/documents", json={"url": f"http://127.0.0.1:{port}/artigo"})
        document_id = added.json()["document"]["id"]
        job = client.post(f"/api/documents/{document_id}/jobs", json={}).json()
        run_job(job["id"])
        finished = client.get(f"/api/jobs/{job['id']}").json()
        document = client.get(f"/api/documents/{document_id}").json()
        assert finished["state"] == "completed", finished
        assert "AttributeError" not in (finished["error"] or "")
        assert document["source_kind"] == "html"
        text = " ".join(item["text"] for item in client.get(f"/api/documents/{document_id}/elements").json())
        assert "Resumo visivel da pagina" in text
    finally:
        server.shutdown()
        server.server_close()


def test_download_failure_keeps_the_traceback_and_the_stage(client, monkeypatch):
    def boom(*_args, **_kwargs):
        none = None
        return none.get("url")

    monkeypatch.setattr("cpmh_backend.services.pipeline.managed_fetch", boom)
    client.put("/api/preferences", json={"values": {"allow_local_network": True}})
    project = client.post("/api/projects", json={"name": "Rastreio"}).json()
    added = client.post(f"/api/projects/{project['id']}/documents", json={"url": "http://127.0.0.1/manual"})
    document_id = added.json()["document"]["id"]
    job = client.post(f"/api/documents/{document_id}/jobs", json={"translate_mode": "none", "export_formats": []})
    run_job(job.json()["id"])
    finished = client.get(f"/api/jobs/{job.json()['id']}").json()
    document = client.get(f"/api/documents/{document_id}").json()
    assert finished["state"] == "failed"
    assert document["state"] == "failed"
    assert "Traceback (most recent call last)" in finished["error"]
    assert "AttributeError" in finished["error"]
    assert "test_html_capture.py" in finished["error"]
    names = [(step["name"], step["state"]) for step in finished["steps"]]
    assert names[0][0] == "validating"
    assert ("download", "running") in names
    assert ("download", "failed") in names
    assert names[-1] == ("error", "failed")
    assert finished["steps"][-1]["message"].startswith("Etapa download: AttributeError")
    assert "pipeline.py" in finished["error"]


def test_missing_document_is_reported_without_attribute_error(client):
    client.put("/api/preferences", json={"values": {"allow_local_network": True}})
    project = client.post("/api/projects", json={"name": "Sumido"}).json()
    added = client.post(f"/api/projects/{project['id']}/documents", json={"url": "https://example.com/sumido"})
    document_id = added.json()["document"]["id"]
    job = client.post(f"/api/documents/{document_id}/jobs", json={"translate_mode": "none", "export_formats": []}).json()
    connection = sqlite3.connect(get_settings().database_path)
    connection.execute("PRAGMA foreign_keys=OFF")
    connection.execute("DELETE FROM documents WHERE id = ?", (document_id,))
    connection.commit()
    connection.close()
    run_job(job["id"])
    connection = sqlite3.connect(get_settings().database_path)
    row = connection.execute("SELECT state, error FROM processing_jobs WHERE id = ?", (job["id"],)).fetchone()
    connection.close()
    assert row[0] == "failed"
    assert row[1] == "Documento não encontrado."
    assert "AttributeError" not in (row[1] or "")


def test_download_does_not_lock_the_database(client, monkeypatch):
    probe = {"ok": False, "error": ""}

    def slow_fetch(*_args, **_kwargs):
        connection = sqlite3.connect(get_settings().database_path, timeout=1)
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("SELECT 1")
            connection.commit()
            probe["ok"] = True
        except sqlite3.OperationalError as exc:
            probe["error"] = str(exc)
        finally:
            connection.close()
        html = b"<html><body><p>A placa fica no leito osseo.</p></body></html>"
        return FetchResult("http://127.0.0.1/manual", "http://127.0.0.1/manual", html, "text/html", "html"), False

    monkeypatch.setattr("cpmh_backend.services.pipeline.managed_fetch", slow_fetch)
    def browser_crash(*_args, **_kwargs):
        raise AttributeError("'NoneType' object has no attribute 'get'")

    monkeypatch.setattr("cpmh_backend.services.capture.capture_html", browser_crash)
    client.put("/api/preferences", json={"values": {"allow_local_network": True}})
    project = client.post("/api/projects", json={"name": "Sem trava"}).json()
    added = client.post(f"/api/projects/{project['id']}/documents", json={"url": "http://127.0.0.1/manual"})
    document_id = added.json()["document"]["id"]
    job = client.post(f"/api/documents/{document_id}/jobs", json={"translate_mode": "none", "export_formats": []})
    assert job.status_code == 200, job.text
    run_job(job.json()["id"])
    assert probe["ok"], probe
    finished = client.get(f"/api/jobs/{job.json()['id']}").json()
    assert finished["state"] == "completed", finished
    assert "AttributeError" not in (finished["error"] or "")


def test_locked_database_returns_a_clear_message(client):
    project = client.post("/api/projects", json={"name": "Ocupado"}).json()
    added = client.post(f"/api/projects/{project['id']}/documents", json={"url": "https://example.com/manual"})
    document_id = added.json()["document"]["id"]
    connection = sqlite3.connect(get_settings().database_path, timeout=0.2)
    connection.execute("BEGIN IMMEDIATE")
    try:
        response = client.post(f"/api/documents/{document_id}/jobs", json={"translate_mode": "none", "export_formats": []})
    finally:
        connection.rollback()
        connection.close()
    assert response.status_code == 503, response.text
    assert response.json()["detail"]["message"] == "O banco local estava ocupado pela extração. Clique em Extrair de novo."
