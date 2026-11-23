"""Diagnóstico e recuperação legítima de documentos em visualizadores web.

`diagnose_url` inspeciona a página no Chromium e escolhe a estratégia. Ele não executa nenhuma
recuperação que dependa de ultrapassar CAPTCHA, login ou pagamento: nesses casos pausa e explica.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from cpmh_backend.errors import AppError, UrlRejected
from cpmh_backend.services.browser_inspector import inspect_url
from cpmh_backend.services.document_source_analyzer import analyze_source


def diagnose_observation(observation: dict) -> dict:
    report = analyze_source(observation)
    report["analyzed_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    report["method"] = "observação do navegador"
    report["summary"] = summarize(report)
    return report


def diagnose_url(url: str, *, timeout: float = 25.0) -> dict:
    """Análise real no Chromium. Sem Chrome, devolve o erro: nunca um resultado inventado."""
    try:
        observation = inspect_url(url, timeout=timeout)
    except (RuntimeError, UrlRejected, AppError) as exc:
        return {
            "url": url,
            "primary_state": "processing_failed",
            "states": ["processing_failed"],
            "conclusive": False,
            "error": str(exc),
            "summary": f"Análise não executada: {exc}",
            "analyzed_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        }
    return diagnose_observation(observation)


def summarize(report: dict) -> str:
    pages = report.get("pages", {})
    reported = pages.get("reported_by_site")
    accessible = pages.get("accessible")
    text = report.get("text", {})
    lines = [
        f"Estado: {report['primary_state']} (visualizador: {report['viewer_type']}).",
        f"Páginas informadas pelo site: {reported if reported is not None else 'não informado'}.",
        f"Páginas acessíveis: {accessible if accessible is not None else 'não verificado'}. Páginas processadas: {pages.get('processed', 0)}.",
        f"Caracteres documentais: {text.get('document_chars', 0)}. Caracteres de interface descartados: {text.get('interface_chars_discarded', 0)}.",
        f"Estratégia {report['strategy']['code']}: {report['strategy']['action']}",
    ]
    if report.get("restrictions"):
        lines.append("Restrições: " + ", ".join(report["restrictions"]) + ".")
    return "\n".join(lines)


def save_report(report: dict, path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf8")
    return path
