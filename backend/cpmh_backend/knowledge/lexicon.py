"""Expansão lexical local. Não é treinamento nem um modelo de linguagem."""

from __future__ import annotations

# Cada grupo acrescenta termos de consulta. Não entra na resposta.
GROUPS = (
    ("resistência à tração", "resistencia a tracao", "tração", "tracao", "ruptura", "força antes de romper", "forca antes de romper", "tensão de ruptura"),
    ("manufatura aditiva", "impressão 3d", "impressao 3d", "impressão tridimensional"),
    ("avaliação externa", "avaliacao externa", "inspeção escolar", "inspecao escolar"),
    ("educação inclusiva", "educacao inclusiva", "práticas inclusivas", "praticas inclusivas"),
    ("objetivo", "objetivos", "finalidade", "propósito", "proposito", "pretende", "visa"),
    ("metodologia", "metodológico", "metodologicos", "procedimento", "procedimentos", "método", "metodo"),
)


def expand_query(text: str) -> str:
    folded = text.lower()
    extra: list[str] = []
    for group in GROUPS:
        if any(term in folded for term in group):
            extra.extend(group)
    if not extra:
        return text
    return text + "\n" + " ".join(extra)
