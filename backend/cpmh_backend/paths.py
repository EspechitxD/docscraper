from __future__ import annotations

from pathlib import Path

from cpmh_backend.config import Settings


def document_dir(settings: Settings, project_id: str, document_id: str) -> Path:
    path = settings.projects_dir / project_id / document_id
    (path / "pages").mkdir(parents=True, exist_ok=True)
    (path / "images").mkdir(parents=True, exist_ok=True)
    (path / "original").mkdir(parents=True, exist_ok=True)
    return path
