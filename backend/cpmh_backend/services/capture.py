from __future__ import annotations

import shutil
from pathlib import Path

from PIL import Image

import time

from cpmh_backend.access import classify
from cpmh_backend.hashing import dhash, looks_blank, looks_partial, sha256_file
from cpmh_backend.intelligence import Block, PageObservation, WordBox, decide_capture
from cpmh_backend.security import validate_url

_SIGNALS = """
() => {
  const src = (el) => el.getAttribute("src") || "";
  const selectors = [
    ".g-recaptcha", "#g-recaptcha-response", ".h-captcha", ".cf-turnstile",
    "#challenge-form", ".cf-browser-verification", "#cf-challenge-running",
    "input[type='password']", "#captcha", ".captcha"
  ];
  return {
    title: document.title || "",
    text: document.body ? document.body.innerText.slice(0, 1500) : "",
    ready: document.readyState,
    iframes: Array.from(document.querySelectorAll("iframe")).map(src).filter(Boolean).slice(0, 20),
    scripts: Array.from(document.querySelectorAll("script")).map(src).filter(Boolean).slice(0, 30),
    markers: selectors.filter((selector) => document.querySelector(selector))
  };
}
"""

_EXTRACT = """
() => {
  const bodyText = document.body ? document.body.innerText.slice(0, 5000) : "";
  const counter = bodyText.match(/(?:p[áa]gina|page)?\\s*(\\d{1,4})\\s*(?:\\/|de|of)\\s*(\\d{1,4})/i);
  const nodes = Array.from(document.querySelectorAll("button, a, [role='button']"));
  let next = null;
  for (const el of nodes) {
    const label = ((el.getAttribute("aria-label") || "") + " " + (el.getAttribute("rel") || "")).toLowerCase();
    if (/(próxima página|proxima pagina|next page|^next$|rel)/.test(label) || el.getAttribute("rel") === "next") {
      next = el;
      break;
    }
  }
  return {
    title: document.title || "",
    counter: counter ? [Number(counter[1]), Number(counter[2])] : null,
    nextPresent: Boolean(next),
    nextDisabled: next ? Boolean(next.disabled || next.getAttribute("aria-disabled") === "true" || next.classList.contains("disabled")) : null,
    ready: document.readyState,
    scrollWidth: document.documentElement.scrollWidth,
    scrollHeight: document.documentElement.scrollHeight
  };
}
"""

_CLICK = """
() => {
  const nodes = Array.from(document.querySelectorAll("button, a, [role='button']"));
  for (const el of nodes) {
    const label = ((el.getAttribute("aria-label") || "") + " " + (el.getAttribute("rel") || "")).toLowerCase();
    const rel = el.getAttribute("rel");
    if (rel === "next" || /(próxima página|proxima pagina|next page)/.test(label)) {
      if (el.disabled || el.getAttribute("aria-disabled") === "true") return false;
      el.click();
      return true;
    }
  }
  return false;
}
"""

_DOM = """
() => {
  const root = document.documentElement;
  const pick = Array.from(document.querySelectorAll("h1,h2,h3,p,li,td,th,caption,figcaption,header,footer"));
  return {
    width: root.scrollWidth,
    height: root.scrollHeight,
    nodes: pick.slice(0, 400).map((el) => {
      const rect = el.getBoundingClientRect();
      return {
        tag: el.tagName,
        text: (el.innerText || "").trim().slice(0, 2000),
        x: rect.x + window.scrollX,
        y: rect.y + window.scrollY,
        w: rect.width,
        h: rect.height
      };
    })
  };
}
"""


def browser_snapshot(value) -> dict | None:
    """O navegador às vezes devolve nulo em vez do objeto da página."""
    return value if isinstance(value, dict) else None


def browser_status() -> dict:
    chrome = shutil.which("google-chrome") or shutil.which("google-chrome-stable") or shutil.which("chromium")
    try:
        import playwright  # noqa: F401

        imported = True
    except Exception:
        imported = False
    return {"playwright": imported, "chrome": bool(chrome), "chrome_path": chrome or ""}


