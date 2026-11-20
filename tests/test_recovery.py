"""Recuperação autorizada. Os cenários são locais e nenhum teste contorna bloqueio."""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from cpmh_backend.access import classify
from cpmh_backend.errors import AccessPaused
from cpmh_backend.recovery import (
    clear_recovery_state,
    domain_slot,
    managed_fetch,
    public_alternative,
    retry_plan,
    robots_allows,
    timeout_for,
)
from cpmh_backend.services.pipeline import run_job


@pytest.fixture(autouse=True)
def _clean_recovery():
    clear_recovery_state()
    yield
    clear_recovery_state()


def test_diagnosis_separates_the_local_scenarios():
    captcha = classify({
        "url": "http://example.test/doc",
        "status": 200,
        "title": "Verificação",
        "text": "Não sou um robô",
        "markers": [".g-recaptcha"],
        "iframes": ["https://www.google.com/recaptcha/api2/anchor"],
        "scripts": [],
        "rendered": True,
    })
    cloudflare = classify({
        "url": "http://example.test/doc",
        "final_url": "http://example.test/cdn-cgi/challenge-platform",
        "status": 403,
        "title": "Just a moment...",
        "text": "Checking your browser",
        "markers": ["#challenge-form"],
        "iframes": [],
        "scripts": [],
    })
    limited = classify({"url": "http://example.test/doc", "status": 429, "text": "Too many requests", "markers": [], "iframes": [], "scripts": []})
    denied = classify({"url": "http://example.test/doc", "status": 403, "text": "Access denied", "markers": [], "iframes": [], "scripts": []})
    expired = classify({"url": "http://example.test/doc", "status": 200, "title": "Sessão", "text": "Sua sessão expirou", "markers": [], "iframes": [], "scripts": [], "rendered": True})
    script = classify({"url": "http://example.test/doc", "status": 200, "title": "Documento", "text": "Habilite o JavaScript para continuar", "markers": ["<noscript"], "iframes": [], "scripts": [], "rendered": True})
    mentioned = classify({"url": "http://example.test/doc", "status": 200, "title": "Manual", "text": "Habilite o JavaScript " + ("texto " * 80), "markers": [], "iframes": [], "scripts": [], "rendered": True})
    network = classify({"url": "http://example.test/doc", "navigation_error": "network"})
    browser = classify({"url": "http://example.test/doc", "navigation_error": "browser"})
    assert [captcha["state"], cloudflare["state"], limited["state"], denied["state"]] == [
        "CAPTCHA_DETECTED",
        "HUMAN_VERIFICATION_REQUIRED",
        "RATE_LIMITED",
        "ACCESS_DENIED",
    ]
    assert expired["state"] == "SESSION_EXPIRED"
    assert script["state"] == "JAVASCRIPT_REQUIRED"
    assert mentioned["state"] == "ACCESS_GRANTED"
    assert network["state"] == "NAVIGATION_ERROR"
    assert browser["state"] == "BROWSER_ERROR"


def test_retry_policy_stops_on_blocks_and_caps_temporary_errors():
    blocked = {"state": "ACCESS_DENIED", "http_status": 403}
    assert retry_plan(blocked, attempt=1, retry_after=1, random_unit=0)["retry"] is False
    captcha = {"state": "CAPTCHA_DETECTED", "http_status": 200}
    assert retry_plan(captcha, attempt=1, retry_after=None, random_unit=0)["retry"] is False
    once = retry_plan({"state": "RATE_LIMITED", "http_status": 429}, attempt=1, retry_after=2, random_unit=0)
    assert once == {"retry": True, "wait_seconds": 2}
    assert retry_plan({"state": "RATE_LIMITED", "http_status": 429}, attempt=2, retry_after=2, random_unit=0)["retry"] is False
    assert retry_plan({"state": "RATE_LIMITED", "http_status": 429}, attempt=1, retry_after=120, random_unit=0)["retry"] is False
    first = retry_plan({"state": "NAVIGATION_ERROR", "http_status": 0}, attempt=1, retry_after=None, random_unit=0)
    third = retry_plan({"state": "UNKNOWN_BLOCK", "http_status": 503}, attempt=3, retry_after=None, random_unit=1)
    assert first["retry"] is True and first["wait_seconds"] == 0.5
    assert third["retry"] is False
    assert retry_plan({"state": "UNKNOWN_BLOCK", "http_status": 404}, attempt=1, retry_after=None, random_unit=0)["retry"] is False


def test_robots_and_public_pdf_stay_on_the_same_site():
    rules = "User-agent: *\nDisallow: /privado\nAllow: /privado/livre\n"
    assert robots_allows(rules, "/privado") is False
    assert robots_allows(rules, "/privado/livre") is True
    assert robots_allows(rules, "/aberto") is True
    specific = "User-agent: CPMHDocumentIntelligence\nDisallow: /secreto\n\nUser-agent: *\nDisallow: /\n"
    assert robots_allows(specific, "/secreto") is False
    assert robots_allows(specific, "/outro") is True
    page = """<meta name="citation_pdf_url" content="/artigo.pdf">
    <a href="https://outro.test/arquivo.pdf">outro</a>
    <a href="/cdn-cgi/challenge/arquivo.pdf">desafio</a>"""
    found = public_alternative(page, "http://exemplo.test/doc")
    assert found is not None
    assert found["url"] == "http://exemplo.test/artigo.pdf"
    assert public_alternative("<p>sem arquivo</p>", "http://exemplo.test/doc") is None
    assert timeout_for("scielo.br", 30, {"scielo.br": 12}) == 12
    assert timeout_for("www.scielo.br", 30, {"scielo.br": 12}) == 12


