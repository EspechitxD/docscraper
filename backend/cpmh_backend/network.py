"""Proxy/VPN fixo da sessão. Um único destino por execução; nunca rodízio."""

from __future__ import annotations

from urllib.parse import urlsplit


def redact_proxy(url: str | None) -> str:
    """Rótulo para auditoria: esquema://host:porta, sem usuário nem senha."""
    raw = (url or "").strip()
    if not raw:
        return "sem proxy"
    parts = urlsplit(raw)
    if not parts.hostname:
        return "proxy inválido"
    port = f":{parts.port}" if parts.port else ""
    return f"{parts.scheme or 'http'}://{parts.hostname}{port}"


def playwright_proxy(url: str | None) -> dict | None:
    """Argumento `proxy=` do chromium.launch(). None quando não há proxy."""
    raw = (url or "").strip()
    if not raw:
        return None
    parts = urlsplit(raw)
    if not parts.hostname:
        return None
    port = f":{parts.port}" if parts.port else ""
    config = {"server": f"{parts.scheme or 'http'}://{parts.hostname}{port}"}
    if parts.username:
        config["username"] = parts.username
    if parts.password:
        config["password"] = parts.password
    return config


def httpx_proxy(url: str | None) -> str | None:
    """Argumento `proxy=` do httpx.Client. None quando não há proxy."""
    raw = (url or "").strip()
    return raw or None
