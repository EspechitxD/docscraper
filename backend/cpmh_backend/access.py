"""Classifica bloqueios de acesso. Não resolve CAPTCHA nem contorna antibot."""

from __future__ import annotations

import re
from urllib.parse import urlsplit

STATES = {
    "ACCESS_GRANTED",
    "CAPTCHA_DETECTED",
    "HUMAN_VERIFICATION_REQUIRED",
    "AUTHENTICATION_REQUIRED",
    "ACCESS_DENIED",
    "RATE_LIMITED",
    "UNKNOWN_BLOCK",
    "NAVIGATION_ERROR",
    "JAVASCRIPT_REQUIRED",
    "SESSION_EXPIRED",
    "BROWSER_ERROR",
}

_SLIDER_PROMPT = re.compile(
    r"(滑动验证|滑块验证|拖动.{0,8}滑块|请完成.{0,6}验证|安全验证|人机验证|"
    r"slide to (?:verify|complete|unlock)|drag the slider|complete the (?:slider|security) (?:check|verification)|"
    r"arraste o (?:controle deslizante|bot[ãa]o)|deslize para verificar|verifica[çc][ãa]o (?:de seguran[çc]a|deslizante))",
    re.IGNORECASE,
)
_SECRET = re.compile(r"(?i)(cookie|set-cookie|authorization|sitekey|token|password)\s*[:=]\s*\S+")
_LONG_TOKEN = re.compile(r"\b[A-Za-z0-9_\-]{40,}\b")


def signals_from_html(url: str, final_url: str, status: int, html: str) -> dict:
    sample = html[:20000]
    title_match = re.search(r"<title[^>]*>(.*?)</title>", sample, re.I | re.S)
    markers = []
    lowered = sample.lower()
    for needle in (
        "g-recaptcha",
        "h-captcha",
        "cf-turnstile",
        "challenge-form",
        "cf-browser-verification",
        "cf-challenge",
        "type=\"password\"",
        "type='password'",
        "id=\"captcha\"",
        "class=\"captcha\"",
        "<noscript",
    ):
        if needle in lowered:
            markers.append(needle)
    return {
        "url": url,
        "final_url": final_url,
        "status": status,
        "title": re.sub(r"<[^>]+>", " ", title_match.group(1)) if title_match else "",
        "text": re.sub(r"<[^>]+>", " ", sample),
        "markers": markers,
        "iframes": re.findall(r"<iframe\b[^>]*\bsrc=[\"']([^\"']+)", sample, re.I)[:20],
        "scripts": re.findall(r"<script\b[^>]*\bsrc=[\"']([^\"']+)", sample, re.I)[:30],
    }