def _server(handler):
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def test_managed_fetch_does_not_repeat_a_block_and_retries_a_short_limit(client):
    hits = {"doc": 0, "limited": 0, "busy": 0, "pdf": 0}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            if self.path.startswith("/limited"):
                hits["limited"] += 1
                if hits["limited"] == 1:
                    body = b"Too many requests"
                    self.send_response(429)
                    self.send_header("Retry-After", "0")
                else:
                    body = b"<html><body><h1>Manual aberto</h1></body></html>"
                    self.send_response(200)
            elif self.path.startswith("/denied"):
                hits["doc"] += 1
                body = b"Access denied"
                self.send_response(403)
            elif self.path.startswith("/busy"):
                hits["busy"] += 1
                body = b"unavailable"
                self.send_response(503)
            elif self.path.startswith("/paper.pdf"):
                hits["pdf"] += 1
                body = b"%PDF-1.4\n% public\n"
                self.send_response(200)
                self.send_header("Content-Type", "application/pdf")
            elif self.path.startswith("/gated"):
                body = b'<html><meta name="citation_pdf_url" content="/paper.pdf"><p>Access denied</p></html>'
                self.send_response(403)
            else:
                body = b"User-agent: *\nDisallow:\n" if self.path.startswith("/robots.txt") else b"ok"
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
            data = body
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, _format, *_args):
            return

    server = _server(Handler)
    port = server.server_address[1]
    base = f"http://127.0.0.1:{port}"
    try:
        result, cached = managed_fetch(base + "/ok", allow_local=True, max_bytes=1000, timeout=5, sleep=lambda _seconds: None, random_unit=lambda: 0)
        assert result.data == b"ok"
        assert cached is False
        again, cached = managed_fetch(base + "/ok", allow_local=True, max_bytes=1000, timeout=5)
        assert cached is True and again.data == b"ok"
        with pytest.raises(AccessPaused):
            managed_fetch(base + "/denied", allow_local=True, max_bytes=1000, timeout=5, sleep=lambda _seconds: None, random_unit=lambda: 0)
        assert hits["doc"] == 1
        opened = managed_fetch(base + "/limited", allow_local=True, max_bytes=1000, timeout=5, sleep=lambda _seconds: None, random_unit=lambda: 0)
        assert hits["limited"] == 2
        assert b"Manual aberto" in opened[0].data
        with pytest.raises(AccessPaused):
            managed_fetch(base + "/busy", allow_local=True, max_bytes=1000, timeout=5, sleep=lambda _seconds: None, random_unit=lambda: 0)
        assert hits["busy"] == 3

        client.put("/api/preferences", json={"values": {"allow_local_network": True}})
        project = client.post("/api/projects", json={"name": "Recuperação"}).json()
        added = client.post(f"/api/projects/{project['id']}/documents", json={"url": base + "/gated"})
        document_id = added.json()["document"]["id"]
        job = client.post(f"/api/documents/{document_id}/jobs", json={}).json()
        run_job(job["id"])
        current = client.get(f"/api/jobs/{job['id']}").json()
        assert current["state"] == "paused"
        assert current["checkpoint"]["access"]["method"] == "public_pdf"
        assert current["checkpoint"]["access"]["alternative"]["url"] == base + "/paper.pdf"
        adopted = client.post(f"/api/jobs/{job['id']}/access/alternative")
        assert adopted.status_code == 200, adopted.text
        document = client.get(f"/api/documents/{document_id}").json()
        assert document["source_kind"] == "pdf"
        assert hits["pdf"] == 1
        resumed = client.post(f"/api/jobs/{job['id']}/resume")
        assert resumed.status_code == 200, resumed.text
    finally:
        server.shutdown()
        server.server_close()


def test_robots_disallow_never_requests_the_document():
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            seen.append(self.path)
            if self.path.startswith("/robots.txt"):
                body = b"User-agent: *\nDisallow: /privado\n"
                self.send_response(200)
            else:
                body = b"nao deveria"
                self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format, *_args):
            return

    server = _server(Handler)
    try:
        with pytest.raises(AccessPaused) as caught:
            managed_fetch(f"http://127.0.0.1:{server.server_address[1]}/privado", allow_local=True, max_bytes=1000, timeout=5)
        assert caught.value.verdict["provider"] == "robots"
        assert all(not path.startswith("/privado") for path in seen)
    finally:
        server.shutdown()
        server.server_close()


def test_domain_slot_keeps_one_request_at_a_time():
    current = {"open": 0, "max": 0}
    gate = threading.Lock()

    def work():
        with domain_slot("exemplo.test", 1):
            with gate:
                current["open"] += 1
                current["max"] = max(current["max"], current["open"])
            threading.Event().wait(0.05)
            with gate:
                current["open"] -= 1

    threads = [threading.Thread(target=work) for _ in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert current["max"] == 1


def test_network_failure_stops_after_three_attempts():
    server = ThreadingHTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
    port = server.server_address[1]
    server.server_close()
    trace: list[dict] = []
    with pytest.raises(AccessPaused) as caught:
        managed_fetch(
            f"http://127.0.0.1:{port}/doc",
            allow_local=True,
            max_bytes=1000,
            timeout=2,
            sleep=lambda _seconds: None,
            random_unit=lambda: 0,
            trace=trace,
        )
    assert caught.value.verdict["state"] == "NAVIGATION_ERROR"
    assert len(trace) == 3
