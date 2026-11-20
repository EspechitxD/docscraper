"""Resposta fundamentada. Sem modelo local, a resposta é uma citação dos trechos."""

from __future__ import annotations

import re

from cpmh_backend.knowledge.embeddings import tokenize
from cpmh_backend.knowledge.lexicon import expand_query
from cpmh_backend.knowledge.runtime import generate
from cpmh_backend.knowledge.security import wrap_untrusted
from cpmh_backend.knowledge.search import search

REFUSAL = "Não encontrei informações suficientes na biblioteca documental para responder com segurança."
_MIN_SCORE = 0.18
_GENERIC = {
    "artigo", "artigos", "estudo", "estudos", "resultado", "resultados", "analise", "contexto",
    "documento", "documentos", "pagina", "informacao", "informacoes", "citado", "citada",
    "relatorio", "texto", "trecho", "trechos", "biblioteca",
    "maior", "menor", "valor", "valores", "utilizado", "utilizada", "apresentado", "apresentada",
}


def ask(session, question: str, **scope) -> dict:
    hits = search(session, question, **scope)
    anchors = set(tokenize(expand_query(question)))
    usable = [hit for hit in hits if hit["score"] >= _MIN_SCORE and _anchored(hit["content"], anchors)]
    if not usable:
        return {"answer": REFUSAL, "citations": [], "mode": "insufficient_evidence", "hits": hits[:3]}
    citations = [_citation(hit) for hit in usable]
    context = "\n\n".join(
        f"[{hit['chunk_id']}] página {hit['page']} {hit['section']}\n{wrap_untrusted(hit['content'])}" for hit in usable
    )
    generated = generate(question, context, [hit["chunk_id"] for hit in usable])
    if generated is None:
        answer = _extractive(question, usable)
        mode = "extractive"
    else:
        answer, kept = validate_citations(generated, usable)
        if not kept:
            answer = _extractive(question, usable)
            mode = "extractive"
        else:
            citations = [_citation(hit) for hit in usable if hit["chunk_id"] in kept]
            mode = "local_llm"
    return {"answer": answer, "citations": citations, "mode": mode, "hits": usable}


def validate_citations(answer: str, hits: list[dict]) -> tuple[str, set[str]]:
    allowed = {hit["chunk_id"] for hit in hits}
    mentioned = set(re.findall(r"\[([0-9a-f-]{36})\]", answer))
    kept = mentioned & allowed
    if not kept:
        return answer, set()
    cleaned = answer
    for chunk_id in mentioned - allowed:
        cleaned = cleaned.replace(f"[{chunk_id}]", "")
    return cleaned.strip(), kept


def _extractive(question: str, hits: list[dict]) -> str:
    lines = ["Com base nos trechos recuperados da biblioteca:"]
    query_tokens = set(tokenize(question))
    for hit in hits[:4]:
        quote = _best_sentence(hit["content"], query_tokens)
        lines.append(f"«{quote}»")
    lines.append("Inferências além desses trechos não foram acrescentadas.")
    return "\n".join(lines)


def _best_sentence(content: str, query_tokens: set[str]) -> str:
    parts = re.split(r"(?<=[.!?])\s+|\n+", content)
    parts = [part.strip() for part in parts if part.strip()]
    if not parts:
        return content[:400]
    def score(part: str) -> int:
        return len(query_tokens & set(tokenize(part)))
    best = max(parts, key=score)
    return best[:500]


def _anchored(content: str, query_tokens: set[str]) -> bool:
    shared = set(tokenize(content)) & query_tokens
    return any(len(token) >= 5 and token not in _GENERIC for token in shared)


def _citation(hit: dict) -> dict:
    return {
        "chunk_id": hit["chunk_id"],
        "document_id": hit["document_id"],
        "document_title": hit["document_title"],
        "page": hit["page"],
        "section": hit["section"],
        "element_type": hit["element_type"],
        "source_region_id": hit["source_region_id"],
        "revision_version": hit["revision_version"],
    }
