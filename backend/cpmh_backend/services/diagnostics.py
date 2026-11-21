from __future__ import annotations

import platform
import shutil

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cpmh_backend.config import Settings
from cpmh_backend.db import database_quick_check
from cpmh_backend.models import LogEntry, as_utc_iso
from cpmh_backend.services.capture import browser_status
from cpmh_backend.services.ocr import tesseract_status
from cpmh_backend.services.translate import argos_available


def summary(session: Session, settings: Settings) -> dict:
    usage = shutil.disk_usage(settings.data_dir)
    errors = session.scalars(select(LogEntry).where(LogEntry.level == "ERROR").order_by(LogEntry.created_at.desc()).limit(8)).all()
    return {
        "app": settings.app_name,
        "version": settings.version,
        "platform": platform.platform(),
        "python": platform.python_version(),
        "database": database_quick_check(settings),
        "database_path": str(settings.database_path),
        "data_dir": str(settings.data_dir),
        "disk_free_bytes": usage.free,
        "disk_total_bytes": usage.total,
        "tesseract": tesseract_status(),
        "browser": browser_status(),
        "translation": {
            "argos_en_pt": argos_available("en", "pt"),
            "argos_zh_pt": argos_available("zh", "pt"),
            "external_requires_consent": True,
        },
        "log_count": session.scalar(select(func.count()).select_from(LogEntry)) or 0,
        "recent_errors": [
            {"id": item.id, "message": item.message, "category": item.category, "created_at": as_utc_iso(item.created_at)}
            for item in errors
        ],
        "windows_installer_tested": False,
    }
