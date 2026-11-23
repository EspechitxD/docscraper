"""Reparo conservador de identificadores lidos pelo OCR.

Regra de ouro: não trocar letra por palpite. Só corrige quando o próprio documento prova o certo.
Normas como F2459 e F2457 são documentos diferentes, então troca de dígito qualquer nunca entra.
Só entram confusões típicas de OCR (E/F, I/l/1, O/0, S/5, B/8) e só com maioria clara.
"""

from __future__ import annotations

import re
from collections import Counter

_CODE = re.compile(r"\b([A-Z]{1,2})(\d{3,5})\b")
_DAMAGED = re.compile(r"\b([A-G])([Il|O]{1,2}\d{1,3})\b")
_CONFUSABLE = {"E": "F", "F": "E", "B": "8", "S": "5", "O": "0"}


def _normalise_damaged(match: re.Match) -> str:
    """'GI22' -> 'G122': letra I ou l no meio dos dígitos de um código de norma."""
    letter, rest = match.group(1), match.group(2)
    fixed = rest.replace("I", "1").replace("l", "1").replace("|", "1").replace("O", "0")
    if fixed.isdigit() and 3 <= len(fixed) + 0 <= 4:
        return f"{letter}{fixed}"
    return match.group(0)


def identifier_counts(texts: list[str]) -> Counter:
    counts: Counter = Counter()
    for text in texts:
        for match in _CODE.finditer(text or ""):
            counts[match.group(0)] += 1
    return counts


def repair_identifiers(text: str, counts: Counter) -> str:
    """Corrige códigos isolados quando outra grafia aparece pelo menos duas vezes mais no documento."""
    if not text:
        return text
    text = _DAMAGED.sub(_normalise_damaged, text)

    def swap(match: re.Match) -> str:
        token = match.group(0)
        if counts.get(token, 0) != 1:
            return token
        letters, digits = match.group(1), match.group(2)
        alternative = _CONFUSABLE.get(letters[0])
        if alternative and alternative.isalpha() and len(letters) == 1:
            candidate = f"{alternative}{digits}"
            if counts.get(candidate, 0) >= 2:
                return candidate
        return token

    return _CODE.sub(swap, text)
