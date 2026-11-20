"""Política de acesso autorizado. Não disfarça o navegador nem insiste em bloqueio."""

from __future__ import annotations

import random
import re
import threading
import time
from contextlib import contextmanager
from urllib.parse import urljoin, urlsplit

import httpx

from cpmh_backend.access import classify, signals_from_html
from cpmh_backend.errors import AccessPaused, AppError, HttpAccess, UrlRejected
from cpmh_backend.security import validate_url
from cpmh_backend.services.fetch import USER_AGENT, FetchResult, fetch_url

MAX_TEMPORARY_ATTEMPTS = 3
MAX_RATE_LIMIT_ATTEMPTS = 2
MAX_AUTOMATIC_WAIT = 30.0
_CACHE_TTL = 120.0
_CACHE_BYTES = 256_000

_slots: dict[str, threading.Semaphore] = {}
_slot_lock = threading.Lock()
_cache: dict[str, tuple[float, FetchResult]] = {}
_cache_lock = threading.Lock()
_robots: dict[str, tuple[float, str | None]] = {}
_robots_lock = threading.Lock()


def clear_recovery_state() -> None:
    with _slot_lock:
        _slots.clear()
    with _cache_lock:
        _cache.clear()
    with _robots_lock:
        _robots.clear()


def timeout_for(host: str, default: float, table: dict | None) -> float:
    if not host or not isinstance(table, dict):
        return default
    host = host.lower()
    for name, seconds in table.items():
        key = str(name).strip().lower()
        if host == key or host.endswith("." + key):
            try:
                return max(3.0, min(float(seconds), 120.0))
            except (TypeError, ValueError):
                return default
    return default


def annotate(verdict: dict) -> dict:
    item = dict(verdict)
    state = item.get("state") or ""
    provider = item.get("provider") or "none"
    mechanism = {
        "CAPTCHA_DETECTED": "captcha",
        "HUMAN_VERIFICATION_REQUIRED": "cloudflare_challenge",
        "RATE_LIMITED": "rate_limit",
        "JAVASCRIPT_REQUIRED": "javascript_required",
        "SESSION_EXPIRED": "session_expired",
        "AUTHENTICATION_REQUIRED": "authentication",
        "ACCESS_DENIED": "access_denied",
        "NAVIGATION_ERROR": "network",
        "BROWSER_ERROR": "browser",
        "ACCESS_GRANTED": "none",
    }.get(state, "unknown")
    method, action = _method(state)
    if provider == "robots":
        mechanism = "robots"
        method = "import_file"
        action = "O robots.txt deste site não permite a captura deste caminho. Importe o arquivo se você tiver autorização para usá-lo."
        item["message"] = action
    elif item.get("alternative") and state != "ACCESS_GRANTED":
        method = "public_pdf"
        action = "A própria página indicou um PDF público no mesmo site. Use esse arquivo ou importe o documento. A captura não procura outras fontes."
    retry_after = item.get("retry_after")
    if state == "RATE_LIMITED" and isinstance(retry_after, (int, float)) and retry_after > MAX_AUTOMATIC_WAIT:
        action = f"O site pediu uma espera de {_wait_label(float(retry_after))}. A captura não fica repetindo o pedido."
        item["message"] = action
    item["mechanism"] = mechanism
    item["method"] = method
    item["action"] = action
    return item


def retry_plan(verdict: dict, *, attempt: int, retry_after: float | None, random_unit: float) -> dict:
    state = verdict.get("state") or ""
    status = int(verdict.get("http_status") or 0)
    blocked = state in {
        "CAPTCHA_DETECTED",
        "HUMAN_VERIFICATION_REQUIRED",
        "AUTHENTICATION_REQUIRED",
        "ACCESS_DENIED",
        "SESSION_EXPIRED",
        "JAVASCRIPT_REQUIRED",
        "BROWSER_ERROR",
    } or status in {401, 403}
    if blocked or state == "ACCESS_GRANTED":
        return {"retry": False, "wait_seconds": 0.0}
    if state == "RATE_LIMITED" or status == 429:
        if attempt >= MAX_RATE_LIMIT_ATTEMPTS or retry_after is None or retry_after > MAX_AUTOMATIC_WAIT:
            return {"retry": False, "wait_seconds": 0.0}
        return {"retry": True, "wait_seconds": max(0.0, float(retry_after))}
    temporary = state == "NAVIGATION_ERROR" or status >= 500
    if temporary and attempt < MAX_TEMPORARY_ATTEMPTS:
        base = min(8.0, 0.5 * (2 ** (attempt - 1)))
        unit = min(1.0, max(0.0, random_unit))
        return {"retry": True, "wait_seconds": round(base + (base * 0.25 * unit), 3)}
    return {"retry": False, "wait_seconds": 0.0}