def classify(signals: dict) -> dict:
    url = str(signals.get("url") or "")
    final_url = str(signals.get("final_url") or url)
    status = int(signals.get("status") or 0)
    title = _clean(signals.get("title") or "")
    raw_text = str(signals.get("text") or "")
    text = _clean(raw_text)
    markers = [_clean(item) for item in signals.get("markers") or []]
    iframes = [_clean(item) for item in signals.get("iframes") or []]
    scripts = [_clean(item) for item in signals.get("scripts") or []]
    error = _clean(signals.get("navigation_error") or "")
    folded = f"{title}\n{text}".lower()
    evidence: list[str] = []

    if error:
        evidence.append("navegação interrompida")
        if any(token in error.lower() for token in ("browser", "navegador", "playwright")):
            return _verdict("BROWSER_ERROR", "browser", 0.9, url, final_url, evidence, status)
        return _verdict("NAVIGATION_ERROR", "network", 0.9, url, final_url, evidence, status)

    if status == 429 or _has(folded, "too many requests", "rate limit", "muitas solicitações"):
        evidence.append(f"http {status}" if status else "texto de limite")
        return _verdict("RATE_LIMITED", "none", 0.86, url, final_url, evidence, status)

    widget = _widget(markers, iframes, scripts, evidence)
    challenge_url = _challenge_destination(url, final_url)
    if challenge_url:
        evidence.append("redirecionamento para verificação")

    if widget == "recaptcha_v2":
        return _verdict("CAPTCHA_DETECTED", widget, 0.93, url, final_url, evidence, status)
    if widget == "hcaptcha":
        return _verdict("CAPTCHA_DETECTED", widget, 0.93, url, final_url, evidence, status)
    if widget == "turnstile":
        return _verdict("CAPTCHA_DETECTED", widget, 0.93, url, final_url, evidence, status)
    if widget == "unknown":
        return _verdict("CAPTCHA_DETECTED", "unknown", 0.72, url, final_url, evidence, status)

    # Verificação por controle deslizante ou quebra-cabeça, sem widget conhecido (comum em sites chineses).
    # O texto visível diz o que fazer; só pausamos. Nunca arrastamos o controle.
    if len(raw_text) < 2000 and _SLIDER_PROMPT.search(folded):
        evidence.append("texto pedindo verificação por controle deslizante")
        return _verdict("CAPTCHA_DETECTED", "slider", 0.9, url, final_url, evidence, status)

    cloudflare = _cloudflare_interstitial(folded, markers)
    if cloudflare or (challenge_url and _has(folded, "humano", "human", "verificar", "verify", "moment")):
        evidence.extend(cloudflare)
        return _verdict("HUMAN_VERIFICATION_REQUIRED", "cloudflare_challenge" if cloudflare else "unknown", 0.84, url, final_url, evidence, status)

    if _has(folded, "sessão expirada", "sessão expirou", "sua sessão expirou", "session expired", "session has expired"):
        evidence.append("texto de sessão expirada")
        return _verdict("SESSION_EXPIRED", "none", 0.86, url, final_url, evidence, status)

    javascript = _has(
        folded,
        "habilite o javascript",
        "enable javascript",
        "javascript is required",
        "javascript obrigatório",
        "you need to enable javascript",
    )
    if signals.get("rendered") and javascript and len(raw_text) < 500:
        evidence.append("página ainda pede JavaScript depois da execução")
        return _verdict("JAVASCRIPT_REQUIRED", "none", 0.8, url, final_url, evidence, status)

    if status == 401 or (_password(markers) and _has(folded, "entrar", "login", "sign in", "senha", "password")):
        if status == 401:
            evidence.append("http 401")
        if _password(markers):
            evidence.append("campo de senha")
        return _verdict("AUTHENTICATION_REQUIRED", "none", 0.88, url, final_url, evidence, status)

    if status == 403 or _has(folded, "access denied", "acesso negado", "you have been blocked", "você foi bloqueado"):
        if status:
            evidence.append(f"http {status or 403}")
        if _has(folded, "blocked", "bloqueado", "denied", "negado"):
            evidence.append("texto de bloqueio")
        state = "ACCESS_DENIED" if evidence else "UNKNOWN_BLOCK"
        return _verdict(state, "none", 0.8 if state == "ACCESS_DENIED" else 0.55, url, final_url, evidence, status)

    if status >= 500:
        evidence.append(f"http {status}")
        return _verdict("UNKNOWN_BLOCK", "none", 0.6, url, final_url, evidence, status)

    if status >= 400:
        evidence.append(f"http {status}")
        return _verdict("UNKNOWN_BLOCK", "none", 0.5, url, final_url, evidence, status)

    return _verdict("ACCESS_GRANTED", "none", 0.9, url, final_url, ["página aberta"], status)


def _widget(markers: list[str], iframes: list[str], scripts: list[str], evidence: list[str]) -> str:
    iframe_text = " ".join(iframes).lower()
    marker_text = " ".join(markers).lower()
    script_text = " ".join(scripts).lower()
    recaptcha_widget = "g-recaptcha" in marker_text or "google.com/recaptcha/api2" in iframe_text or "recaptcha/api2/anchor" in iframe_text
    hcaptcha_widget = "h-captcha" in marker_text or "hcaptcha.com" in iframe_text
    turnstile_widget = "cf-turnstile" in marker_text or "challenges.cloudflare.com" in iframe_text
    if recaptcha_widget:
        evidence.append("widget reCAPTCHA")
        return "recaptcha_v2"
    if hcaptcha_widget:
        evidence.append("widget hCaptcha")
        return "hcaptcha"
    if turnstile_widget:
        evidence.append("widget Turnstile")
        return "turnstile"
    unknown = ("captcha" in marker_text) and ("iframe" in marker_text or "captcha" in iframe_text)
    if unknown:
        evidence.append("widget de CAPTCHA não identificado")
        return "unknown"
    # Script sozinho, inclusive reCAPTCHA v3, não prova um desafio ativo.
    if "recaptcha/api.js" in script_text or "hcaptcha.com/1/api.js" in script_text or "turnstile" in script_text:
        evidence.append("script de verificação sem widget ativo")
    return ""


