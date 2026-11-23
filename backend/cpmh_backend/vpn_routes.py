"""Rotas da VPN. Usam o mesmo token local da API."""

from __future__ import annotations

import hmac

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

from cpmh_backend import vpn
from cpmh_backend.config import get_settings
from cpmh_backend.errors import AppError


def _auth(
    authorization: str | None = Header(default=None),
    x_cpmh_token: str | None = Header(default=None),
    x_api_token: str | None = Header(default=None),
) -> None:
    supplied = x_cpmh_token or x_api_token or ""
    if not supplied and authorization and authorization.lower().startswith("bearer "):
        supplied = authorization[7:].strip()
    if not hmac.compare_digest(supplied.encode(), get_settings().token.encode()):
        raise HTTPException(status_code=401, detail={"code": "unauthorized", "message": "Token inválido."})


router = APIRouter(prefix="/vpn", tags=["vpn"], dependencies=[Depends(_auth)])


class VpnConfigBody(BaseModel):
    required: bool
    provider: str
    name: str = ""
    wireguard_conf: str = ""


def _guard(call):
    try:
        return call()
    except AppError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.message}) from exc


@router.get("/status")
def get_status() -> dict:
    return _guard(lambda: vpn.status(force=True))


@router.get("/config")
def get_config() -> dict:
    cfg = vpn.load_config()
    return {"required": cfg.required, "provider": cfg.provider, "name": cfg.name, "wireguard_conf": cfg.wireguard_conf}


@router.put("/config")
def put_config(body: VpnConfigBody) -> dict:
    return _guard(
        lambda: vpn.configure(
            required=body.required, provider=body.provider, name=body.name, wireguard_conf=body.wireguard_conf
        )
    )


@router.post("/connect")
def post_connect() -> dict:
    return _guard(vpn.connect)


@router.post("/disconnect")
def post_disconnect() -> dict:
    return _guard(vpn.disconnect)
