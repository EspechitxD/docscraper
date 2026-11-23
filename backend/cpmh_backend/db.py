from __future__ import annotations

import shutil
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from cpmh_backend.config import Settings, get_settings
from cpmh_backend.logging_setup import setup_logging
from cpmh_backend.models import Base, PreferenceProfile, SchemaMigration, UserPreference, utcnow

SCHEMA_VERSION = 4

DEFAULT_PREFERENCES: dict[str, object] = {
    "ui_language": "pt-BR",
    "default_output_dir": "",
    "default_format": "docx",
    "default_export_mode": "editable",
    "ocr_languages": ["por", "eng", "chi_sim", "chi_tra"],
    "confidence_high": 85,
    "confidence_medium": 60,
    "translation_mode": "none",
    "max_concurrent_jobs": 1,
    "max_pages": 50,
    "max_download_mb": 80,
    "timeout_seconds": 30,
    "domain_timeouts": {},
    "domain_concurrency": 2,
    "retention_days_cache": 14,
    "purge_completed_captures_days": 0,
    "allow_local_network": False,
    "log_level": "INFO",
    "active_profile": "Perfil de trabalho CPMH",
    "external_translation_url": "",
    "external_translation_acknowledged": False,
    "open_folder_after_export": False,
    "theme": "cpmh-industrial",
    "proxy_url": "",
    "operator_name": "",
    "vpn_required": True,
    "vpn_provider": "rasdial",
    "vpn_name": "NOME EXATO DA VPN",
    "vpn_wireguard_conf": "",
}

_engine: Engine | None = None
_Session: sessionmaker[Session] | None = None


