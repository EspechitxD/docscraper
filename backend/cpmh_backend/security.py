"""Política de URL, SSRF e validação de arquivos importados.

O aplicativo só busca endereços que o usuário informou. Não contorna
autenticação, paywall ou DRM. Destinos privados, de loopback e de
metadados de infraestrutura são recusados, salvo configuração explícita
de rede local, desligada por padrão.
"""

from __future__ import annotations

import ipaddress
import os
import re
import socket
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from cpmh_backend.errors import AppError, UrlRejected

MAX_URL_LENGTH = 2048
BLOCKED_HOSTS = {
    "localhost",
    "localhost.localdomain",
    "metadata.google.internal",
    "metadata.google.com",
    "metadata",
}

FILE_SIGNATURES: dict[str, tuple[bytes, ...]] = {
    ".pdf": (b"%PDF-",),
    ".png": (b"\x89PNG\r\n\x1a\n",),
    ".jpg": (b"\xff\xd8\xff",),
    ".jpeg": (b"\xff\xd8\xff",),
    ".webp": (b"RIFF",),
    ".bmp": (b"BM",),
    ".tif": (b"II*\x00", b"MM\x00*"),
    ".tiff": (b"II*\x00", b"MM\x00*"),
    ".txt": (),
    ".csv": (),
}

Resolver = Callable[[str], list[str]]


@dataclass(frozen=True)
class ValidatedUrl:
    url: str
    host: str
    ips: tuple[str, ...]


def _default_resolver(host: str) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise UrlRejected(f"Não foi possível resolver o endereço: {host}") from exc
    ips: list[str] = []
    for info in infos:
        ip = info[4][0]
        if ip not in ips:
            ips.append(ip)
    if not ips:
        raise UrlRejected(f"O endereço não possui IP utilizável: {host}")
    return ips


