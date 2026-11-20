from __future__ import annotations

import os
import sys
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field

from cpmh_backend import __version__


def default_data_dir() -> Path:
    override = os.environ.get("CPMH_DATA_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    if os.name == "nt":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / "CPMH Document Intelligence"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "CPMH Document Intelligence"
    return Path.home() / ".local" / "share" / "cpmh-document-intelligence"


class Settings(BaseModel):
    app_name: str = "CPMH Document Intelligence"
    version: str = __version__
    host: str = "127.0.0.1"
    port: int = 8765
    token: str
    data_dir: Path
    allow_local_network: bool = False
    static_dir: Path | None = None
    log_level: str = "INFO"
    install_dir: Path = Field(default_factory=lambda: Path(__file__).resolve().parents[2])

    @property
    def database_path(self) -> Path:
        return self.data_dir / "database" / "cpmh.sqlite"

    @property
    def log_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def backup_dir(self) -> Path:
        return self.data_dir / "database" / "backups"

    @property
    def projects_dir(self) -> Path:
        return self.data_dir / "projects"

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"

    @property
    def inbox_dir(self) -> Path:
        return self.data_dir / "inbox"


@lru_cache
def get_settings() -> Settings:
    token = os.environ.get("CPMH_API_TOKEN", "").strip()
    if not token:
        raise RuntimeError("CPMH_API_TOKEN não definido. O backend não inicia sem o token local.")
    host = os.environ.get("CPMH_HOST", "127.0.0.1").strip() or "127.0.0.1"
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise RuntimeError("O backend só pode escutar em loopback.")
    static = os.environ.get("CPMH_STATIC_DIR", "").strip()
    return Settings(
        host=host,
        port=int(os.environ.get("CPMH_PORT", "8765")),
        token=token,
        data_dir=default_data_dir(),
        allow_local_network=os.environ.get("CPMH_ALLOW_LOCAL_NETWORK", "").lower() in {"1", "true", "yes"},
        static_dir=Path(static) if static else None,
        log_level=os.environ.get("CPMH_LOG_LEVEL", "INFO").upper(),
    )
