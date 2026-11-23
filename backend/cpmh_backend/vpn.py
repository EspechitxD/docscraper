"""VPN corporativa: verificação, conexão e bloqueio de acesso sem VPN.

O aplicativo não cria nem fornece uma VPN. Ele usa a VPN que a TI da empresa
disponibiliza e se recusa a acessar endereços externos enquanto ela não estiver ativa.
Uma VPN fixa por sessão: não há troca de servidor nem rodízio de IP.

Provedores:
  rasdial    VPN nativa do Windows (Configurações > VPN). Conecta e desconecta pelo app.
  wireguard  Túnel WireGuard a partir de um arquivo .conf da TI. Conectar exige administrador.
  adapter    Qualquer cliente de VPN que crie um adaptador de rede (OpenVPN, FortiClient...).
             O app só verifica se o adaptador está ativo; quem conecta é o cliente da empresa.

Linha de comando (na pasta backend):
  python -m cpmh_backend.vpn configure --provider rasdial --name "VPN CPMH"
  python -m cpmh_backend.vpn status | connect | disconnect
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from cpmh_backend.errors import AppError, VpnRequired

PROVIDERS = ("none", "rasdial", "wireguard", "adapter")
_NAME_RE = re.compile(r"^[\w .\-()]{1,64}$", re.UNICODE)
_TTL = 10.0
_NO_WINDOW = 0x08000000 if os.name == "nt" else 0
_lock = threading.Lock()
_cache: dict = {"key": None, "at": 0.0, "value": None}


@dataclass(frozen=True)
class VpnConfig:
    required: bool
    provider: str
    name: str
    wireguard_conf: str


def load_config() -> VpnConfig:
    from cpmh_backend.db import preference_value, session_scope

    with session_scope() as db:
        return VpnConfig(
            required=bool(preference_value(db, "vpn_required")),
            provider=str(preference_value(db, "vpn_provider") or "none"),
            name=str(preference_value(db, "vpn_name") or ""),
            wireguard_conf=str(preference_value(db, "vpn_wireguard_conf") or ""),
        )


def _run(args: list[str], *, env: dict | None = None, timeout: float = 20) -> tuple[int, str]:
    try:
        done = subprocess.run(
            args,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout,
            creationflags=_NO_WINDOW,
            env=env,
        )
    except FileNotFoundError:
        return 127, "programa não encontrado"
    except subprocess.TimeoutExpired:
        return 124, "tempo esgotado"
    return done.returncode, (done.stdout or "") + (done.stderr or "")


def _wireguard_exe() -> str | None:
    for base in (os.environ.get("ProgramFiles"), r"C:\Program Files"):
        if base:
            candidate = Path(base) / "WireGuard" / "wireguard.exe"
            if candidate.is_file():
                return str(candidate)
    return None


def _probe(cfg: VpnConfig) -> tuple[bool, str]:
    if cfg.provider == "none":
        return False, "Nenhuma VPN configurada."
    if os.name != "nt":
        return False, "A verificação de VPN só é suportada no Windows."
    if not cfg.name:
        return False, "Falta o nome da conexão VPN."
    if cfg.provider == "rasdial":
        _code, out = _run(["rasdial"])
        active = cfg.name in {line.strip() for line in out.splitlines()}
        return active, "Conexão ativa." if active else "A conexão VPN não está ativa."
    if cfg.provider == "wireguard":
        code, out = _run(["sc.exe", "query", f"WireGuardTunnel${cfg.name}"])
        active = code == 0 and "RUNNING" in out.upper()
        return active, "Túnel ativo." if active else "O túnel WireGuard não está ativo."
    if cfg.provider == "adapter":
        env = dict(os.environ, CPMH_VPN_NAME=cfg.name)
        script = (
            "if (Get-NetAdapter -Name $env:CPMH_VPN_NAME -ErrorAction SilentlyContinue "
            "| Where-Object { $_.Status -eq 'Up' }) { exit 0 } else { exit 1 }"
        )
        code, _out = _run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], env=env)
        active = code == 0
        return active, "Adaptador ativo." if active else "O adaptador de VPN não está ativo."
    return False, "Tipo de VPN desconhecido."


def _status(cfg: VpnConfig, *, force: bool = False) -> dict:
    key = (cfg.provider, cfg.name, cfg.wireguard_conf)
    now = time.monotonic()
    with _lock:
        if not force and _cache["key"] == key and now - _cache["at"] < _TTL:
            return {**_cache["value"], "required": cfg.required}
    connected, detail = _probe(cfg)
    value = {
        "provider": cfg.provider,
        "name": cfg.name,
        "connected": connected,
        "detail": detail,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
    with _lock:
        _cache.update(key=key, at=time.monotonic(), value=value)
    return {**value, "required": cfg.required}


def _reset_cache() -> None:
    with _lock:
        _cache.update(key=None, at=0.0, value=None)


def status(*, force: bool = False) -> dict:
    return _status(load_config(), force=force)


def audit_label() -> str:
    """Texto para o registro de auditoria. Não inclui IP, senha nem caminho de arquivo."""
    try:
        cfg = load_config()
        if cfg.provider == "none":
            return "sem vpn"
        state = "ativa" if _status(cfg)["connected"] else "inativa"
        return f"vpn {cfg.provider}:{cfg.name} ({state})"
    except Exception:
        return "vpn indisponível"


def ensure_vpn() -> None:
    """Chamado antes de qualquer URL ser aceita. Falha fechada: sem VPN, sem acesso."""
    try:
        cfg = load_config()
    except Exception as exc:
        raise VpnRequired("Não foi possível verificar a VPN. Nenhum endereço foi acessado.") from exc
    if not cfg.required:
        return
    current = _status(cfg)
    if not current["connected"]:
        raise VpnRequired(
            f"A VPN da empresa não está ativa ({current['detail']}). "
            "Conecte a VPN e tente de novo. Nenhum endereço foi acessado."
        )


def _unsupported(cfg: VpnConfig) -> None:
    if cfg.provider == "none" or not cfg.name:
        raise AppError("Configure a VPN antes de conectar.", status_code=409, code="vpn_not_configured")
    if os.name != "nt":
        raise AppError("Conectar a VPN só é suportado no Windows.", status_code=409, code="vpn_unsupported")


def connect() -> dict:
    cfg = load_config()
    _unsupported(cfg)
    if _status(cfg, force=True)["connected"]:
        return _status(cfg)
    if cfg.provider == "rasdial":
        code, out = _run(["rasdial", cfg.name], timeout=60)
    elif cfg.provider == "wireguard":
        exe = _wireguard_exe()
        if not exe:
            raise AppError("WireGuard não encontrado neste computador.", status_code=409, code="vpn_missing_client")
        if not Path(cfg.wireguard_conf).is_file():
            raise AppError("O arquivo .conf do túnel não foi encontrado.", status_code=409, code="vpn_missing_conf")
        code, out = _run([exe, "/installtunnelservice", cfg.wireguard_conf], timeout=60)
    else:
        raise AppError(
            "Esta VPN é conectada pelo cliente da empresa. Conecte por ele e verifique de novo.",
            status_code=409,
            code="vpn_manual_connect",
        )
    if code != 0:
        hint = " Execute o aplicativo como administrador." if cfg.provider == "wireguard" else ""
        raise AppError(f"A conexão VPN falhou: {out.strip()[:200]}.{hint}", status_code=502, code="vpn_connect_failed")
    time.sleep(1.5)
    return _status(cfg, force=True)


def disconnect() -> dict:
    cfg = load_config()
    _unsupported(cfg)
    if cfg.provider == "rasdial":
        code, out = _run(["rasdial", cfg.name, "/disconnect"], timeout=60)
    elif cfg.provider == "wireguard":
        exe = _wireguard_exe()
        if not exe:
            raise AppError("WireGuard não encontrado neste computador.", status_code=409, code="vpn_missing_client")
        code, out = _run([exe, "/uninstalltunnelservice", cfg.name], timeout=60)
    else:
        raise AppError(
            "Desconecte pelo cliente da empresa.", status_code=409, code="vpn_manual_connect"
        )
    if code != 0:
        raise AppError(f"A desconexão falhou: {out.strip()[:200]}", status_code=502, code="vpn_disconnect_failed")
    return _status(cfg, force=True)


def configure(*, required: bool, provider: str, name: str = "", wireguard_conf: str = "") -> dict:
    from cpmh_backend.db import session_scope, set_preference

    provider = (provider or "none").strip().lower()
    name = (name or "").strip()
    wireguard_conf = (wireguard_conf or "").strip().strip('"')
    if provider not in PROVIDERS:
        raise AppError(f"Tipo de VPN inválido. Use: {', '.join(PROVIDERS)}.", code="vpn_invalid")
    if provider == "wireguard":
        conf = Path(wireguard_conf)
        if conf.suffix.lower() != ".conf" or not conf.is_file():
            raise AppError("Informe o caminho de um arquivo .conf existente.", code="vpn_invalid")
        name = conf.stem
    if provider != "none" and not _NAME_RE.fullmatch(name):
        raise AppError("Nome da VPN inválido (até 64 letras, números, espaço, ponto, hífen).", code="vpn_invalid")
    if provider == "none":
        name, required = "", False
    with session_scope() as db:
        set_preference(db, "vpn_required", bool(required))
        set_preference(db, "vpn_provider", provider)
        set_preference(db, "vpn_name", name)
        set_preference(db, "vpn_wireguard_conf", wireguard_conf if provider == "wireguard" else "")
    _reset_cache()
    return status(force=True)


def _cli(argv: list[str]) -> int:
    import argparse

    os.environ.setdefault("CPMH_API_TOKEN", "cli-local")
    from cpmh_backend.config import get_settings
    from cpmh_backend.db import init_db

    parser = argparse.ArgumentParser(prog="python -m cpmh_backend.vpn")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("status")
    sub.add_parser("connect")
    sub.add_parser("disconnect")
    conf = sub.add_parser("configure")
    conf.add_argument("--provider", required=True, choices=PROVIDERS)
    conf.add_argument("--name", default="")
    conf.add_argument("--conf", default="")
    conf.add_argument("--optional", action="store_true", help="não bloquear a captura sem VPN")
    args = parser.parse_args(argv)

    init_db(get_settings())
    try:
        if args.command == "configure":
            result = configure(required=not args.optional, provider=args.provider, name=args.name, wireguard_conf=args.conf)
        elif args.command == "connect":
            result = connect()
        elif args.command == "disconnect":
            result = disconnect()
        else:
            result = status(force=True)
    except AppError as exc:
        print(f"Erro: {exc.message}")
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
