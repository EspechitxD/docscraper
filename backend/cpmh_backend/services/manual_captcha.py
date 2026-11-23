"""Resolução manual de verificação: ao detectar CAPTCHA, abre uma janela visível do Chrome
para a pessoa resolver na hora, sem extensão e sem automação de nenhum tipo. A pessoa faz
exatamente o que faria abrindo o site direto no navegador; o app só espera e retoma sozinho.

Vale para qualquer site, não só locais, porque não há bypass algum: um humano decide e age.
Ligado por CPMH_MANUAL_CAPTCHA=1.
"""
from __future__ import annotations

import logging
import os

log = logging.getLogger("cpmh.manual_captcha")


def manual_captcha_enabled() -> bool:
    return os.environ.get("CPMH_MANUAL_CAPTCHA", "").strip().lower() in {"1", "true", "yes"}


def manual_captcha_timeout() -> float:
    try:
        return max(1.0, float(os.environ.get("CPMH_MANUAL_CAPTCHA_TIMEOUT", "180")))
    except ValueError:
        return 180.0


def open_browser_context(playwright, *, launch_browser, viewport: dict):
    """Contexto headless normal, ou visível quando a resolução manual está ligada.

    Devolve (context, close). Mantém a mesma assinatura usada antes de haver o modo laboratório,
    só troca headless por visível quando CPMH_MANUAL_CAPTCHA=1.
    """
    if not manual_captcha_enabled():
        browser = launch_browser(playwright)
        return browser.new_context(viewport=viewport, device_scale_factor=1), browser.close

    from cpmh_backend.services.capture import find_browser

    chrome_path, _label = find_browser()
    browser = playwright.chromium.launch(executable_path=chrome_path or None, headless=False)
    return browser.new_context(viewport=viewport, device_scale_factor=1), browser.close


def focus_and_wait_ready(page, timeout_ms: int) -> None:
    """No modo manual: seleciona a aba e espera a página terminar de carregar antes de qualquer outra coisa.

    Sem isso, a checagem de desafio roda em cima de uma página ainda carregando (scripts e imagens
    chegando ao mesmo tempo), e tudo parece acontecer junto na janela visível. Fora do modo manual
    não faz nada.
    """
    if not manual_captcha_enabled():
        return
    try:
        page.bring_to_front()
    except Exception:
        pass
    for state in ("load", "networkidle"):
        try:
            page.wait_for_load_state(state, timeout=timeout_ms)
        except Exception:
            pass


def wait_for_manual_solve(page, still_challenged) -> dict:
    """Mantém a página aberta até a pessoa resolver o desafio na janela, ou até o timeout.

    `still_challenged(page)` é a mesma checagem que classifica a página no resto do app.
    Fora do modo manual não faz nada e devolve {}.
    """
    if not manual_captcha_enabled():
        return {}
    limit = manual_captcha_timeout()
    waited = 0.0
    log.info("Verificação manual: janela aberta, aguardando até %.0fs que você resolva.", limit)
    while waited < limit:
        try:
            verdict = still_challenged(page)
        except Exception:
            verdict = {"state": "CAPTCHA_DETECTED"}
        if not verdict:
            log.info("Verificação manual: concluída após %.0fs.", waited)
            return {"manual": True, "resolved": True, "waited": waited}
        page.wait_for_timeout(1000)
        waited += 1.0
    log.info("Verificação manual: tempo esgotado (%.0fs) sem conclusão.", limit)
    return {"manual": True, "resolved": False, "waited": waited}


def manual_note(info: dict) -> str:
    if not info.get("manual"):
        return ""
    if info.get("resolved"):
        return f"verificação concluída manualmente na janela ({int(info['waited'])}s)"
    return f"janela aberta para verificação manual, não concluída em {int(info['waited'])}s"