def _parse_literal_ip(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    candidate = host.strip().strip("[]")
    try:
        return ipaddress.ip_address(candidate)
    except ValueError:
        pass
    if re.fullmatch(r"\d{1,10}", candidate):
        try:
            return ipaddress.ip_address(int(candidate))
        except ValueError:
            return None
    parts = candidate.split(".")
    if not parts or len(parts) > 4:
        return None
    if not all(re.fullmatch(r"0x[0-9a-fA-F]+|\d+", part) for part in parts):
        return None
    numbers: list[int] = []
    for part in parts:
        try:
            if part.lower().startswith("0x"):
                numbers.append(int(part, 16))
            elif len(part) > 1 and part.startswith("0") and part.isdigit():
                numbers.append(int(part, 8))
            else:
                numbers.append(int(part, 10))
        except ValueError:
            return None
    if len(numbers) == 1:
        value = numbers[0]
    elif len(numbers) == 2:
        value = (numbers[0] << 24) | numbers[1]
    elif len(numbers) == 3:
        value = (numbers[0] << 24) | (numbers[1] << 16) | numbers[2]
    else:
        value = (numbers[0] << 24) | (numbers[1] << 16) | (numbers[2] << 8) | numbers[3]
    try:
        return ipaddress.ip_address(value)
    except ValueError:
        return None


def ip_is_blocked(ip: ipaddress.IPv4Address | ipaddress.IPv6Address, *, allow_local: bool) -> bool:
    if ip.version == 6 and getattr(ip, "ipv4_mapped", None) is not None:
        ip = ip.ipv4_mapped
    if not allow_local:
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            return True
    # Metadados de nuvem permanecem bloqueados mesmo com rede local liberada.
    if ip.version == 4 and ip in ipaddress.ip_network("169.254.169.254/32"):
        return True
    if ip.is_multicast or ip.is_unspecified or ip.is_reserved:
        return True
    return False


def normalize_url(url: str) -> str:
    raw = url.strip()
    if not raw or len(raw) > MAX_URL_LENGTH:
        raise UrlRejected("A URL está vazia ou excede o tamanho permitido.")
    parts = urlsplit(raw)
    if parts.scheme.lower() not in {"http", "https"}:
        raise UrlRejected("Somente endereços http e https são aceitos.")
    if parts.username or parts.password:
        raise UrlRejected("URLs com usuário ou senha não são aceitas.")
    host = parts.hostname
    if not host:
        raise UrlRejected("A URL não possui servidor.")
    host = host.rstrip(".").lower()
    try:
        host_idna = host.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise UrlRejected("O nome do servidor é inválido.") from exc
    port = parts.port
    if (parts.scheme.lower() == "http" and port == 80) or (parts.scheme.lower() == "https" and port == 443):
        port = None
    netloc = host_idna if port is None else f"{host_idna}:{port}"
    if ":" in host_idna and not host_idna.startswith("["):
        netloc = f"[{host_idna}]" if port is None else f"[{host_idna}]:{port}"
    path = parts.path or "/"
    if path != "/" and path.endswith("/"):
        path = path[:-1]
    return urlunsplit((parts.scheme.lower(), netloc, path, parts.query, ""))


def validate_url(url: str, *, allow_local: bool = False, resolver: Resolver | None = None) -> ValidatedUrl:
    normalized = normalize_url(url)
    parts = urlsplit(normalized)
    host = parts.hostname or ""
    if host in BLOCKED_HOSTS and not allow_local:
        raise UrlRejected("Endereços locais e de metadados estão bloqueados.")
    literal = _parse_literal_ip(host)
    if literal is not None:
        if ip_is_blocked(literal, allow_local=allow_local):
            raise UrlRejected("O endereço aponta para uma rede bloqueada.")
        return ValidatedUrl(normalized, host, (str(literal),))
    if host in BLOCKED_HOSTS:
        raise UrlRejected("Endereços locais e de metadados estão bloqueados.")
    resolve = resolver or _default_resolver
    ips = resolve(host)
    parsed_ips = []
    for value in ips:
        try:
            parsed_ips.append(ipaddress.ip_address(value))
        except ValueError as exc:
            raise UrlRejected("A resolução de DNS devolveu um IP inválido.") from exc
    if any(ip_is_blocked(ip, allow_local=allow_local) for ip in parsed_ips):
        raise UrlRejected("O endereço resolve para uma rede bloqueada.")
    if not parsed_ips:
        raise UrlRejected("Não foi possível confirmar o destino da URL.")
    return ValidatedUrl(normalized, host, tuple(str(ip) for ip in parsed_ips))


def domain_of(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""


def user_output_dir(install_dir: Path | None = None) -> Path:
    """Pasta de exportação fora do aplicativo e das pastas do sistema."""
    home = Path.home()
    for name in ("Documents", "Documentos", "Downloads"):
        folder = home / name / "CPMH"
        if not _path_is_forbidden(folder, install_dir):
            return folder
    return home / "CPMH"


def prepare_output_dir(path: str | Path | None, *, install_dir: Path | None = None) -> Path:
    text = str(path or "").strip()
    if text:
        return assert_output_dir_allowed(Path(text).expanduser(), install_dir=install_dir)
    chosen = user_output_dir(install_dir)
    if _path_is_forbidden(chosen, install_dir):
        raise AppError(f"Não há uma pasta de destino segura. Crie uma pasta fora do aplicativo, por exemplo {chosen}.")
    chosen.mkdir(parents=True, exist_ok=True)
    return assert_output_dir_allowed(chosen, install_dir=install_dir)


def _path_is_forbidden(path: Path, install_dir: Path | None) -> bool:
    try:
        resolved = path.expanduser().resolve()
    except OSError:
        return True
    for root in _forbidden_output_roots(install_dir):
        if resolved == root or root in resolved.parents:
            return True
    return False


def _forbidden_output_roots(install_dir: Path | None) -> list[Path]:
    roots: list[Path] = []
    if os.name == "nt":
        windows = os.environ.get("SystemRoot", r"C:\Windows")
        roots.extend([Path(windows), Path(r"C:\Windows"), Path(r"C:\Program Files"), Path(r"C:\Program Files (x86)")])
    else:
        roots.extend(
            [Path("/etc"), Path("/usr"), Path("/bin"), Path("/sbin"), Path("/proc"), Path("/sys"), Path("/dev"), Path("/boot")]
        )
    if install_dir is not None:
        roots.append(install_dir.expanduser().resolve())
    return roots


def assert_output_dir_allowed(path: Path, *, install_dir: Path | None = None) -> Path:
    try:
        resolved = path.expanduser().resolve()
    except OSError as exc:
        raise AppError("A pasta de destino é inválida.") from exc
    if _path_is_forbidden(resolved, install_dir):
        raise AppError(
            f"Essa pasta fica dentro do aplicativo ou de uma pasta do sistema. Escolha outra, por exemplo {user_output_dir(install_dir)}."
        )
    if not resolved.exists():
        if not resolved.parent.exists():
            raise AppError("A pasta pai do destino não existe.")
        resolved.mkdir(parents=False, exist_ok=False)
    if not resolved.is_dir():
        raise AppError("O destino precisa ser uma pasta.")
    return resolved


_NAME_RE = re.compile(r"[^\w.\- ()]+", re.UNICODE)


def safe_filename(name: str) -> str:
    base = Path(name).name.strip()
    base = _NAME_RE.sub("_", base).strip(" .")
    if not base or base in {".", ".."}:
        raise AppError("Nome de arquivo inválido.")
    return base[:180]


def validate_import_bytes(filename: str, data: bytes, *, max_bytes: int) -> str:
    if len(data) > max_bytes:
        raise AppError("O arquivo importado excede o limite configurado.")
    if not data:
        raise AppError("O arquivo importado está vazio.")
    suffix = Path(filename).suffix.lower()
    if suffix not in FILE_SIGNATURES:
        raise AppError("Extensão de arquivo não permitida.")
    if data.startswith(b"MZ") or data.startswith(b"\x7fELF") or data.startswith(b"#!"):
        raise AppError("O arquivo parece executável e foi recusado.")
    if b"\x00" in data and suffix in {".txt", ".csv"}:
        raise AppError("O arquivo de texto contém bytes nulos.")
    signatures = FILE_SIGNATURES[suffix]
    if signatures and not any(data.startswith(sig) for sig in signatures):
        raise AppError("O conteúdo do arquivo não corresponde à extensão.")
    if suffix == ".webp" and data[8:12] != b"WEBP":
        raise AppError("O arquivo WebP é inválido.")
    return suffix
