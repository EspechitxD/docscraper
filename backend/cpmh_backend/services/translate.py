from __future__ import annotations

import re

import httpx

from cpmh_backend.errors import AppError, ConsentRequired, UrlRejected
from cpmh_backend.models import GlossaryTerm
from cpmh_backend.security import validate_url

_PROTECTED = re.compile(
    r"https?://\S+"
    r"|\bISO\s?\d[\w:-]*\b"
    r"|\bTi6Al4V\b"
    r"|\b[A-Z]{2,}[-/]?\d[\w./-]*\b"
    r"|\b\d+(?:[.,]\d+)?(?:\s?(?:mm|cm|µm|um|kg|g|MPa|kPa|°C|%))?\b",
    re.IGNORECASE,
)


def apply_glossary(text: str, terms: list[GlossaryTerm]) -> tuple[str, list[str]]:
    placeholders: list[str] = []

    def hold(value: str) -> str:
        placeholders.append(value)
        return f"⟦{len(placeholders) - 1}⟧"

    working = _PROTECTED.sub(lambda match: hold(match.group(0)), text)
    ordered = sorted(terms, key=lambda term: len(term.source or ""), reverse=True)
    for term in ordered:
        source = (term.source or "").strip()
        if not source:
            continue
        pattern = re.compile(rf"(?<!\w){re.escape(source)}(?!\w)", re.IGNORECASE)
        if term.do_not_translate:
            working = pattern.sub(lambda match: hold(match.group(0)), working)
        elif term.target:
            working = pattern.sub(term.target, working)

    def restore(match: re.Match[str]) -> str:
        return placeholders[int(match.group(1))]

    return re.sub(r"⟦(\d+)⟧", restore, working), placeholders


def argos_available(source: str = "en", target: str = "pt") -> bool:
    try:
        import argostranslate.translate
    except Exception:
        return False
    try:
        languages = argostranslate.translate.get_installed_languages()
    except Exception:
        return False
    sources = [language for language in languages if language.code.startswith(source)]
    targets = [language for language in languages if language.code.startswith(target)]
    if not sources or not targets:
        return False
    return sources[0].get_translation(targets[0]) is not None


def translate_with_argos(text: str, source: str = "en", target: str = "pt") -> str | None:
    if not text.strip() or not argos_available(source, target):
        return None
    import argostranslate.translate

    languages = argostranslate.translate.get_installed_languages()
    source_lang = next(language for language in languages if language.code.startswith(source))
    target_lang = next(language for language in languages if language.code.startswith(target))
    translation = source_lang.get_translation(target_lang)
    return translation.translate(text)


def translate_external(text: str, endpoint: str, *, consent: bool, timeout: float, allow_local: bool) -> str:
    if not consent:
        raise ConsentRequired()
    if not endpoint.strip():
        raise AppError("Nenhum serviço externo de tradução foi configurado.", code="external_not_configured")
    try:
        validated = validate_url(endpoint, allow_local=allow_local)
    except UrlRejected as exc:
        raise AppError(exc.message, code="url_rejected") from exc
    try:
        response = httpx.post(
            validated.url,
            json={"text": text, "source": "auto", "target": "pt"},
            timeout=timeout,
            headers={"User-Agent": "CPMHDocumentIntelligence/0.1"},
        )
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        raise AppError(f"O serviço externo de tradução falhou: {exc}", code="external_failed") from exc
    translated = payload.get("translation") or payload.get("translated_text") or payload.get("text")
    if not isinstance(translated, str) or not translated.strip():
        raise AppError("O serviço externo não devolveu uma tradução utilizável.", code="external_failed")
    return translated


def translate_text(
    text: str,
    terms: list[GlossaryTerm],
    *,
    source_language: str,
    use_external: bool,
    consent: bool,
    endpoint: str,
    timeout: float,
    allow_local: bool,
) -> dict:
    protected, _holders = apply_glossary(text, terms)
    provider = "glossary"
    partial = True
    translated = protected
    if use_external:
        # O glossário já protegeu termos. O texto restante ainda contém marcadores restaurados.
        translated = translate_external(protected, endpoint, consent=consent, timeout=timeout, allow_local=allow_local)
        provider = "external"
        partial = False
    else:
        neural_source = "zh" if source_language.startswith("chi") or source_language == "zh" else "en"
        neural = translate_with_argos(protected, neural_source, "pt")
        if neural:
            translated = neural
            provider = "argos"
            partial = False
    return {
        "source_text": text,
        "translated_text": translated,
        "provider": provider,
        "partial": partial,
        "target_lang": "pt",
    }
