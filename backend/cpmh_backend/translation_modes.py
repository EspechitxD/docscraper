"""Contrato único dos modos de tradução.

A interface antiga enviava `portuguese` e `selected`. A exportação lia
`portuguese_only` e `selection`. Os aliases continuam aceitos e são
convertidos para o identificador canônico.
"""

from __future__ import annotations

CANONICAL_MODES = ("none", "selected_regions", "document_pt_br", "bilingual")

_ALIASES = {
    "none": "none",
    "": "none",
    "selected": "selected_regions",
    "selection": "selected_regions",
    "selected_regions": "selected_regions",
    "full": "document_pt_br",
    "portuguese": "document_pt_br",
    "portuguese_only": "document_pt_br",
    "document_pt_br": "document_pt_br",
    "side_by_side": "bilingual",
    "bilingual": "bilingual",
}


def normalize_translation_mode(value: str | None) -> str:
    key = (value or "none").strip()
    if key not in _ALIASES:
        raise ValueError(key)
    return _ALIASES[key]


def translation_state(*, provider: str, partial: bool, error: str = "") -> str:
    if error:
        return "error"
    if provider == "glossary" or partial:
        return "partial"
    if provider == "argos":
        return "completed"
    if provider == "external":
        return "completed"
    return "unavailable"