def capture_html(
    url: str,
    out_dir: Path,
    *,
    allow_local: bool,
    max_pages: int,
    timeout: float,
) -> dict:
    validated = validate_url(url, allow_local=allow_local)
    status_info = browser_status()
    if not status_info["playwright"] or not status_info["chrome"]:
        raise RuntimeError("Chromium ou Playwright não está disponível para a captura HTML.")
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import TimeoutError as PlaywrightTimeout
    from playwright.sync_api import sync_playwright

    out_dir.mkdir(parents=True, exist_ok=True)
    observations: list[PageObservation] = []
    pages: list[dict] = []
    capture_status = "inconclusive"
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        try:
            context = browser.new_context(viewport={"width": 1280, "height": 1600}, device_scale_factor=1)
            page = context.new_page()

            def guard(route):
                try:
                    validate_url(route.request.url, allow_local=allow_local)
                except Exception:
                    route.abort()
                    return
                route.continue_()

            page.route("**/*", guard)
            started = time.perf_counter()
            try:
                response = page.goto(validated.url, wait_until="domcontentloaded", timeout=int(timeout * 1000))
            except PlaywrightTimeout:
                verdict = classify({"url": validated.url, "final_url": validated.url, "navigation_error": "network"})
                return {"status": "blocked", "pages": [], "final_url": validated.url, "access": verdict}
            except PlaywrightError:
                verdict = classify({"url": validated.url, "final_url": validated.url, "navigation_error": "browser"})
                return {"status": "blocked", "pages": [], "final_url": validated.url, "access": verdict}
            try:
                page.wait_for_load_state("networkidle", timeout=min(3000, int(timeout * 1000)))
            except PlaywrightTimeout:
                pass
            page.wait_for_timeout(250)
            observed = browser_snapshot(page.evaluate(_SIGNALS))
            if observed is None:
                verdict = classify({"url": validated.url, "final_url": page.url, "navigation_error": "browser"})
                return {"status": "blocked", "pages": [], "final_url": page.url, "access": verdict}
            verdict = classify(
                {
                    "url": validated.url,
                    "final_url": page.url,
                    "status": response.status if response is not None else 0,
                    "title": observed.get("title") or "",
                    "text": observed.get("text") or "",
                    "markers": observed.get("markers") or [],
                    "iframes": observed.get("iframes") or [],
                    "scripts": observed.get("scripts") or [],
                    "ready": observed.get("ready") or "",
                    "rendered": True,
                    "elapsed_ms": int((time.perf_counter() - started) * 1000),
                }
            )
            if verdict["state"] != "ACCESS_GRANTED":
                return {"status": "blocked", "pages": [], "final_url": page.url, "access": verdict}
            for index in range(max_pages):
                png = out_dir / f"capture-{index + 1:04d}.png"
                page.screenshot(path=str(png), full_page=True)
                info = browser_snapshot(page.evaluate(_EXTRACT)) or {}
                dom = browser_snapshot(page.evaluate(_DOM))
                image = Image.open(png)
                digest = sha256_file(png)
                perceptual = dhash(image)
                counter = info.get("counter") or [None, None]
                observation = PageObservation(
                    content_hash=digest,
                    phash=perceptual,
                    counter_current=counter[0],
                    counter_total=counter[1],
                    next_present=bool(info.get("nextPresent")),
                    next_disabled=info.get("nextDisabled"),
                    blank=looks_blank(image),
                    partial=looks_partial(image),
                )
                observations.append(observation)
                decision = decide_capture(observations, hit_max=index + 1 >= max_pages)
                pages.append(
                    {
                        "sequence": len(pages) + 1,
                        "path": str(png),
                        "sha256": digest,
                        "phash": perceptual,
                        "width": image.width,
                        "height": image.height,
                        "title": info.get("title") or "",
                        "blocks": _blocks_from_dom(dom, image.size),
                        "blank": observation.blank,
                        "partial": observation.partial,
                        "reported_number": str(counter[0] or ""),
                        "source_url": page.url,
                    }
                )
                image.close()
                if decision == "continue":
                    clicked = page.evaluate(_CLICK)
                    if not clicked:
                        # Botão seguinte desabilitado é evidência de fim. Clique que não acontece
                        # com o controle ainda ativo deixa a captura inconclusiva.
                        if info.get("nextDisabled") is True:
                            capture_status = "complete"
                        else:
                            capture_status = "inconclusive" if info.get("nextPresent") else "complete"
                        break
                    page.wait_for_timeout(400)
                    continue
                capture_status = "complete" if decision == "complete" else "inconclusive"
                break
            else:
                capture_status = "inconclusive"
        finally:
            browser.close()
    if pages and observations and observations[-1].content_hash == (observations[-2].content_hash if len(observations) > 1 else ""):
        # A última imagem repetida não entra como página nova.
        if len(pages) > 1 and pages[-1]["sha256"] == pages[-2]["sha256"]:
            Path(pages[-1]["path"]).unlink(missing_ok=True)
            pages.pop()
    return {"status": capture_status, "pages": pages, "final_url": validated.url}


