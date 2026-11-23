from __future__ import annotations

import hashlib
import io
import os
import json
import re
import logging
import shutil
from html.parser import HTMLParser
from pathlib import Path

from PIL import Image, ImageDraw

import time

from cpmh_backend.access import classify, signals_from_html
from cpmh_backend.hashing import dhash, hamming, looks_blank, looks_partial, sha256_file
from cpmh_backend.intelligence import Block, PageObservation, WordBox, decide_capture
from cpmh_backend.security import validate_url
from cpmh_backend.services.lab_extension import MARCA_INTEGRACAO, lab_enabled_for, lab_note, open_capture_context, wait_until_unchallenged
from cpmh_backend.services.manual_captcha import focus_and_wait_ready, manual_note, open_browser_context, wait_for_manual_solve

logger = logging.getLogger("cpmh")

_SIGNALS = """
() => {
  const src = (el) => el.getAttribute("src") || "";
  const selectors = [
    ".g-recaptcha", "#g-recaptcha-response", ".h-captcha", ".cf-turnstile",
    "#challenge-form", ".cf-browser-verification", "#cf-challenge-running",
    "input[type='password']", "#captcha", ".captcha"
  ];
  return JSON.stringify({
    title: document.title || "",
    text: document.body ? document.body.innerText.slice(0, 1500) : "",
    ready: document.readyState,
    iframes: Array.from(document.querySelectorAll("iframe")).map(src).filter(Boolean).slice(0, 20),
    scripts: Array.from(document.querySelectorAll("script")).map(src).filter(Boolean).slice(0, 30),
    markers: selectors.filter((selector) => document.querySelector(selector))
  });
}
"""

_EXTRACT = """
() => {
  const bodyText = document.body ? document.body.innerText.slice(0, 5000) : "";
  const counters = Array.from(bodyText.matchAll(/(\\d{1,4})\\s*(?:\\/|de|of)\\s*(\\d{1,4})/gi)).map((m) => [Number(m[1]), Number(m[2])]);
  const counter = counters.length ? counters[0] : null;
  const nodes = Array.from(document.querySelectorAll("button, a, [role='button']"));
  let next = null;
  for (const el of nodes) {
    const label = ((el.getAttribute("aria-label") || "") + " " + (el.getAttribute("title") || "") + " " + (el.id || "") + " " + (el.getAttribute("rel") || "")).toLowerCase();
    if (el.id === "nextPageButton" || el.getAttribute("rel") === "next" || /(próxima página|proxima pagina|next page|下一页|^next$)/.test(label)) {
      next = el;
      break;
    }
  }
  return JSON.stringify({
    title: document.title || "",
    counter: counter,
    counters: counters,
    nextPresent: Boolean(next),
    nextDisabled: next ? Boolean(next.disabled || next.getAttribute("aria-disabled") === "true" || next.classList.contains("disabled")) : null,
    ready: document.readyState,
    scrollWidth: document.documentElement.scrollWidth,
    scrollHeight: document.documentElement.scrollHeight
  });
}
"""

_CLICK = """
() => {
  const nodes = Array.from(document.querySelectorAll("button, a, [role='button']"));
  for (const el of nodes) {
    const label = ((el.getAttribute("aria-label") || "") + " " + (el.getAttribute("title") || "") + " " + (el.id || "") + " " + (el.getAttribute("rel") || "")).toLowerCase();
    const rel = el.getAttribute("rel");
    if (el.id === "nextPageButton" || rel === "next" || /(próxima página|proxima pagina|next page|下一页)/.test(label)) {
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
  return JSON.stringify({
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
  });
}
"""


_CHALLENGE_STATES = {"CAPTCHA_DETECTED", "HUMAN_VERIFICATION_REQUIRED"}


def _challenge_verdict(page) -> dict | None:
    """Veredito atual se a página ainda pede verificação humana; None se não pede."""
    observed = evaluate_page(page, _SIGNALS)
    if observed is None:
        return None
    verdict = classify(
        {
            "url": page.url,
            "final_url": page.url,
            "title": observed.get("title") or "",
            "text": observed.get("text") or "",
            "markers": observed.get("markers") or [],
            "iframes": observed.get("iframes") or [],
            "scripts": observed.get("scripts") or [],
            "ready": observed.get("ready") or "",
            "rendered": True,
        }
    )
    return verdict if verdict["state"] in _CHALLENGE_STATES else None


