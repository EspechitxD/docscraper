"""Contagem de páginas, caracteres e palavras. Só conta o que foi processado, nunca metadado do site."""

from __future__ import annotations

import re

_CJK = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af]")


def cjk_share(text: str) -> float:
    letters = [char for char in text if char.isalpha() or _CJK.match(char)]
    if not letters:
        return 0.0
    return sum(1 for char in letters if _CJK.match(char)) / len(letters)


def count_words(text: str) -> int | None:
    """Palavras por espaço. Em chinês, japonês e coreano não há espaço entre palavras: devolve None."""
    if cjk_share(text) > 0.2:
        return None
    return len(re.findall(r"\S+", text))


def page_statistics(pages: list[dict]) -> dict:
    """`pages`: lista de {sequence, text, interface_text?, confidence?, method?}."""
    per_page = []
    total_with = total_without = total_interface = 0
    words_total: int | None = 0
    for page in pages:
        text = str(page.get("text") or "")
        interface = str(page.get("interface_text") or "")
        with_spaces = len(text)
        without = len("".join(text.split()))
        words = count_words(text)
        total_with += with_spaces
        total_without += without
        total_interface += len(interface)
        if words is None:
            words_total = None
        elif words_total is not None:
            words_total += words
        per_page.append(
            {
                "sequence": page.get("sequence"),
                "chars_with_spaces": with_spaces,
                "chars_without_spaces": without,
                "words": words,
                "has_text": without >= 20,
                "confidence": page.get("confidence"),
                "method": page.get("method", ""),
            }
        )
    with_text = sum(1 for item in per_page if item["has_text"])
    return {
        "pages_processed": len(per_page),
        "pages_with_text": with_text,
        "pages_without_text": len(per_page) - with_text,
        "chars_with_spaces": total_with,
        "chars_without_spaces": total_without,
        "document_chars": total_with,
        "interface_chars_discarded": total_interface,
        "words": words_total,
        "words_note": "" if words_total is not None else "Idioma sem espaço entre palavras: contagem de palavras omitida.",
        "per_page": per_page,
    }