def probe_html(url: str, *, allow_local: bool, timeout: float) -> dict:
    """Abre a URL só para classificar o acesso. Não extrai páginas."""
    validated = validate_url(url, allow_local=allow_local)
    status_info = browser_status()
    if not status_info["playwright"] or not status_info["chrome"]:
        return classify({"url": validated.url, "navigation_error": "browser"})
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import TimeoutError as PlaywrightTimeout
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        try:
            page = browser.new_context(viewport={"width": 1280, "height": 1600}).new_page()

            def guard(route):
                try:
                    validate_url(route.request.url, allow_local=allow_local)
                except Exception:
                    route.abort()
                    return
                route.continue_()

            page.route("**/*", guard)
            try:
                response = page.goto(validated.url, wait_until="domcontentloaded", timeout=int(timeout * 1000))
            except PlaywrightTimeout:
                return classify({"url": validated.url, "final_url": validated.url, "navigation_error": "network"})
            except PlaywrightError:
                return classify({"url": validated.url, "final_url": validated.url, "navigation_error": "browser"})
            try:
                page.wait_for_load_state("networkidle", timeout=min(3000, int(timeout * 1000)))
            except PlaywrightTimeout:
                pass
            page.wait_for_timeout(200)
            observed = browser_snapshot(page.evaluate(_SIGNALS))
            if observed is None:
                return classify({"url": validated.url, "final_url": page.url, "navigation_error": "browser"})
            return classify(
                {
                    "url": validated.url,
                    "final_url": page.url,
                    "status": response.status if response is not None else 0,
                    "title": observed.get("title") or "",
                    "text": observed.get("text") or "",
                    "markers": observed.get("markers") or [],
                    "iframes": observed.get("iframes") or [],
                    "scripts": observed.get("scripts") or [],
                    "ready": observed.get("ready") or "",
                    "rendered": True,
                }
            )
        finally:
            browser.close()


def _blocks_from_dom(dom: dict | None, image_size: tuple[int, int]) -> list[Block]:
    if not isinstance(dom, dict):
        return []
    width = dom.get("width") or image_size[0] or 1
    height = dom.get("height") or image_size[1] or 1
    scale_x = image_size[0] / width if width else 1
    scale_y = image_size[1] / height if height else 1
    tag_category = {
        "H1": "title",
        "H2": "subtitle",
        "H3": "subtitle",
        "P": "paragraph",
        "LI": "paragraph",
        "CAPTION": "caption",
        "FIGCAPTION": "caption",
        "HEADER": "header",
        "FOOTER": "footer",
        "TD": "table",
        "TH": "table",
    }
    blocks: list[Block] = []
    for node in dom.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        text = " ".join(str(node.get("text") or "").split())
        if not text:
            continue
        x = max(node.get("x") or 0, 0) * scale_x / image_size[0]
        y = max(node.get("y") or 0, 0) * scale_y / image_size[1]
        box_w = max(node.get("w") or 0, 1) * scale_x / image_size[0]
        box_h = max(node.get("h") or 0, 1) * scale_y / image_size[1]
        words = [WordBox(part, (x, y, box_w, box_h), 95.0) for part in text.split()]
        blocks.append(
            Block(
                text=text,
                bbox=(x, y, box_w, box_h),
                confidence=95.0,
                source="html_dom",
                font_size=box_h,
                category=tag_category.get(node.get("tag"), "paragraph"),
                level=1 if node.get("tag") == "H1" else (2 if node.get("tag") in {"H2", "H3"} else 0),
                words=words,
            )
        )
    return blocks
