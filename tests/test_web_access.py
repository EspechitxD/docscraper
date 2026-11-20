"""Detecção de bloqueio e pausa. Nenhum teste resolve CAPTCHA."""

from __future__ import annotations

import datetime as dt
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from cpmh_backend.access import classify, signals_from_html
from cpmh_backend.access_flow import partition_name
from cpmh_backend.db import session_scope
from cpmh_backend.models import ProcessingJob
from cpmh_backend.services.pipeline import run_job

SECRET = "sitekey-super-secreto-que-nao-pode-ir-para-o-log-1234567890"

HCAPTCHA = f"""<!doctype html><html><head><title>Verificação</title></head><body>
<div class="h-captcha" data-sitekey="{SECRET}"></div>
<iframe src="https://hcaptcha.com/captcha/frame"></iframe>
<p>Confirme que você é humano.</p>
</body></html>"""

OPEN = """<!doctype html><html><head><title>Manual</title></head><body>
<h1>Manual aberto</h1><p>A placa é posicionada no leito.</p>
</body></html>"""


def test_classifier_covers_the_local_fixtures_without_solving_anything():
    granted = classify(signals_from_html("http://example.test/doc", "http://example.test/doc", 200, OPEN))
    assert granted["state"] == "ACCESS_GRANTED"

    script_only = classify({
        "url": "http://example.test/artigo",
        "status": 200,
        "title": "Artigo",
        "text": "O texto discute o que é um captcha, sem pedir verificação.",
        "scripts": ["https://www.google.com/recaptcha/api.js"],
        "iframes": [],
        "markers": [],
    })
    assert script_only["state"] == "ACCESS_GRANTED"

    recaptcha = classify({
        "url": "http://example.test/gate",
        "status": 200,
        "title": "Verificação",
        "text": "Não sou um robô",
        "markers": [".g-recaptcha"],
        "iframes": ["https://www.google.com/recaptcha/api2/anchor"],
        "scripts": ["https://www.google.com/recaptcha/api.js"],
    })
    assert recaptcha["state"] == "CAPTCHA_DETECTED"
    assert recaptcha["provider"] == "recaptcha_v2"

    turnstile = classify({
        "url": "http://example.test/gate",
        "status": 200,
        "title": "Turnstile",
        "text": "Confirme",
        "markers": [".cf-turnstile"],
        "iframes": ["https://challenges.cloudflare.com/cdn-cgi/challenge-platform/turnstile"],
        "scripts": [],
    })
    assert turnstile["provider"] == "turnstile"

    cloudflare = classify(signals_from_html(
        "http://example.test/doc",
        "http://example.test/cdn-cgi/challenge-platform",
        403,
        "<title>Just a moment...</title><form id='challenge-form'></form><p>Checking your browser</p>",
    ))
    assert cloudflare["state"] == "HUMAN_VERIFICATION_REQUIRED"
    assert "challenge" in cloudflare["final_url"]

    login = classify(signals_from_html("http://example.test/login", "http://example.test/login", 200, "<title>Entrar</title><input type='password'><p>Senha</p>"))
    assert login["state"] == "AUTHENTICATION_REQUIRED"

    denied = classify({"url": "http://example.test/x", "status": 403, "title": "Access denied", "text": "you have been blocked", "markers": [], "iframes": [], "scripts": []})
    assert denied["state"] == "ACCESS_DENIED"

    limited = classify({"url": "http://example.test/x", "status": 429, "text": "Too many requests", "markers": [], "iframes": [], "scripts": []})
    assert limited["state"] == "RATE_LIMITED"

    unknown = classify({"url": "http://example.test/x", "status": 503, "text": "", "markers": [], "iframes": [], "scripts": []})
    assert unknown["state"] == "UNKNOWN_BLOCK"

    broken = classify({"url": "http://example.test/x", "navigation_error": "timeout"})
    assert broken["state"] == "NAVIGATION_ERROR"
    assert SECRET not in str(recaptcha["evidence"])


