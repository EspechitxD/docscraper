"""Modo laboratório: carrega a extensão NopeCHA (ou outra) só em páginas locais de teste.

Uso acadêmico, em ambiente controlado. A extensão só é carregada quando TODAS as condições valem:
  1. CPMH_LAB_MODE=1
  2. há uma extensão com manifest.json: CPMH_LAB_EXTENSION_DIR, ou por padrão lab/extension/nopecha
  3. a URL alvo está em loopback (localhost, 127.0.0.1 ou ::1)

Qualquer outra URL segue o fluxo normal de captura, sem extensão. Isso mantém a política do
SECURITY.md: o CPMH não contorna CAPTCHA em sites de terceiros.

Chave do serviço (opcional): variável NOPECHA_KEY. Sem chave, vale o plano gratuito do serviço
(limite por IP). A chave vai para uma cópia da extensão no perfil de laboratório; o pacote em
lab/extension/nopecha nunca é alterado.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
from pathlib import Path
from urllib.parse import urlsplit

log = logging.getLogger("cpmh.lab_extension")
MARCA_INTEGRACAO = "LAB-INTEGRACAO-v3"

LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
BUNDLED_EXTENSION = _PROJECT_ROOT / "lab" / "extension" / "nopecha"


def lab_extension_dir() -> Path | None:
    if os.environ.get("CPMH_LAB_MODE", "").strip().lower() not in {"1", "true", "yes"}:
        return None
    raw = os.environ.get("CPMH_LAB_EXTENSION_DIR", "").strip()
    path = Path(raw).expanduser() if raw else BUNDLED_EXTENSION
    return path if (path / "manifest.json").is_file() else None


def lab_enabled_for(url: str) -> Path | None:
    """Devolve a pasta da extensão se o modo laboratório vale para esta URL; senão None."""
    ext = lab_extension_dir()
    if ext is None:
        return None
    host = (urlsplit(url).hostname or "").lower()
    if host not in LOOPBACK_HOSTS:
        log.info("Modo laboratório ignorado: host %s não é loopback.", host)
        return None
    return ext


def lab_reason(url: str) -> str:
    """Diz em uma frase por que o modo laboratório está ativo ou inativo para esta URL."""
    if os.environ.get("CPMH_LAB_MODE", "").strip().lower() not in {"1", "true", "yes"}:
        return "CPMH_LAB_MODE não está definido como 1 neste processo"
    raw = os.environ.get("CPMH_LAB_EXTENSION_DIR", "").strip()
    path = Path(raw).expanduser() if raw else BUNDLED_EXTENSION
    if not (path / "manifest.json").is_file():
        return f"não há manifest.json em {path}"
    host = (urlsplit(url).hostname or "").lower()
    if host not in LOOPBACK_HOSTS:
        return f"o host '{host or url[:40]}' não é loopback (localhost, 127.0.0.1 ou ::1)"
    return "ativo"


def lab_profile_dir() -> Path:
    raw = os.environ.get("CPMH_LAB_PROFILE_DIR", "").strip()
    return Path(raw).expanduser() if raw else Path.home() / ".cpmh-lab-profile"


def prepare_runtime_extension(source: Path, profile: Path) -> Path:
    """Copia a extensão para o perfil de laboratório e injeta a chave do serviço, se houver."""
    target = profile / "ext-runtime"
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)
    shutil.copytree(source, target)
    key = os.environ.get("NOPECHA_KEY", "").strip()
    manifest_path = target / "manifest.json"
    if key:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if isinstance(manifest.get("nopecha"), dict):
            manifest["nopecha"]["key"] = key
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
            log.info("Modo laboratório: chave do serviço injetada na cópia da extensão.")
        else:
            log.warning("Modo laboratório: esta extensão não aceita chave no manifest; ignorada.")
    _enable_lab_solvers(manifest_path)
    return target


_LAB_SOLVER_FLAGS = (
    "geetest_auto_open", "geetest_auto_solve",
    "funcaptcha_auto_open", "funcaptcha_auto_solve",
    "awscaptcha_auto_open", "awscaptcha_auto_solve",
    "lemincaptcha_auto_open", "lemincaptcha_auto_solve",
)


def _enable_lab_solvers(manifest_path: Path) -> None:
    """Na cópia de laboratório, liga os tipos de desafio que o build traz desligados (ex.: GeeTest, slider)."""
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    cfg = manifest.get("nopecha")
    if not isinstance(cfg, dict):
        return
    changed = False
    for flag in _LAB_SOLVER_FLAGS:
        if flag in cfg and cfg[flag] is not True:
            cfg[flag] = True
            changed = True
    if changed:
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def open_capture_context(playwright, url: str, *, launch_browser, viewport: dict):
    """Abre o contexto de captura. Devolve (context, close).

    Fluxo normal: navegador headless + contexto isolado. Modo laboratório: contexto persistente
    com janela visível, porque o Chromium só carrega extensões assim.
    """
    source = lab_enabled_for(url)
    log.info("Modo laboratório: %s", lab_reason(url))
    if source is None:
        browser = launch_browser(playwright)
        context = browser.new_context(viewport=viewport, device_scale_factor=1)
        return context, browser.close

    from cpmh_backend.services.capture import find_browser

    chrome_path, _label = find_browser()
    profile = lab_profile_dir()
    profile.mkdir(parents=True, exist_ok=True)
    ext = prepare_runtime_extension(source, profile)
    log.info("Modo laboratório ativo: extensão %s", ext)
    context = playwright.chromium.launch_persistent_context(
        str(profile / "chrome-data"),
        executable_path=chrome_path or None,
        headless=False,
        viewport=viewport,
        args=[f"--disable-extensions-except={ext}", f"--load-extension={ext}"],
    )
    return context, context.close


def lab_solve_timeout() -> float:
    try:
        return max(1.0, float(os.environ.get("CPMH_LAB_SOLVE_TIMEOUT", "40")))
    except ValueError:
        return 40.0


def wait_until_unchallenged(page, url: str, still_challenged) -> dict:
    """Só no modo laboratório: dá tempo para a extensão resolver o desafio antes da classificação.

    `still_challenged(page)` devolve o veredito atual do app (dict com "state" e "provider") ou None.
    Repete a checagem a cada segundo, até CPMH_LAB_SOLVE_TIMEOUT. Usa o MESMO critério que pausa a
    captura (widget conhecido ou texto de slider), em vez de olhar só seletores de widget.
    Fora do modo laboratório não faz nada e devolve {}.
    """
    if lab_enabled_for(url) is None:
        return {}
    limit = lab_solve_timeout()
    waited = 0.0
    verdict = None
    while True:
        try:
            verdict = still_challenged(page)
        except Exception:  # página navegando ou fechando: tenta de novo até o limite
            verdict = {"state": "CAPTCHA_DETECTED", "provider": "unknown"}
        if not verdict:
            log.info("Modo laboratório: nenhum desafio pendente após %.0fs.", waited)
            return {"lab": True, "cleared": True, "waited": waited}
        if waited >= limit:
            break
        page.wait_for_timeout(1000)
        waited += 1.0
    log.info("Modo laboratório: desafio (%s) ainda presente após %.0fs.", verdict.get("provider"), waited)
    return {"lab": True, "cleared": False, "waited": waited, "provider": verdict.get("provider")}


def lab_note(info: dict) -> str:
    """Texto curto para o relatório de acesso: mostra se a extensão estava ativa e o que aconteceu."""
    if not info.get("lab"):
        return ""
    if info.get("cleared"):
        return "modo laboratório: extensão ativa, desafio resolvido"
    return (
        f"modo laboratório: extensão ativa, desafio ({info.get('provider') or 'desconhecido'}) "
        f"não resolvido em {int(info.get('waited') or 0)}s"
    )


def human_pause_enabled() -> bool:
    """CPMH_LAB_HUMAN_PAUSE=1: ao detectar desafio, mantém a janela aberta para a pessoa resolver."""
    return os.environ.get("CPMH_LAB_HUMAN_PAUSE", "").strip().lower() in {"1", "true", "yes"}


def human_pause_timeout() -> float:
    try:
        return max(1.0, float(os.environ.get("CPMH_LAB_HUMAN_PAUSE_TIMEOUT", "180")))
    except ValueError:
        return 180.0


def wait_for_human(page, still_challenged, *, headed: bool) -> dict:
    """Mantém a página aberta e visível até a pessoa resolver o desafio, ou até o timeout.

    `still_challenged(page)` é a MESMA checagem que classifica a página no resto do app.
    Só faz sentido com uma janela visível (`headed=True`); sem isso devolve de imediato
    para não travar uma sessão headless onde ninguém veria o desafio.
    Devolve {"human_pause": True, "resolved": bool, "waited": segundos}.
    """
    if not human_pause_enabled() or not headed:
        return {}
    limit = human_pause_timeout()
    waited = 0.0
    log.info("Pausa para o usuário: aguardando até %.0fs que a verificação seja concluída na janela.", limit)
    while waited < limit:
        try:
            verdict = still_challenged(page)
        except Exception:
            verdict = {"state": "CAPTCHA_DETECTED"}
        if not verdict:
            log.info("Pausa para o usuário: verificação concluída após %.0fs.", waited)
            return {"human_pause": True, "resolved": True, "waited": waited}
        page.wait_for_timeout(1000)
        waited += 1.0
    log.info("Pausa para o usuário: tempo esgotado (%.0fs) sem conclusão.", limit)
    return {"human_pause": True, "resolved": False, "waited": waited}


def human_pause_note(info: dict) -> str:
    if not info.get("human_pause"):
        return ""
    if info.get("resolved"):
        return f"verificação concluída pelo usuário na janela ({int(info['waited'])}s)"
    return f"usuário não concluiu a verificação na janela em {int(info['waited'])}s"