def robots_allows(text: str, path: str, agent: str = "cpmhdocumentintelligence") -> bool:
    if not looks_like_robots(text):
        return True
    groups: list[dict] = []
    current: dict | None = None
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, value = [part.strip() for part in line.split(":", 1)]
        key = key.lower()
        if key == "user-agent":
            if current and current["rules"]:
                groups.append(current)
                current = {"agents": [value.lower()], "rules": []}
            elif current:
                current["agents"].append(value.lower())
            else:
                current = {"agents": [value.lower()], "rules": []}
        elif key in {"allow", "disallow"} and current is not None:
            current["rules"].append((key, value))
    if current:
        groups.append(current)
    agent = agent.lower()
    selected = [group for group in groups if any(_agent_match(item, agent) for item in group["agents"])]
    specific = [group for group in selected if any(item != "*" for item in group["agents"])]
    chosen = specific or selected
    if not chosen:
        return True
    match: tuple[str, str] | None = None
    target = path or "/"
    for group in chosen:
        for kind, prefix in group["rules"]:
            if prefix == "":
                continue
            if target.startswith(prefix) and (match is None or len(prefix) > len(match[1])):
                match = (kind, prefix)
    if match is None:
        return True
    return match[0] == "allow"


def looks_like_robots(text: str) -> bool:
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if line:
            return line.lower().startswith("user-agent")
    return False


def public_alternative(html: str, page_url: str) -> dict | None:
    if not html or not page_url:
        return None
    origin = _endpoint(page_url)
    found: list[str] = []
    for tag in _tags(html, "meta"):
        if tag.get("name", "").lower() == "citation_pdf_url" and tag.get("content"):
            found.append(tag["content"])
    for tag in _tags(html, "link"):
        if "alternate" in tag.get("rel", "").lower() and "pdf" in tag.get("type", "").lower() and tag.get("href"):
            found.append(tag["href"])
    for tag in _tags(html, "a"):
        href = tag.get("href", "")
        if href.lower().split("?", 1)[0].endswith(".pdf"):
            found.append(href)
    for candidate in found:
        absolute = urljoin(page_url, candidate)
        target = urlsplit(absolute)
        if target.scheme not in {"http", "https"} or _endpoint(absolute) != origin:
            continue
        path = (target.path or "").lower()
        if any(piece in path for piece in ("captcha", "challenge", "cdn-cgi", "login")):
            continue
        return {"kind": "public_pdf", "url": absolute, "label": "PDF público indicado pela própria página"}
    return None


@contextmanager
def domain_slot(host: str, limit: int):
    capacity = max(1, min(int(limit or 1), 4))
    with _slot_lock:
        slot = _slots.get(host)
        if slot is None or getattr(slot, "_cpmh_limit", None) != capacity:
            slot = threading.Semaphore(capacity)
            slot._cpmh_limit = capacity  # type: ignore[attr-defined]
            _slots[host] = slot
    slot.acquire()
    try:
        yield
    finally:
        slot.release()


def managed_fetch(
    url: str,
    *,
    allow_local: bool,
    max_bytes: int,
    timeout: float,
    domain_limit: int = 2,
    sleep=time.sleep,
    random_unit=None,
    should_stop=None,
    client: httpx.Client | None = None,
    trace: list | None = None,
) -> tuple[FetchResult, bool]:
    validated = validate_url(url, allow_local=allow_local)
    host = validated.host
    roller = random_unit or random.random
    with domain_slot(host, domain_limit):
        if not _robots_allow(validated.url, allow_local=allow_local, timeout=min(timeout, 10), client=client):
            verdict = annotate(
                {
                    **classify({"url": validated.url, "status": 403, "title": "robots.txt", "text": "acesso negado"}),
                    "provider": "robots",
                }
            )
            raise AccessPaused(verdict)
        cached = _read_cache(validated.url)
        if cached is not None:
            if trace is not None:
                trace.append({"url": validated.url, "status": 200, "cached": True})
            return cached, True
        attempt = 0
        while True:
            if should_stop and should_stop():
                raise AppError("A tarefa foi cancelada antes de um novo pedido.")
            attempt += 1
            try:
                result = fetch_url(
                    validated.url,
                    allow_local=allow_local,
                    max_bytes=max_bytes,
                    timeout=timeout,
                    client=client,
                )
            except HttpAccess as exc:
                if trace is not None:
                    trace.append({"url": exc.final_url, "status": exc.http_status, "cached": False})
                verdict = classify(signals_from_html(validated.url, exc.final_url, exc.http_status, exc.snippet))
                alternative = public_alternative(exc.snippet, exc.final_url)
                if alternative:
                    verdict["alternative"] = alternative
                verdict["retry_after"] = exc.retry_after
                verdict["attempts_made"] = attempt
                plan = retry_plan(verdict, attempt=attempt, retry_after=exc.retry_after, random_unit=float(roller()))
                if not plan["retry"]:
                    raise AccessPaused(annotate(verdict)) from exc
                _wait(plan["wait_seconds"], sleep, should_stop)
                continue
            except httpx.TransportError as exc:
                if trace is not None:
                    trace.append({"url": validated.url, "status": 0, "cached": False})
                verdict = classify({"url": validated.url, "navigation_error": "network"})
                verdict["attempts_made"] = attempt
                plan = retry_plan(verdict, attempt=attempt, retry_after=None, random_unit=float(roller()))
                if not plan["retry"]:
                    raise AccessPaused(annotate(verdict)) from exc
                _wait(plan["wait_seconds"], sleep, should_stop)
                continue
            except UrlRejected:
                raise
            if trace is not None:
                trace.append({"url": result.final_url, "status": 200, "cached": False})
            _write_cache(validated.url, result)
            return result, False


