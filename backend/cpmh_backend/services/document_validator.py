"""Validação antes da exportação e nota de qualidade: Excelente, Boa, Parcial ou Insuficiente."""

from __future__ import annotations

from collections import Counter

from cpmh_backend.services.capture import looks_like_interface_text
from cpmh_backend.services.document_statistics import page_statistics

QUALITIES = ("Excelente", "Boa", "Parcial", "Insuficiente")


def validate_extraction(
    pages: list[dict],
    *,
    reported_pages: int | None = None,
    accessible_pages: int | None = None,
    tables: list[list[list[str]]] | None = None,
) -> dict:
    """Valida o que foi realmente extraído. `reported_pages` é só metadado do site."""
    stats = page_statistics(pages)
    issues: list[dict] = []
    processed = stats["pages_processed"]

    def issue(code: str, severity: str, message: str) -> None:
        issues.append({"code": code, "severity": severity, "message": message})

    # Interface no lugar de documento.
    interface_pages = [
        page.get("sequence")
        for page in pages
        if looks_like_interface_text([line for line in str(page.get("text") or "").splitlines() if line.strip()])
    ]
    if interface_pages:
        issue("interface_text", "error", f"Páginas com cara de interface do site: {interface_pages[:10]}")

    # Páginas vazias.
    empty_ratio = stats["pages_without_text"] / processed if processed else 1.0
    if processed and stats["pages_without_text"]:
        issue("empty_pages", "warning" if empty_ratio <= 0.25 else "error", f"{stats['pages_without_text']} de {processed} páginas sem texto reconhecível.")

    # Cobertura.
    expected = accessible_pages if accessible_pages is not None else reported_pages
    if reported_pages and processed < reported_pages:
        issue("coverage", "warning", f"O site informa {reported_pages} páginas; foram processadas {processed}.")
    if accessible_pages is not None and processed < accessible_pages:
        issue("accessible_not_processed", "error", f"{accessible_pages} páginas acessíveis, só {processed} processadas.")

    # Repetição excessiva: a mesma linha em muitas páginas (menu repetido, marca d'água).
    lines = Counter()
    for page in pages:
        for line in {line.strip() for line in str(page.get("text") or "").splitlines() if len(line.strip()) > 12}:
            lines[line] += 1
    repeated = sum(1 for count in lines.values() if processed >= 3 and count >= max(3, processed * 0.6))
    total_lines = max(len(lines), 1)
    if repeated and repeated / total_lines > 0.3:
        issue("repetition", "warning", "Muitas linhas se repetem na maior parte das páginas.")

    # Continuidade de numeração.
    numbers = [int(page["reported_number"]) for page in pages if str(page.get("reported_number") or "").isdigit()]
    if len(numbers) >= 3 and any(b - a > 1 for a, b in zip(numbers, numbers[1:])):
        issue("continuity", "warning", "Salto na numeração das páginas capturadas.")

    # Tabelas: todas as linhas com o mesmo número de colunas.
    for index, rows in enumerate(tables or [], start=1):
        widths = {len(row) for row in rows}
        if len(widths) > 1:
            issue("table_integrity", "warning", f"Tabela {index} com linhas de larguras diferentes: {sorted(widths)}.")

    # Qualidade do OCR.
    confidences = [float(page["confidence"]) for page in pages if page.get("confidence") not in (None, "")]
    avg_conf = sum(confidences) / len(confidences) if confidences else None
    if avg_conf is not None and avg_conf < 60:
        issue("ocr_quality", "warning", f"Confiança média do OCR baixa ({avg_conf:.0f}).")

    errors = [item for item in issues if item["severity"] == "error"]
    if processed == 0 or stats["document_chars"] < 200 or interface_pages and len(interface_pages) >= max(1, processed // 2):
        quality = "Insuficiente"
    elif errors or empty_ratio > 0.25 or (expected and processed < expected) or (reported_pages and processed < reported_pages):
        quality = "Parcial"
    elif issues or empty_ratio > 0.1 or (avg_conf is not None and avg_conf < 75):
        quality = "Boa"
    elif avg_conf is not None and avg_conf < 85:
        quality = "Boa"
    else:
        quality = "Excelente"
    return {
        "quality": quality,
        "issues": issues,
        "statistics": stats,
        "pages": {
            "reported_by_site": reported_pages,
            "accessible": accessible_pages,
            "processed": processed,
            "with_text": stats["pages_with_text"],
            "without_text": stats["pages_without_text"],
        },
        "average_confidence": round(avg_conf, 1) if avg_conf is not None else None,
        "safe_to_export": quality in {"Excelente", "Boa"},
    }