def _cloudflare_interstitial(folded: str, markers: list[str]) -> list[str]:
    marker_text = " ".join(markers).lower()
    structural = "challenge-form" in marker_text or "cf-browser-verification" in marker_text or "cf-challenge" in marker_text
    titled = _has(folded, "just a moment", "um momento", "attention required", "verificando se você é humano", "checking your browser")
    if structural and titled:
        return ["desafio Cloudflare"]
    if structural and _has(folded, "cloudflare"):
        return ["formulário de desafio Cloudflare"]
    return []


def _challenge_destination(url: str, final_url: str) -> bool:
    if not final_url or final_url == url:
        return False
    final = urlsplit(final_url)
    host = (final.hostname or "").lower()
    path = (final.path or "").lower()
    return "challenges.cloudflare.com" in host or "/cdn-cgi/challenge" in path or path.rstrip("/").endswith("/captcha")


def _password(markers: list[str]) -> bool:
    return any("password" in item.lower() for item in markers)


def _has(text: str, *needles: str) -> bool:
    return any(needle in text for needle in needles)


def _clean(value: str) -> str:
    text = " ".join(str(value).split())
    text = _SECRET.sub(r"\1=[omitido]", text)
    text = _LONG_TOKEN.sub("[omitido]", text)
    return text[:300]


def _verdict(state: str, provider: str, confidence: float, url: str, final_url: str, evidence: list[str], status: int) -> dict:
    unique = []
    for item in evidence:
        if item and item not in unique:
            unique.append(item[:160])
    return {
        "state": state,
        "provider": provider,
        "confidence": round(confidence, 2),
        "url": url[:500],
        "final_url": final_url[:500],
        "http_status": status,
        "evidence": unique[:8],
        "message": _message(state, provider),
    }


def _message(state: str, provider: str) -> str:
    names = {
        "recaptcha_v2": "Google reCAPTCHA",
        "hcaptcha": "hCaptcha",
        "turnstile": "Cloudflare Turnstile",
        "cloudflare_challenge": "verificação da Cloudflare",
        "unknown": "CAPTCHA não identificado",
        "slider": "verificação por controle deslizante",
        "none": "restrição de acesso",
    }
    name = names.get(provider, "restrição de acesso")
    if state == "ACCESS_GRANTED":
        return "A captura abriu a página sem bloqueio detectado."
    if state == "CAPTCHA_DETECTED":
        return f"A página apresentou {name}. A extração foi pausada. Conclua a verificação no site, se ele permitir, e peça nova checagem. O aplicativo não resolve o desafio."
    if state == "HUMAN_VERIFICATION_REQUIRED":
        return f"O site pediu {name}. A extração foi pausada até a captura conseguir abrir a página."
    if state == "AUTHENTICATION_REQUIRED":
        return "A página pede autenticação. A captura não entra com senha nem contorna o login. Importe o arquivo se você já tiver autorização para usá-lo."
    if state == "ACCESS_DENIED":
        return "O site negou o acesso. A captura não insiste nem troca de identificador. Importe o arquivo manualmente se a obtenção por URL não for possível."
    if state == "RATE_LIMITED":
        return "O site limitou o número de pedidos. A tarefa fica pausada. Não há nova tentativa automática."
    if state == "NAVIGATION_ERROR":
        return "A navegação não chegou a abrir a página. Confira o endereço e tente a checagem de novo."
    if state == "BROWSER_ERROR":
        return "O navegador de captura falhou antes de abrir a página. A nova checagem usa o mesmo Chromium, sem outro identificador."
    if state == "SESSION_EXPIRED":
        return "A sessão da página expirou. Entre de novo no navegador, se o site permitir. A captura não reaproveita senha nem cookie."
    if state == "JAVASCRIPT_REQUIRED":
        return "A página continuou pedindo JavaScript depois que o navegador de captura o executou. Abra o endereço no navegador integrado. O aplicativo não mascara a automação."
    return "O acesso não pôde ser classificado com segurança. A extração permanece pausada."
