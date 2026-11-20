from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urljoin

import httpx

from cpmh_backend.errors import HttpAccess, UrlRejected
from cpmh_backend.security import Resolver, validate_url

USER_AGENT = "CPMHDocumentIntelligence/0.1 (authorized desktop capture)"


@dataclass
class FetchResult:
    url: str
    final_url: str
    data: bytes
    content_type: str
    kind: str


def sniff_kind(data: bytes, content_type: str) -> str:
    if data.startswith(b"%PDF-"):
        return "pdf"
    if data.startswith(b"\x89PNG"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "webp"
    if data.startswith(b"MZ") or data.startswith(b"\x7fELF"):
        raise UrlRejected("O endereço devolveu um executável. O download foi interrompido.")
    if "html" in content_type.lower() or data.lstrip()[:1] in {b"<", b""} or data.lstrip().lower().startswith(b"<!doctype"):
        return "html"
    if "pdf" in content_type.lower():
        return "pdf"
    return "other"


def fetch_url(
    url: str,
    *,
    allow_local: bool,
    max_bytes: int,
    timeout: float,
    client: httpx.Client | None = None,
    resolver: Resolver | None = None,
    max_redirects: int = 5,
) -> FetchResult:
    owns_client = client is None
    current = url
    client = client or httpx.Client(timeout=timeout, follow_redirects=False, headers={"User-Agent": USER_AGENT})
    try:
        for _hop in range(max_redirects + 1):
            validated = validate_url(current, allow_local=allow_local, resolver=resolver)
            with client.stream("GET", validated.url, follow_redirects=False) as response:
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location")
                    if not location:
                        raise UrlRejected("Redirecionamento sem destino.")
                    current = urljoin(validated.url, location)
                    continue
                if response.status_code >= 400:
                    snippet = ""
                    if response.status_code in {401, 403, 429, 503}:
                        raw = bytearray()
                        for chunk in response.iter_bytes():
                            raw.extend(chunk)
                            if len(raw) >= 4000:
                                break
                        snippet = raw[:4000].decode("utf-8", errors="replace")
                    raise HttpAccess(response.status_code, validated.url, snippet)
                chunks: list[bytes] = []
                total = 0
                for chunk in response.iter_bytes():
                    total += len(chunk)
                    if total > max_bytes:
                        raise UrlRejected("O download excedeu o limite configurado.")
                    chunks.append(chunk)
                data = b"".join(chunks)
                content_type = response.headers.get("content-type", "")
                kind = sniff_kind(data, content_type)
                return FetchResult(validated.url, str(response.url), data, content_type, kind)
        raise UrlRejected("A URL excedeu o número de redirecionamentos permitido.")
    finally:
        if owns_client:
            client.close()