def _robots_allow(url: str, *, allow_local: bool, timeout: float, client: httpx.Client | None) -> bool:
    parts = urlsplit(url)
    origin = f"{parts.scheme}://{parts.netloc}"
    body = _robots_body(origin, allow_local=allow_local, timeout=timeout, client=client)
    if body is None:
        return True
    return robots_allows(body, parts.path or "/", "cpmhdocumentintelligence")


def _robots_body(origin: str, *, allow_local: bool, timeout: float, client: httpx.Client | None) -> str | None:
    now = time.monotonic()
    with _robots_lock:
        cached = _robots.get(origin)
        if cached and now - cached[0] < _CACHE_TTL:
            return cached[1]
    try:
        result = fetch_url(origin + "/robots.txt", allow_local=allow_local, max_bytes=100_000, timeout=timeout, client=client)
        text = result.data.decode("utf-8", errors="replace")
        if not looks_like_robots(text):
            text = None
    except (HttpAccess, UrlRejected, httpx.TransportError):
        text = None
    with _robots_lock:
        _robots[origin] = (now, text)
    return text


def _read_cache(url: str) -> FetchResult | None:
    with _cache_lock:
        found = _cache.get(url)
        if found is None:
            return None
        stored, result = found
        if time.monotonic() - stored > _CACHE_TTL:
            _cache.pop(url, None)
            return None
        return result


def _write_cache(url: str, result: FetchResult) -> None:
    if len(result.data) > _CACHE_BYTES:
        return
    with _cache_lock:
        if len(_cache) > 32:
            _cache.clear()
        _cache[url] = (time.monotonic(), result)


def _wait(seconds: float, sleep, should_stop) -> None:
    if seconds <= 0:
        return
    deadline = time.monotonic() + seconds
    while True:
        if should_stop and should_stop():
            raise AppError("A tarefa foi cancelada antes de um novo pedido.")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        sleep(min(0.2, remaining))


def _method(state: str) -> tuple[str, str]:
    if state == "ACCESS_GRANTED":
        return "capture", "A captura pode continuar."
    if state in {"CAPTCHA_DETECTED", "HUMAN_VERIFICATION_REQUIRED"}:
        return "human_verification", "Abra o navegador e conclua a verificação no site. Depois peça uma nova checagem."
    if state in {"AUTHENTICATION_REQUIRED", "SESSION_EXPIRED"}:
        return "manual_login", "Entre com a sua conta no navegador, se o site permitir. A captura não envia senha."
    if state == "JAVASCRIPT_REQUIRED":
        return "human_browser", "Abra a página no navegador integrado. A captura já executa JavaScript e não vai mascarar o navegador."
    if state == "RATE_LIMITED":
        return "wait", "Espere o intervalo informado pelo site. Não haverá outra tentativa automática."
    if state == "NAVIGATION_ERROR":
        return "recheck", "Confira a rede e peça uma nova checagem. A repetição automática já chegou ao limite."
    if state == "BROWSER_ERROR":
        return "recheck", "Peça uma nova checagem. O aplicativo não troca de navegador para contornar a falha."
    return "import_file", "Este bloqueio não será contornado. Importe o arquivo se a obtenção por URL não for possível."


def _wait_label(seconds: float) -> str:
    if seconds > 86_400:
        return "mais de um dia"
    if seconds >= 60:
        return f"{int(seconds // 60)} minutos"
    return f"{int(seconds)} segundos"


def _agent_match(rule: str, agent: str) -> bool:
    if rule == "*":
        return True
    return agent.startswith(rule)


def _endpoint(url: str) -> tuple[str, int]:
    parts = urlsplit(url)
    port = parts.port or (443 if parts.scheme == "https" else 80)
    return (parts.hostname or "").lower(), port


def _tags(html: str, name: str) -> list[dict[str, str]]:
    tags = []
    for match in re.finditer(rf"<{name}\b[^>]*>", html, re.I):
        attrs = {
            key.lower(): value
            for key, value in re.findall(r"([A-Za-z_:][-A-Za-z0-9_:.]*)\s*=\s*[\"']([^\"']*)[\"']", match.group(0))
        }
        tags.append(attrs)
    return tags