def _lab_wait(page, url: str) -> dict:
    return wait_until_unchallenged(page, url, _challenge_verdict)


def _resolution_wait(page, url: str) -> dict:
    """Tenta a espera do modo laboratório; se ela não se aplicar, tenta a espera manual."""
    info = _lab_wait(page, url)
    if info:
        return info
    return wait_for_manual_solve(page, _challenge_verdict)


def _with_lab_note(verdict: dict, info: dict) -> dict:
    note = lab_note(info) or manual_note(info)
    if note and verdict.get("state") in _CHALLENGE_STATES:
        verdict.setdefault("evidence", []).append(note)
    return verdict


def _post_solve_timeout_ms() -> int:
    """Tempo para esperar o conteúdo real carregar depois de resolver um desafio.

    Independente do tempo limite por página (CPMH timeout_seconds, em geral 30s): muitos visores
    de documento (barra de progresso, leitor tipo flipbook) continuam fazendo requisições em segundo
    plano por mais tempo que isso, então "networkidle" nunca dispara dentro do timeout curto da página.
    Configurável por CPMH_POST_SOLVE_TIMEOUT_MS (padrão 20000).
    """
    try:
        return max(1000, int(os.environ.get("CPMH_POST_SOLVE_TIMEOUT_MS", "45000")))
    except ValueError:
        return 45000


def _post_solve_settle_ms() -> int:
    """Pausa fixa adicional depois do networkidle, para visores que nunca ficam realmente ociosos
    (polling contínuo). Configurável por CPMH_POST_SOLVE_SETTLE_MS (padrão 3000)."""
    try:
        return max(0, int(os.environ.get("CPMH_POST_SOLVE_SETTLE_MS", "3000")))
    except ValueError:
        return 3000


def _content_fingerprint(page) -> int:
    """Tamanho aproximado do conteúdo visível: cresce enquanto o visor ainda está carregando páginas."""
    try:
        return int(page.evaluate("document.body ? document.body.innerText.length + document.images.length * 97 : 0"))
    except Exception:
        return -1


def _wait_until_content_stable(page, max_ms: int, interval_ms: int = 1000, stable_rounds: int = 3) -> None:
    """Espera enquanto o conteúdo da página ainda está crescendo (visor carregando progressivamente),
    e só segue depois que ele parar de mudar por `stable_rounds` checagens seguidas, ou ao estourar
    `max_ms`. Mais confiável que um tempo fixo para visores com barra de progresso ou carregamento
    por partes, onde a rede nunca fica totalmente ociosa.
    """
    deadline = time.perf_counter() + max_ms / 1000
    previous = _content_fingerprint(page)
    stable = 0
    while time.perf_counter() < deadline:
        page.wait_for_timeout(interval_ms)
        current = _content_fingerprint(page)
        if current == previous and current >= 0:
            stable += 1
            if stable >= stable_rounds:
                return
        else:
            stable = 0
        previous = current


def _wait_after_resolution(page, lab_info: dict, timeout_ms: int) -> None:
    """Depois que um desafio é resolvido (laboratório ou manual), a página costuma navegar ou
    recarregar para o conteúdo real. Espera esse carregamento terminar antes de começar a capturar,
    em vez de uma pausa fixa curta, que gerava prints repetidos de uma página ainda em branco.
    """
    if not (lab_info.get("resolved") or lab_info.get("cleared")):
        return
    budget = max(timeout_ms, _post_solve_timeout_ms())
    try:
        page.wait_for_load_state("load", timeout=budget)
    except Exception:
        pass
    try:
        page.wait_for_load_state("networkidle", timeout=min(budget, 8000))
    except Exception:
        pass  # visor pode nunca ficar ocioso (polling contínuo); a checagem de conteúdo abaixo cobre isso
    _wait_until_content_stable(page, budget)
    settle = _post_solve_settle_ms()
    if settle:
        page.wait_for_timeout(settle)


def _allow_route(route, allow_local: bool) -> None:
    try:
        request = getattr(route, "request", None)
        validate_url(getattr(request, "url", "") or "", allow_local=allow_local)
        route.continue_()
    except Exception:
        try:
            route.abort()
        except Exception:
            return


