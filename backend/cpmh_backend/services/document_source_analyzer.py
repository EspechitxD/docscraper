"""DocumentSourceAnalyzer: de onde vem o conteúdo documental de uma página web.

Recebe uma observação (o que o navegador viu: texto, iframes, canvas, imagens, respostas de rede)
e devolve um diagnóstico. Não acessa a rede e não contorna nada: só interpreta o que foi observado.

Regra do módulo: ausência de texto HTML não é ausência de documento, e metadado do site
("16 páginas") nunca vira página processada.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from cpmh_backend.access import classify, signals_from_html
from cpmh_backend.services.capture import _INTERFACE_WORDS, group_page_surfaces

# Estados do diagnóstico (seção 6 do prompt).
STATES = (
    "html_document",
    "pdf_document",
    "pdf_viewer_detected",
    "image_document",
    "canvas_document",
    "ocr_required",
    "authentication_required",
    "captcha_required",
    "access_restricted",
    "interface_only",
    "partial_document",
    "document_recovered",
    "processing_failed",
)

_PDFJS_MARKERS = ("pdf.js", "pdfjs", "pdf.worker", "pdfviewer", "/web/viewer.html", "pdfjs-dist")
_PAYWALL = re.compile(
    r"(积分|付费|开通会员|VIP用户|购买|下载本文需要|全文阅读已结束|paywall|subscribe to (?:read|download)|"
    r"assinatura|pagamento|assine para|payment required|purchase)",
    re.IGNORECASE,
)
_LOGIN_WALL = re.compile(r"(请先登录|登录后|sign in to (?:view|read|download)|faça login para|entre para (?:ver|ler|baixar))", re.IGNORECASE)
_FOOTER = re.compile(r"(版权|备案|©|copyright|all rights reserved|direitos reservados)", re.IGNORECASE)
_EXPORT_CONTROL = re.compile(r"(打印|导出|print|export|imprimir|exportar)", re.IGNORECASE)
_DOWNLOAD_CONTROL = re.compile(r"(下载|download|baixar)", re.IGNORECASE)

_REPORTED = (
    re.compile(r"(?:页数|pages?|páginas?)\s*[::=]?\s*(\d{1,5})", re.IGNORECASE),
    re.compile(r"og:document:page[^>]*content=[\"'](\d{1,5})", re.IGNORECASE),
)


def reported_pages_from_text(text: str) -> int | None:
    """Número de páginas que o próprio site declara. É metadado: nada foi processado."""
    for pattern in _REPORTED:
        match = pattern.search(text or "")
        if match:
            return int(match.group(1))
    totals = [int(total) for _cur, total in re.findall(r"(\d{1,4})\s*/\s*(\d{1,4})", text or "") if int(total) > 1]
    return max(totals) if totals else None


def split_interface_text(blocks: list[str]) -> tuple[list[str], list[str]]:
    """Separa blocos de texto em (documento, interface)."""
    document: list[str] = []
    interface: list[str] = []
    for raw in blocks:
        text = " ".join(str(raw).split())
        if not text:
            continue
        cjk = len(re.findall(r"[\u4e00-\u9fff]", text))
        sentence = cjk >= 25 or (not cjk and len(text.split()) >= 8 and len(text) >= 45)
        short = len(text) <= 14 or len(text.split()) <= 2
        marked = bool(_INTERFACE_WORDS.search(text) or _PAYWALL.search(text) or _FOOTER.search(text))
        alpha_words = [word for word in text.split() if len(re.sub(r"[^A-Za-zÀ-ÿ]", "", word)) >= 2]
        proseish = sentence or (not cjk and (len(alpha_words) >= 5 or text.endswith((".", ";", ":"))))
        if proseish and not marked:
            document.append(text)
        else:
            interface.append(text)
    return document, interface


def _is_pdf_response(item: dict) -> bool:
    return "pdf" in str(item.get("content_type", "")).lower() and 200 <= int(item.get("status") or 0) < 300


def _blob(observation: dict) -> str:
    parts = [
        " ".join(observation.get("scripts") or []),
        " ".join(item.get("src", "") for item in observation.get("iframes") or []),
        " ".join(item.get("url", "") for item in observation.get("responses") or []),
        str(observation.get("html_head") or ""),
    ]
    return " ".join(parts).lower()


def analyze_source(observation: dict) -> dict:
    """Interpreta uma observação do navegador. Devolve o diagnóstico completo."""
    url = str(observation.get("url") or "")
    final_url = str(observation.get("final_url") or url)
    visible = str(observation.get("visible_text") or "")
    blocks = observation.get("text_blocks") or [line for line in visible.splitlines() if line.strip()]
    document_blocks, interface_blocks = split_interface_text(blocks)
    document_chars = sum(len(text) for text in document_blocks)
    interface_chars = sum(len(text) for text in interface_blocks)
    evidence: list[str] = []
    flags: list[str] = []

    # Restrições: CAPTCHA, autenticação e controle de acesso. Só classificamos; nunca resolvemos.
    verdict = classify(
        signals_from_html(url, final_url, int(observation.get("status") or 200), str(observation.get("html_head") or visible))
    )
    verdict_state = verdict.get("state", "ACCESS_GRANTED")
    restrictions: list[str] = []
    if verdict_state in {"CAPTCHA_DETECTED", "HUMAN_VERIFICATION_REQUIRED"}:
        restrictions.append("captcha")
    if verdict_state in {"AUTHENTICATION_REQUIRED", "SESSION_EXPIRED"} or _LOGIN_WALL.search(visible):
        restrictions.append("authentication")
    if verdict_state in {"ACCESS_DENIED", "RATE_LIMITED"}:
        restrictions.append("access_denied")
    if _PAYWALL.search(visible):
        restrictions.append("payment")
    if restrictions:
        evidence.append("restrições: " + ", ".join(restrictions))

    # Fontes documentais.
    responses = observation.get("responses") or []
    pdf_accessible = sorted({item["url"] for item in responses if _is_pdf_response(item)})
    linked = list(observation.get("links") or [])
    linked += [item.get("src", "") for item in observation.get("iframes") or [] if ".pdf" in item.get("src", "").lower()]
    linked += [item.get("src", "") for item in observation.get("embeds") or [] if ".pdf" in item.get("src", "").lower() or "pdf" in str(item.get("type", "")).lower()]
    if urlsplit(final_url).path.lower().endswith(".pdf") and 200 <= int(observation.get("status") or 0) < 300:
        pdf_accessible.append(final_url)
    pdf_linked = sorted({href for href in linked if href and href not in pdf_accessible})
    blob = _blob(observation)
    pdfjs = bool(observation.get("has_pdfjs_global")) or any(marker in blob for marker in _PDFJS_MARKERS)
    text_layer_chars = int(observation.get("text_layer_chars") or 0)

    canvases = [
        {"w": int(c.get("w", 0)), "h": int(c.get("h", 0))}
        for c in observation.get("canvases") or []
        if int(c.get("w", 0)) >= 400 and int(c.get("h", 0)) >= 480
    ]
    surfaces = group_page_surfaces(
        [
            {"i": i, "w": int(img.get("w", 0)), "h": int(img.get("h", 0)), "top": int(img.get("top", 0)), "src": img.get("src", "")}
            for i, img in enumerate(observation.get("images") or [])
            if int(img.get("nw", img.get("w", 0)) or 0) > 0
        ]
        + [{"i": 10_000 + i, "w": c["w"], "h": c["h"], "top": i} for i, c in enumerate(canvases) if len(canvases) >= 2]
    )
    page_images = [item for item in surfaces if item["i"] < 10_000]
    reported = observation.get("reported_pages")
    if reported is None:
        reported = reported_pages_from_text(visible + " " + str(observation.get("html_head") or ""))

    # Tipo de visualizador e acessibilidade, na ordem de confiança.
    viewer = "none"
    accessible_pages: int | None = None
    if pdf_accessible:
        viewer = "pdf_direct"
        evidence.append(f"PDF acessível por resposta de rede: {len(pdf_accessible)}")
    elif pdfjs:
        viewer = "pdfjs"
        evidence.append("marcadores de PDF.js na página")
    elif page_images:
        viewer = "image_pages"
        accessible_pages = len(page_images)
        evidence.append(f"{len(page_images)} imagens com formato de página")
    elif canvases:
        viewer = "canvas"
        accessible_pages = len(canvases)
        evidence.append(f"{len(canvases)} canvas com formato de página")
    elif document_chars >= 400:
        viewer = "html"
    if observation.get("iframes"):
        evidence.append(f"iframes: {len(observation['iframes'])}")
    if len(canvases) == 1 and viewer == "image_pages":
        flags.append("canvas_extra")

    # Estado principal.
    controls = " | ".join(observation.get("controls") or [])
    export_available = bool(_EXPORT_CONTROL.search(controls))
    download_control = bool(_DOWNLOAD_CONTROL.search(controls))
    if "captcha" in restrictions:
        primary = "captcha_required"
    elif "authentication" in restrictions and viewer in {"none", "html"} and document_chars < 400:
        primary = "authentication_required"
    elif viewer == "pdf_direct":
        primary = "pdf_document"
    elif viewer == "pdfjs":
        primary = "pdf_viewer_detected"
    elif viewer == "html":
        primary = "html_document"
    elif viewer == "image_pages":
        primary = "image_document"
    elif viewer == "canvas":
        primary = "canvas_document"
    elif restrictions:
        primary = "access_restricted"
    else:
        primary = "interface_only"
    if viewer in {"image_pages", "canvas"}:
        flags.append("ocr_required")
    if "payment" in restrictions or "access_denied" in restrictions:
        flags.append("access_restricted")
    if reported and accessible_pages is not None and accessible_pages < int(reported):
        flags.append("partial_document")
    if primary == "html_document" and interface_chars > document_chars * 2:
        evidence.append("texto de interface maior que o documental")

    strategy = _strategy(primary, viewer, restrictions, export_available, download_control, text_layer_chars)
    conclusive = primary != "interface_only" or bool(restrictions)
    return {
        "url": url,
        "final_url": final_url,
        "primary_state": primary,
        "states": [primary] + [flag for flag in flags if flag != primary],
        "viewer_type": viewer,
        "restrictions": restrictions,
        "evidence": evidence,
        "resources": {
            "pdf_accessible": pdf_accessible,
            "pdf_linked_not_verified": pdf_linked,
            "iframes": [item.get("src", "") for item in observation.get("iframes") or []][:10],
            "canvas_page_like": len(canvases),
            "page_images": len(page_images),
            "export_control_seen": export_available,
            "download_control_seen": download_control,
            "pdfjs_text_layer_chars": text_layer_chars,
        },
        "pages": {
            "reported_by_site": int(reported) if reported else None,
            "accessible": accessible_pages,
            "processed": 0,
            "with_text": 0,
            "without_text": 0,
        },
        "text": {"document_chars": document_chars, "interface_chars_discarded": interface_chars},
        "strategy": strategy,
        "conclusive": conclusive,
        "errors": {
            "network": list(observation.get("network_errors") or [])[:10],
            "console": list(observation.get("console_errors") or [])[:10],
        },
    }


def _strategy(primary: str, viewer: str, restrictions: list[str], export: bool, download: bool, text_layer: int) -> dict:
    """Estratégia A–F (seção 4). Nenhuma delas contorna restrição."""
    if primary == "captcha_required":
        return _s("F", "Intervenção do usuário", "Pause. Resolva o CAPTCHA você mesmo no navegador e confirme para retomar.")
    if primary == "authentication_required":
        return _s("F", "Intervenção do usuário", "A página pede login. Entre com a sua conta no navegador e confirme para retomar.")
    if primary == "html_document":
        return _s("A", "Extração HTML", "Há texto documental no HTML. Use a extração convencional.")
    if primary == "pdf_document":
        return _s("B", "PDF acessível", "Baixe o PDF acessível sem login e processe-o como arquivo.")
    if primary == "pdf_viewer_detected":
        if text_layer:
            return _s("C", "PDF.js com camada de texto", "A camada de texto do visualizador está acessível. Use-a e confira com a imagem.")
        return _s("C", "PDF.js", "Visualizador PDF.js sem PDF acessível nem camada de texto. Peça o PDF por fonte autorizada.")
    if primary == "image_document":
        extra = " Há restrição de pagamento: só as páginas exibidas a qualquer visitante serão lidas." if "payment" in restrictions else ""
        return _s("D", "Imagens das páginas + OCR", "Capture as folhas exibidas e leia por OCR." + extra)
    if primary == "canvas_document":
        if export:
            return _s("E", "Exportação ou impressão do visualizador", "O visualizador oferece impressão ou exportação. Use-a com a sua autorização.")
        return _s("E", "Canvas sem exportação", "Sem exportação legítima visível. Capture só o que a tela mostra, ou importe o arquivo.")
    if primary == "access_restricted":
        return _s("F", "Restrição de acesso", "O conteúdo exige pagamento ou permissão. Forneça o documento por fonte autorizada (PDF licenciado).")
    return _s("F", "Nenhuma fonte documental", "Só interface foi encontrada. Importe o PDF por uma fonte autorizada.")


def _s(code: str, name: str, action: str) -> dict:
    return {"code": code, "name": name, "action": action}
