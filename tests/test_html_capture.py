"""Captura sequencial de um visualizador HTML local, com rede local explicitamente permitida."""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

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