def browser_snapshot(value) -> dict | None:
    """O navegador às vezes devolve nulo em vez do objeto da página."""
    return value if isinstance(value, dict) else None


def evaluate_page(page, script: str) -> dict | None:
    """Lê um objeto calculado na página.

    Há páginas que definem `then` em Object.prototype. O Playwright trata
    qualquer objeto devolvido como Promise e recebe undefined. Uma string
    JSON não entra nesse caminho, então o objeto nasce aqui no Python.
    """
    value = page.evaluate(script)
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return None
    return value if isinstance(value, dict) else None


def find_browser() -> tuple[str, str]:
    """Acha um navegador Chromium instalado: (caminho, nome). Vazio quando não há.

    No Windows o Chrome é chrome.exe em Program Files e não está no PATH; o Edge (msedge.exe) já vem
    com o sistema e é Chromium. Procurar só 'google-chrome' no PATH nunca o encontrava.
    """
    override = os.environ.get("CPMH_CHROME_PATH", "").strip()
    if override and Path(override).is_file():
        return override, "navegador indicado em CPMH_CHROME_PATH"
    for name, label in (
        ("google-chrome", "Google Chrome"),
        ("google-chrome-stable", "Google Chrome"),
        ("chrome", "Google Chrome"),
        ("chrome.exe", "Google Chrome"),
        ("chromium", "Chromium"),
        ("chromium-browser", "Chromium"),
        ("msedge", "Microsoft Edge"),
        ("msedge.exe", "Microsoft Edge"),
    ):
        found = shutil.which(name)
        if found:
            return found, label
    candidates: list[tuple[Path, str]] = []
    for variable in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
        base = os.environ.get(variable)
        if base:
            candidates.append((Path(base) / "Google" / "Chrome" / "Application" / "chrome.exe", "Google Chrome"))
    for variable in ("PROGRAMFILES(X86)", "PROGRAMFILES", "LOCALAPPDATA"):
        base = os.environ.get(variable)
        if base:
            candidates.append((Path(base) / "Microsoft" / "Edge" / "Application" / "msedge.exe", "Microsoft Edge"))
    candidates += [
        (Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"), "Google Chrome"),
        (Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"), "Microsoft Edge"),
    ]
    for path, label in candidates:
        if path.is_file():
            return str(path), label
    return "", ""


def launch_browser(playwright):
    """Abre o navegador encontrado por find_browser. Levanta RuntimeError se não houver."""
    path, _label = find_browser()
    if not path:
        raise RuntimeError(_NO_BROWSER_MESSAGE)
    return playwright.chromium.launch(executable_path=path, headless=True)


_NO_BROWSER_MESSAGE = (
    "Nenhum Chrome, Chromium ou Edge foi encontrado neste computador. Instale o Google Chrome "
    "ou indique o caminho do navegador na variável CPMH_CHROME_PATH."
)


def browser_status() -> dict:
    chrome, label = find_browser()
    try:
        import playwright  # noqa: F401

        imported = True
    except Exception:
        imported = False
    return {"playwright": imported, "chrome": bool(chrome), "chrome_path": chrome or "", "browser_name": label}


def browser_unavailable_reason(info: dict) -> str:
    """Diz exatamente o que falta, em vez de 'Chromium ou Playwright'."""
    missing = []
    if not info.get("playwright"):
        missing.append("o pacote Python 'playwright' (rode: pip install -r requirements.txt)")
    if not info.get("chrome"):
        missing.append("um navegador Chrome, Chromium ou Edge instalado (ou CPMH_CHROME_PATH)")
    return "Falta " + " e ".join(missing) + "." if missing else ""


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
        raise RuntimeError(browser_unavailable_reason(status_info))

    out_dir.mkdir(parents=True, exist_ok=True)
    observations: list[PageObservation] = []
    pages: list[dict] = []
    try:
        return _capture_with_browser(
            validated.url,
            out_dir,
            allow_local=allow_local,
            max_pages=max_pages,
            timeout=timeout,
            observations=observations,
            pages=pages,
        )
    except Exception as exc:
        logger.exception("captura html")
        return {
            "status": "browser_failed",
            "pages": pages,
            "final_url": validated.url,
            "error": f"{type(exc).__name__}: {exc}",
        }


def _visible_canvas(page):
    """A folha desenhada num canvas, a que está mais dentro da janela."""
    raw = page.evaluate(
        """() => {
      const viewHeight = window.innerHeight || 800;
      const nodes = Array.from(document.querySelectorAll('canvas'));
      let best = null;
      nodes.forEach((canvas, index) => {
        const rect = canvas.getBoundingClientRect();
        if (rect.width < 400 || rect.height < 480) return;
        const visible = Math.min(rect.bottom, viewHeight) - Math.max(rect.top, 0);
        const score = visible > 0 ? visible : rect.width;
        if (!best || score > best.score) best = {index, score};
      });
      return best ? JSON.stringify(best) : '';
    }"""
    )
    if not isinstance(raw, str) or not raw:
        return None
    try:
        chosen = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return page.locator("canvas").nth(int(chosen["index"]))


def _canvas_image(locator):
    try:
        payload = locator.screenshot(type="png", timeout=5000)
    except Exception:
        return None
    return Image.open(io.BytesIO(payload))


def _canvas_digest(locator) -> str:
    try:
        payload = locator.screenshot(type="png", timeout=5000)
    except Exception:
        return ""
    return hashlib.sha256(payload).hexdigest()


def _wait_for_painted_canvas(page, timeout: float) -> bool:
    """Espera o visor desenhar a folha. Sem canvas grande, segue na hora."""
    if _visible_canvas(page) is None:
        return False
    deadline = time.perf_counter() + min(max(timeout, 1.0), 20.0)
    while True:
        locator = _visible_canvas(page)
        image = _canvas_image(locator) if locator is not None else None
        if image is not None and not looks_blank(image):
            image.close()
            return True
        if image is not None:
            image.close()
        if time.perf_counter() >= deadline:
            return False
        page.wait_for_timeout(400)



_INTERFACE_WORDS = re.compile(
    r"(登录|注册|下载|上传|搜索|搜本文档|首页|帮助中心|关于我们|联系我们|版权所有|客服|会员|设置|全屏|缩略图|"
    r"log ?in|sign ?(?:in|up)|download|upload|search|cookies?|privacy|terms of|menu|subscribe|share|fullscreen|"
    r"entrar|cadastr|baixar|pesquisar|pol[ií]tica de|compartilhar|tela cheia)",
    re.IGNORECASE,
)


def pick_counter(candidates) -> list[int | None]:
    """Escolhe o contador de páginas entre vários 'N / M' da tela.

    Um visualizador tem mais de um: o do campo de busca ('1 / 1') e o das páginas ('3 / 16').
    O total do documento é o maior total plausível, então o contador da busca não encerra a captura.
    """
    valid = [
        (int(item[0]), int(item[1]))
        for item in (candidates or [])
        if isinstance(item, (list, tuple)) and len(item) >= 2 and 0 < int(item[1]) and 0 <= int(item[0]) <= int(item[1])
    ]
    if not valid:
        return [None, None]
    current, total = max(valid, key=lambda pair: (pair[1], pair[0]))
    return [current, total]


def looks_like_interface_text(blocks) -> bool:
    """Texto que é só a interface do site (menus, botões, rodapé), não o documento.

    Um documento tem frases. Uma interface tem rótulos curtos e palavras como 'baixar', 'login', 下载.
    """
    texts = [" ".join(str(getattr(block, "text", block)).split()) for block in blocks]
    texts = [text for text in texts if text]
    if len(texts) < 6:
        return False

    def is_sentence(text: str) -> bool:
        cjk = len(re.findall(r"[\u4e00-\u9fff]", text))
        if cjk:
            return cjk >= 25
        return len(text.split()) >= 8 and len(text) >= 45

    sentences = sum(1 for text in texts if is_sentence(text))
    short = sum(1 for text in texts if len(text) <= 14 or len(text.split()) <= 2)
    marked = sum(1 for text in texts if _INTERFACE_WORDS.search(text))
    return sentences / len(texts) < 0.08 and (short / len(texts) >= 0.6 or marked / len(texts) >= 0.25)


def group_page_surfaces(items: list[dict]) -> list[dict]:
    """Das imagens e canvas da tela, fica com as que têm cara de página: retrato e tamanho parecido."""
    candidates = [
        item
        for item in items
        if item.get("w", 0) >= 400 and item.get("h", 0) >= 480 and 1.0 <= item["h"] / max(item["w"], 1) <= 1.9
    ]
    if len(candidates) < 2:
        return []
    biggest = max(item["w"] * item["h"] for item in candidates)
    pages = [item for item in candidates if item["w"] * item["h"] >= biggest * 0.7]
    pages.sort(key=lambda item: (item.get("top", 0), item.get("i", 0)))
    return pages if len(pages) >= 2 else []

_SURFACES = """
() => {
  const items = [];
  document.querySelectorAll("img, canvas").forEach((el, i) => {
    const rect = el.getBoundingClientRect();
    items.push({i: i, tag: el.tagName, w: Math.round(rect.width), h: Math.round(rect.height), top: rect.top + window.scrollY});
  });
  return JSON.stringify({items: items});
}
"""


def _capture_stacked_pages(page, out_dir: Path, *, max_pages: int, timeout: float, pages: list[dict]) -> bool:
    """Visualizador que empilha as páginas como imagens: captura cada uma, na ordem da tela."""
    info = evaluate_page(page, _SURFACES) or {}
    surfaces = group_page_surfaces(info.get("items") or [])
    if not surfaces:
        return False
    logger.info("visor empilhado: %s folhas na tela", len(surfaces))
    for surface in surfaces[:max_pages]:
        locator = page.locator("img, canvas").nth(int(surface["i"]))
        try:
            locator.scroll_into_view_if_needed(timeout=5000)
        except Exception:
            pass
        png = out_dir / f"capture-{len(pages) + 1:04d}.png"
        image = None
        deadline = time.perf_counter() + min(8.0, max(timeout, 1.0))
        while True:
            try:
                ready = locator.evaluate("el => el.tagName === 'IMG' ? (el.complete && el.naturalWidth > 0) : true")
                if ready:
                    locator.screenshot(path=str(png), timeout=8000)
                    image = Image.open(png)
                    if not looks_blank(image):
                        break
                    image.close()
                    image = None
            except Exception:
                image = None
            if time.perf_counter() >= deadline:
                break
            page.wait_for_timeout(400)
        if image is None:
            continue
        digest = sha256_file(png)
        pages.append(
            {
                "sequence": len(pages) + 1,
                "path": str(png),
                "sha256": digest,
                "phash": dhash(image),
                "width": image.width,
                "height": image.height,
                "title": "",
                "blocks": [],
                "blank": False,
                "partial": False,
                "reported_number": str(len(pages) + 1),
                "source_url": page.url,
            }
        )
        image.close()
    return bool(pages)


def _capture_with_browser(url, out_dir, *, allow_local, max_pages, timeout, observations, pages) -> dict:
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import TimeoutError as PlaywrightTimeout
    from playwright.sync_api import sync_playwright

    capture_status = "inconclusive"
    with sync_playwright() as playwright:
        context, close_context = open_capture_context(
            playwright, url, launch_browser=launch_browser, viewport={"width": 1280, "height": 1600}
        ) if lab_enabled_for(url) is not None else open_browser_context(
            playwright, launch_browser=launch_browser, viewport={"width": 1280, "height": 1600}
        )
        try:
            context.set_default_timeout(int(timeout * 1000))
            context.set_default_navigation_timeout(int(timeout * 1000))
            page = context.new_page()

            page.route("**/*", lambda route: _allow_route(route, allow_local))
            started = time.perf_counter()
            try:
                response = page.goto(url, wait_until="domcontentloaded", timeout=int(timeout * 1000))
            except PlaywrightTimeout:
                verdict = classify({"url": url, "final_url": url, "navigation_error": "network"})
                return {"status": "blocked", "pages": [], "final_url": url, "access": verdict}
            except PlaywrightError:
                verdict = classify({"url": url, "final_url": url, "navigation_error": "browser"})
                return {"status": "blocked", "pages": [], "final_url": url, "access": verdict}
            try:
                page.wait_for_load_state("networkidle", timeout=min(3000, int(timeout * 1000)))
            except PlaywrightTimeout:
                pass
            focus_and_wait_ready(page, int(timeout * 1000))  # modo manual: seleciona a aba e espera carregar
            lab_info = _resolution_wait(page, url)  # modo laboratório (extensão) ou manual (janela)
            _wait_after_resolution(page, lab_info, int(timeout * 1000))
            page.wait_for_timeout(250)
            observed = evaluate_page(page, _SIGNALS)
            if observed is None:
                verdict = classify({"url": url, "final_url": page.url, "navigation_error": "browser"})
                return {"status": "blocked", "pages": [], "final_url": page.url, "access": verdict}
            verdict = classify(
                {
                    "url": url,
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
                return {"status": "blocked", "pages": [], "final_url": page.url, "access": _with_lab_note(verdict, lab_info)}
            if _capture_stacked_pages(page, out_dir, max_pages=max_pages, timeout=timeout, pages=pages):
                counter_info = evaluate_page(page, _EXTRACT) or {}
                total = pick_counter(counter_info.get("counters") or [counter_info.get("counter")])[1]
                complete = total is None or len(pages) >= total
                return {"status": "complete" if complete else "inconclusive", "pages": pages, "final_url": url, "expected_pages": total}
            canvas_pages = _wait_for_painted_canvas(page, timeout)
            if canvas_pages:
                logger.info("visor desenhou a folha; a captura usa o canvas")
            seen_pages: set[str] = set()
            for index in range(max_pages):
                png = out_dir / f"capture-{index + 1:04d}.png"
                surface = _visible_canvas(page) if canvas_pages else None
                if surface is not None:
                    surface.screenshot(path=str(png), timeout=8000)
                    dom = None
                else:
                    page.screenshot(path=str(png), full_page=True)
                    dom = evaluate_page(page, _DOM)
                info = evaluate_page(page, _EXTRACT) or {}
                image = Image.open(png)
                digest = sha256_file(png)
                perceptual = dhash(image)
                raw_counter = pick_counter(info.get("counters") or [info.get("counter")])
                counter = list(raw_counter) if isinstance(raw_counter, (list, tuple)) and len(raw_counter) >= 2 else [None, None]
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
                seen_pages.add(digest)
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
                        "blocks": _dom_blocks_or_empty(dom, image.size),
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
                    previous = digest
                    page.wait_for_timeout(400)
                    if canvas_pages:
                        changed_to = ""
                        deadline = time.perf_counter() + min(8.0, max(timeout, 1.0))
                        while time.perf_counter() < deadline:
                            locator = _visible_canvas(page)
                            current = _canvas_digest(locator) if locator is not None else ""
                            if current and current != previous:
                                changed_to = current
                                break
                            page.wait_for_timeout(400)
                        if not changed_to or changed_to in seen_pages:
                            capture_status = "complete"
                            break
                    continue
                capture_status = "complete" if decision == "complete" else "inconclusive"
                break
            else:
                capture_status = "inconclusive"
        finally:
            close_context()
    _trim_trailing_duplicates(pages, observations)
    return {"status": capture_status, "pages": pages, "final_url": url}


def _trim_trailing_duplicates(pages: list, observations: list) -> None:
    """Remove páginas repetidas no final da captura: um 'próximo' que não mudou a página de verdade
    gera duas capturas quase idênticas (mesmo texto, pixels levemente diferentes por compressão ou
    anti-aliasing). O hash exato (sha256) só pega repetição byte a byte; o hash perceptual (phash),
    com pequena tolerância, pega essas quase-duplicatas também. Remove enquanto o final repetir,
    não só o último par.
    """
    while len(pages) > 1 and len(observations) > 1:
        last, prev = observations[-1], observations[-2]
        same_exact = last.content_hash == prev.content_hash
        same_visual = hamming(pages[-1]["phash"], pages[-2]["phash"]) <= 4
        if not (same_exact or same_visual):
            break
        Path(pages[-1]["path"]).unlink(missing_ok=True)
        pages.pop()
        observations.pop()


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
        context, close_context = open_capture_context(
            playwright, validated.url, launch_browser=launch_browser, viewport={"width": 1280, "height": 1600}
        ) if lab_enabled_for(validated.url) is not None else open_browser_context(
            playwright, launch_browser=launch_browser, viewport={"width": 1280, "height": 1600}
        )
        try:
            page = context.new_page()

            page.route("**/*", lambda route: _allow_route(route, allow_local))
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
            focus_and_wait_ready(page, int(timeout * 1000))  # modo manual: seleciona a aba e espera carregar
            lab_info = _resolution_wait(page, validated.url)  # modo laboratório ou manual
            _wait_after_resolution(page, lab_info, int(timeout * 1000))
            page.wait_for_timeout(200)
            observed = evaluate_page(page, _SIGNALS)
            if observed is None:
                return classify({"url": validated.url, "final_url": page.url, "navigation_error": "browser"})
            return _with_lab_note(classify(
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
            ), lab_info)
        finally:
            close_context()


class _VisibleHtml(HTMLParser):
    _SKIP = {"script", "style", "noscript", "template", "svg"}
    _BREAK = {"p", "div", "h1", "h2", "h3", "h4", "li", "tr", "section", "article", "blockquote", "figcaption", "pre", "br"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[tuple[str, str]] = []
        self._skip = 0
        self._buffer: list[str] = []

    def handle_starttag(self, tag, attrs):
        name = tag.lower()
        if name in self._SKIP:
            self._skip += 1
        if name == "br":
            self._flush("p")

    def handle_endtag(self, tag):
        name = tag.lower()
        if name in self._SKIP and self._skip:
            self._skip -= 1
            return
        if name in self._BREAK:
            self._flush(name)

    def handle_data(self, data):
        if self._skip or not data:
            return
        self._buffer.append(data)

    def close(self):
        super().close()
        self._flush("p")

    def _flush(self, tag: str) -> None:
        text = " ".join("".join(self._buffer).split())
        self._buffer = []
        if text:
            self.parts.append((tag, text[:500]))


def pages_from_downloaded_html(html: str, url: str, out_dir: Path) -> dict:
    """Extrai o texto do HTML já baixado quando o navegador não devolve a página."""
    verdict = classify(signals_from_html(url, url, 200, html or ""))
    if verdict.get("state") != "ACCESS_GRANTED":
        return {"status": "blocked", "pages": [], "access": verdict, "final_url": url}
    parser = _VisibleHtml()
    parser.feed(html or "")
    parser.close()
    parts = parser.parts[:180]
    if not parts:
        return {"status": "empty", "pages": [], "final_url": url}
    if looks_like_interface_text([text for _tag, text in parts]):
        # Visualizador que desenha as páginas em imagem: o HTML só traz menus e botões.
        return {"status": "interface_only", "pages": [], "final_url": url}
    out_dir.mkdir(parents=True, exist_ok=True)
    width = 1100
    line = 26
    height = 48 + line * len(parts)
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    categories = {"h1": "title", "h2": "subtitle", "h3": "subtitle", "h4": "subtitle"}
    blocks: list[Block] = []
    top = 24
    for tag, text in parts:
        draw.text((36, top), text[:170], fill=(20, 20, 20))
        x = 36 / width
        y = top / height
        box_w = 0.9
        box_h = 18 / height
        blocks.append(
            Block(
                text=text,
                bbox=(x, y, box_w, box_h),
                confidence=90.0,
                source="html_text",
                font_size=box_h,
                category=categories.get(tag, "paragraph"),
                level=1 if tag == "h1" else (2 if tag in {"h2", "h3", "h4"} else 0),
                words=[WordBox(part, (x, y, box_w, box_h), 90.0) for part in text.split()],
            )
        )
        top += line
    path = out_dir / "capture-0001.png"
    image.save(path, format="PNG")
    return {
        "status": "complete",
        "pages": [
            {
                "sequence": 1,
                "path": str(path),
                "width": width,
                "height": height,
                "title": next((text for tag, text in parts if tag == "h1"), ""),
                "blocks": blocks,
                "blank": False,
                "partial": False,
                "reported_number": "",
                "source_url": url,
                "source": "html_text",
            }
        ],
        "final_url": url,
        "source": "html_text",
    }


def _dom_blocks_or_empty(dom, image_size) -> list[Block]:
    """Texto do DOM só vale se for o documento. Se for menu e botão, a captura é lida por OCR."""
    blocks = _blocks_from_dom(dom, image_size)
    if looks_like_interface_text(blocks):
        logger.info("texto do DOM parece interface do site; a página capturada vai para o OCR")
        return []
    return blocks


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