def test_http_block_pauses_before_extraction_and_resume_waits_for_recheck(client):
    mode = {"body": HCAPTCHA, "status": 403}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            data = mode["body"].encode()
            self.send_response(mode["status"])
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
        client.put("/api/preferences", json={"values": {"allow_local_network": True}})
        project = client.post("/api/projects", json={"name": "Acesso"}).json()
        other = client.post("/api/projects", json={"name": "Outro"}).json()
        added = client.post(f"/api/projects/{project['id']}/documents", json={"url": f"http://127.0.0.1:{port}/doc"})
        assert added.status_code == 200, added.text
        document_id = added.json()["document"]["id"]
        job = client.post(f"/api/documents/{document_id}/jobs", json={}).json()
        run_job(job["id"])
        current = client.get(f"/api/jobs/{job['id']}").json()
        assert current["state"] == "paused", current
        assert current["checkpoint"]["access"]["state"] == "CAPTCHA_DETECTED"
        assert current["checkpoint"]["access"]["provider"] == "hcaptcha"
        pages = client.get(f"/api/documents/{document_id}/pages").json()
        assert pages == []
        assert SECRET not in str(current)
        history = client.get(f"/api/jobs/{job['id']}/access").json()
        assert SECRET not in str(history)
        logs = client.get("/api/logs").json()
        assert SECRET not in str(logs)

        refused = client.post(f"/api/jobs/{job['id']}/resume")
        assert refused.status_code == 409

        observed = client.post(f"/api/jobs/{job['id']}/access/observation", json={
            "url": f"http://127.0.0.1:{port}/doc",
            "title": "Verificação",
            "text": "Confirme que você é humano.",
            "markers": [".h-captcha"],
            "iframes": ["https://hcaptcha.com/captcha/frame"],
        })
        assert observed.status_code == 200
        assert observed.json()["access"]["cleared"] is False

        mode["status"] = 200
        mode["body"] = OPEN
        checked = client.post(f"/api/jobs/{job['id']}/access/recheck")
        assert checked.status_code == 200, checked.text
        assert checked.json()["resumable"] is True

        resumed = client.post(f"/api/jobs/{job['id']}/resume")
        assert resumed.status_code == 200, resumed.text
        run_job(job["id"])
        document = client.get(f"/api/documents/{document_id}").json()
        assert document["state"] == "awaiting_review", document
        pages = client.get(f"/api/documents/{document_id}/pages").json()
        assert len(pages) == 1
        with session_scope() as db:
            stored = db.get(ProcessingJob, job["id"])
            stored.state = "queued"
        run_job(job["id"])
        pages_again = client.get(f"/api/documents/{document_id}/pages").json()
        assert len(pages_again) == 1

        second = client.post(f"/api/projects/{other['id']}/documents", json={"url": f"http://127.0.0.1:{port}/outro"}).json()["document"]["id"]
        second_job = client.post(f"/api/documents/{second}/jobs", json={}).json()
        assert partition_name(project["id"], job["id"]) != partition_name(other["id"], second_job["id"])
        assert current["checkpoint"]["access"]["partition"] == partition_name(project["id"], job["id"])
    finally:
        server.shutdown()
        server.server_close()


def test_status_without_a_browser_pauses(client):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            status = 401 if self.path.startswith("/login") else 429
            data = b"authentication required" if status == 401 else b"Too many requests"
            self.send_response(status)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, _format, *_args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        client.put("/api/preferences", json={"values": {"allow_local_network": True}})
        project = client.post("/api/projects", json={"name": "HTTP"}).json()["id"]
        for path, expected in (("/login", "AUTHENTICATION_REQUIRED"), ("/limit", "RATE_LIMITED")):
            added = client.post(f"/api/projects/{project}/documents", json={"url": f"http://127.0.0.1:{port}{path}"})
            document_id = added.json()["document"]["id"]
            job = client.post(f"/api/documents/{document_id}/jobs", json={}).json()
            run_job(job["id"])
            current = client.get(f"/api/jobs/{job['id']}").json()
            assert current["state"] == "paused", current
            assert current["checkpoint"]["access"]["state"] == expected
            assert client.get(f"/api/documents/{document_id}/pages").json() == []
    finally:
        server.shutdown()
        server.server_close()


def test_repeated_block_expires_and_does_not_resume_itself(client):
    document = client.post("/api/projects", json={"name": "Sessão"}).json()
    created = client.post(f"/api/projects/{document['id']}/documents", json={"url": "https://example.com/manual"})
    assert created.status_code == 200, created.text
    job_id = client.post(f"/api/documents/{created.json()['document']['id']}/jobs", json={}).json()["id"]
    old = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=2)).isoformat()
    with session_scope() as db:
        job = db.get(ProcessingJob, job_id)
        job.state = "paused"
        job.checkpoint = {"access": {"state": "ACCESS_GRANTED", "cleared": True, "cleared_at": old, "message": "ok", "persistent": False}}
    expired = client.post(f"/api/jobs/{job_id}/resume")
    assert expired.status_code == 409
    assert "expirou" in expired.text

    with session_scope() as db:
        job = db.get(ProcessingJob, job_id)
        job.checkpoint = {"access": {"state": "ACCESS_DENIED", "cleared": False, "persistent": True, "message": "negado"}}
    persistent = client.post(f"/api/jobs/{job_id}/resume")
    assert persistent.status_code == 409
    assert "manualmente" in persistent.text
    closed = client.post(f"/api/jobs/{job_id}/access/close")
    assert closed.status_code == 200
    assert closed.json()["closed"] is True