def _sqlite_on_connect(dbapi_connection, _connection_record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=3000")
    cursor.close()


def init_db(settings: Settings | None = None) -> Engine:
    global _engine, _Session
    settings = settings or get_settings()
    for directory in (
        settings.data_dir,
        settings.database_path.parent,
        settings.backup_dir,
        settings.projects_dir,
        settings.cache_dir,
        settings.inbox_dir,
        settings.log_dir,
    ):
        directory.mkdir(parents=True, exist_ok=True)
    setup_logging(settings)
    if _engine is None:
        _engine = create_engine(
            f"sqlite:///{settings.database_path}",
            connect_args={"check_same_thread": False},
            future=True,
        )
        event.listen(_engine, "connect", _sqlite_on_connect)
        _Session = sessionmaker(bind=_engine, expire_on_commit=False, autoflush=False, future=True)
    assert _engine is not None
    Base.metadata.create_all(_engine)
    _migrate_additive(_engine)
    with session_scope() as session:
        current = session.scalar(select(SchemaMigration.version).order_by(SchemaMigration.version.desc()))
        if not current:
            session.add(SchemaMigration(version=SCHEMA_VERSION, applied_at=utcnow()))
        elif current < SCHEMA_VERSION:
            session.add(SchemaMigration(version=SCHEMA_VERSION, applied_at=utcnow()))
        _seed(session)
        _recover_interrupted(session)
    _maybe_backup(settings)
    _purge_cache(settings)
    return _engine


def _migrate_additive(engine: Engine) -> None:
    """Acrescenta colunas novas. Não apaga dados nem recria tabelas."""
    with engine.begin() as connection:
        rows = connection.execute(text("PRAGMA table_info(ocr_regions)")).fetchall()
        names = {row[1] for row in rows}
        if names and "evidence" not in names:
            connection.execute(text("ALTER TABLE ocr_regions ADD COLUMN evidence TEXT DEFAULT ''"))
        connection.execute(
            text(
                "CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts USING fts5("
                "chunk_id UNINDEXED, content, tokenize='unicode61')"
            )
        )


def reset_db() -> None:
    global _engine, _Session
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _Session = None
    from cpmh_backend.logging_setup import reset_logging

    reset_logging()


def session() -> Session:
    if _Session is None:
        raise RuntimeError("Banco não inicializado.")
    return _Session()


@contextmanager
def session_scope() -> Iterator[Session]:
    current = session()
    try:
        yield current
        current.commit()
    except Exception:
        current.rollback()
        raise
    finally:
        current.close()


def _seed(session: Session) -> None:
    for key, value in DEFAULT_PREFERENCES.items():
        if session.get(UserPreference, key) is None:
            session.add(UserPreference(key=key, value={"v": value}, updated_at=utcnow()))
    if session.get(PreferenceProfile, "Perfil de trabalho CPMH") is None:
        session.add(
            PreferenceProfile(
                name="Perfil de trabalho CPMH",
                values={key: value for key, value in DEFAULT_PREFERENCES.items()},
                updated_at=utcnow(),
            )
        )
    from cpmh_backend.services.glossary import ensure_starter_glossary

    ensure_starter_glossary(session)


def _recover_interrupted(session: Session) -> None:
    from cpmh_backend.models import Document, ProcessingJob

    active = {"validating", "capturing", "processing", "ocr", "structuring", "extracting_images", "translating", "reconstructing", "exporting"}
    jobs = session.scalars(select(ProcessingJob).where(ProcessingJob.state.in_(active))).all()
    for job in jobs:
        job.state = "paused"
        job.error = "Recuperado após interrupção. A tarefa pode ser retomada a partir do último ponto salvo."
        document = session.get(Document, job.document_id)
        if document is not None and document.state in active:
            document.state = "paused"
            document.error_message = job.error


def _maybe_backup(settings: Settings) -> None:
    if not settings.database_path.exists() or settings.database_path.stat().st_size == 0:
        return
    latest = sorted(settings.backup_dir.glob("cpmh-*.sqlite"))
    if latest:
        age = utcnow().timestamp() - latest[-1].stat().st_mtime
        if age < 20 * 60 * 60:
            return
    stamp = utcnow().strftime("%Y%m%d-%H%M%S")
    destination = settings.backup_dir / f"cpmh-{stamp}.sqlite"
    source = sqlite3.connect(settings.database_path)
    target = sqlite3.connect(destination)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()
    backups = sorted(settings.backup_dir.glob("cpmh-*.sqlite"))
    for old in backups[:-5]:
        old.unlink(missing_ok=True)


def _purge_cache(settings: Settings) -> None:
    with session_scope() as current:
        row = current.get(UserPreference, "retention_days_cache")
        days = 14
        if row and isinstance(row.value, dict):
            days = int(row.value.get("v", 14) or 0)
    if days <= 0 or not settings.cache_dir.exists():
        return
    cutoff = utcnow().timestamp() - days * 86400
    for path in settings.cache_dir.rglob("*"):
        if path.is_file() and path.stat().st_mtime < cutoff:
            path.unlink(missing_ok=True)


def backup_now(settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    settings.backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = utcnow().strftime("%Y%m%d-%H%M%S")
    destination = settings.backup_dir / f"cpmh-{stamp}.sqlite"
    if not settings.database_path.exists():
        raise FileNotFoundError(settings.database_path)
    source = sqlite3.connect(settings.database_path)
    target = sqlite3.connect(destination)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()
    return str(destination)


def preference_value(session: Session, key: str):
    row = session.get(UserPreference, key)
    if row is None:
        return DEFAULT_PREFERENCES.get(key)
    if isinstance(row.value, dict) and "v" in row.value:
        return row.value["v"]
    return row.value


def set_preference(session: Session, key: str, value) -> None:
    row = session.get(UserPreference, key)
    if row is None:
        session.add(UserPreference(key=key, value={"v": value}, updated_at=utcnow()))
    else:
        row.value = {"v": value}
        row.updated_at = utcnow()


def repair(settings: Settings | None = None) -> dict:
    settings = settings or get_settings()
    for directory in (
        settings.data_dir,
        settings.database_path.parent,
        settings.backup_dir,
        settings.projects_dir,
        settings.cache_dir,
        settings.inbox_dir,
        settings.log_dir,
    ):
        directory.mkdir(parents=True, exist_ok=True)
    init_db(settings)
    removed = 0
    inbox = settings.inbox_dir
    if inbox.exists():
        for path in inbox.iterdir():
            if path.is_file() and path.suffix == ".tmp":
                path.unlink()
                removed += 1
    return {"ok": True, "directories": True, "temporary_files_removed": removed}


def remove_tree(path) -> None:
    target = path if hasattr(path, "exists") else None
    if target is not None and target.exists():
        shutil.rmtree(target, ignore_errors=True)


def database_quick_check(settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    if not settings.database_path.exists():
        return "ausente"
    connection = sqlite3.connect(settings.database_path)
    try:
        row = connection.execute("PRAGMA quick_check").fetchone()
    finally:
        connection.close()
    return row[0] if row else "desconhecido"


# Import side effect guard: glossary seed imports db only inside functions.
_ = text

