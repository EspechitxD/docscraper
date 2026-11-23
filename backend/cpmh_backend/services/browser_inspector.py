"""Inspeção da página no Chromium (Playwright). Só observa: não clica em nada e não ultrapassa controles.

Coleta o que um visitante comum teria: DOM, iframes, canvas, imagens, respostas de rede e erros.
Cookies, tokens e cabeçalhos de autorização nunca são lidos nem gravados.
"""

from __future__ import annotations

import json
import logging
import re

from cpmh_backend.security import validate_url
from cpmh_backend.services.capture import browser_status, browser_unavailable_reason, launch_browser
from cpmh_backend.services.document_source_analyzer import reported_pages_from_text

logger = logging.getLogger(__name__)

INSPECT_JS = """
() => {
  const rect = (el) => { const r = el.getBoundingClientRect(); return {w: Math.round(r.width), h: Math.round(r.height), top: Math.round(r.top + window.scrollY)}; };
  const out = {title: document.title || ""};
  out.iframes = Array.from(document.querySelectorAll("iframe")).map((e) => Object.assign({src: e.src || ""}, rect(e)));
  out.embeds = Array.from(document.querySelectorAll("embed, object")).map((e) => ({tag: e.tagName, src: e.src || e.data || "", type: e.type || ""}));
  out.canvases = Array.from(document.querySelectorAll("canvas")).map(rect);
  out.images = Array.from(document.querySelectorAll("img")).map((e) => Object.assign({src: (e.currentSrc || e.src || "").slice(0, 300), nw: e.naturalWidth, nh: e.naturalHeight}, rect(e)));
  out.links = Array.from(document.querySelectorAll("a[href]")).map((a) => a.href).filter((h) => /\\.pdf(\\?|#|$)/i.test(h)).slice(0, 20);
  out.scripts = Array.from(document.querySelectorAll("script[src]")).map((s) => s.src).slice(0, 80);
  out.text_layer_chars = Array.from(document.querySelectorAll(".textLayer, [class*='textLayer']")).reduce((n, e) => n + (e.innerText || "").length, 0);
  out.controls = Array.from(document.querySelectorAll("button, a, [role='button']")).map((e) => ((e.innerText || "") + " " + (e.title || "") + " " + (e.getAttribute("aria-label") || "")).trim()).filter(Boolean).slice(0, 150);
  out.visible_text = (document.body ? document.body.innerText : "").slice(0, 60000);
  out.has_pdfjs_global = typeof window.PDFViewerApplication !== "undefined" || typeof window.pdfjsLib !== "undefined";
  const meta = document.querySelector("meta[property='og:document:page'], meta[name='og:document:page']");
  out.meta_pages = meta ? meta.getAttribute("content") : null;
  return JSON.stringify(out);
}
"""


def observe_page(page, *, url: str, responses: list[dict], network_errors: list[str], console_errors: list[str], status: int) -> dict:
    """Monta a observação a partir de uma página já carregada. Separado para poder ser testado sem navegador."""
    raw = page.evaluate(INSPECT_JS)
    data = json.loads(raw) if isinstance(raw, str) else (raw or {})
    visible = str(data.get("visible_text") or "")
    meta_pages = data.get("meta_pages")
    reported = int(meta_pages) if str(meta_pages or "").isdigit() else reported_pages_from_text(visible)
    html_head = ""
    try:
        html_head = page.content()[:20000]
    except Exception:  # pragma: no cover - página fechada
        pass
    observation = {
        "url": url,
        "final_url": getattr(page, "url", url),
        "status": status,
        "title": data.get("title", ""),
        "visible_text": visible,
        "html_head": html_head,
        "reported_pages": reported,
        "responses": responses,
        "network_errors": network_errors,
        "console_errors": console_errors,
    }
    for key in ("iframes", "embeds", "canvases", "images", "links", "scripts", "controls", "text_layer_chars", "has_pdfjs_global"):
        observation[key] = data.get(key)
    return observation


_SECRETISH = re.compile(r"(?i)(token|session|auth|key|sig|signature)=[^&\s]+")


def _clean_url(value: str) -> str:
    return _SECRETISH.sub(r"\1=***", value or "")[:400]


def inspect_url(url: str, *, timeout: float = 25.0) -> dict:
    """Abre a URL no Chrome do sistema e devolve a observação. Levanta RuntimeError sem Chrome."""
    validate_url(url)
    info = browser_status()
    if not info["playwright"] or not info["chrome"]:
        raise RuntimeError(browser_unavailable_reason(info) + " Nenhum resultado foi simulado.")
    from playwright.sync_api import sync_playwright

    responses: list[dict] = []
    network_errors: list[str] = []
    console_errors: list[str] = []
    with sync_playwright() as playwright:
        browser = launch_browser(playwright)
        try:
            context = browser.new_context(viewport={"width": 1366, "height": 900})
            page = context.new_page()
            page.on(
                "response",
                lambda r: responses.append(
                    {
                        "url": _clean_url(r.url),
                        "status": r.status,
                        "content_type": r.headers.get("content-type", ""),
                        "resource_type": r.request.resource_type,
                    }
                )
                if len(responses) < 400
                else None,
            )
            page.on("requestfailed", lambda r: network_errors.append(f"{_clean_url(r.url)}: {r.failure}") if len(network_errors) < 40 else None)
            page.on("console", lambda m: console_errors.append(m.text[:200]) if m.type == "error" and len(console_errors) < 40 else None)
            result = page.goto(url, wait_until="domcontentloaded", timeout=int(timeout * 1000))
            status = result.status if result else 0
            try:
                page.wait_for_load_state("networkidle", timeout=int(timeout * 500))
            except Exception:
                network_errors.append("a página não ficou ociosa no tempo previsto")
            # Rolagem curta: dispara só o carregamento preguiçoso que um visitante comum dispararia.
            for _ in range(4):
                page.mouse.wheel(0, 900)
                page.wait_for_timeout(500)
            page.evaluate("window.scrollTo(0, 0)")
            return observe_page(
                page, url=url, responses=responses, network_errors=network_errors, console_errors=console_errors, status=status
            )
        finally:
            browser.close()
