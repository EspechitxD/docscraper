"""Busca híbrida: texto do FTS5 e similaridade do vetor local."""

from __future__ import annotations

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from cpmh_backend.knowledge.embeddings import MODEL_ID, cosine, embed, tokenize
from cpmh_backend.knowledge.lexicon import expand_query
from cpmh_backend.models import Document, KnowledgeChunk, KnowledgeEmbedding, KnowledgeLibrary


def search(
    session: Session,
    question: str,
    *,
    project_id: str | None = None,
    document_id: str | None = None,
    library_id: str | None = None,
    limit: int = 6,
) -> list[dict]:
    expanded = expand_query(question)
    statement = select(KnowledgeChunk).where(KnowledgeChunk.deleted.is_(False))
    if library_id:
        statement = statement.where(KnowledgeChunk.library_id == library_id)
    if document_id:
        statement = statement.where(KnowledgeChunk.document_id == document_id)
    if project_id:
        library_ids = list(
            session.scalars(select(KnowledgeLibrary.id).where(KnowledgeLibrary.project_id == project_id)).all()
        )
        if not library_ids:
            return []
        statement = statement.where(KnowledgeChunk.library_id.in_(library_ids))
    chunks = session.scalars(statement).all()
    if not chunks:
        return []
    lexical_scores = _lexical(session, expanded, {chunk.id for chunk in chunks})
    query_vector = embed(expanded)
    query_tokens = set(tokenize(expanded))
    original_tokens = set(tokenize(question))
    purpose = {"objetivo", "objetivos"} & original_tokens
    ranked = []
    for chunk in chunks:
        vector_row = session.scalar(
            select(KnowledgeEmbedding).where(
                KnowledgeEmbedding.chunk_id == chunk.id,
                KnowledgeEmbedding.model_id == MODEL_ID,
            )
        )
        vector_score = cosine(query_vector, vector_row.vector) if vector_row and vector_row.vector else 0.0
        token_score = 0.0
        if query_tokens:
            overlap = query_tokens & set(tokenize(chunk.content))
            token_score = len(overlap) / len(query_tokens)
        lexical = max(lexical_scores.get(chunk.id, 0.0), token_score)
        score = 0.45 * lexical + 0.55 * max(vector_score, token_score)
        if purpose and chunk.page_sequence <= 2 and {"pretende", "finalidade", "proposito", "objetivo", "objetivos"} & set(tokenize(chunk.content)):
            score += 0.2
        if chunk.element_type in {"header", "footer", "page_number"}:
            score *= 0.2
        ranked.append((score, chunk))
    ranked.sort(key=lambda item: item[0], reverse=True)
    results = []
    titles = {}
    for score, chunk in ranked[:limit]:
        if chunk.document_id not in titles:
            document = session.get(Document, chunk.document_id)
            titles[chunk.document_id] = document.title if document else ""
        results.append(
            {
                "score": round(score, 4),
                "chunk_id": chunk.id,
                "document_id": chunk.document_id,
                "document_title": titles[chunk.document_id],
                "page": chunk.page_sequence,
                "section": chunk.section,
                "element_type": chunk.element_type,
                "content": chunk.content,
                "source_region_id": chunk.source_region_id,
                "revision_version": chunk.revision_version,
            }
        )
    return results


def _lexical(session: Session, question: str, allowed: set[str]) -> dict[str, float]:
    tokens = [token for token in tokenize(question) if token.upper() not in {"AND", "OR", "NOT", "NEAR"}][:12]
    if not tokens:
        return {}
    match = " OR ".join(f'"{token}"' for token in tokens)
    try:
        rows = session.execute(
            text(
                "SELECT chunk_id, bm25(knowledge_fts) AS rank FROM knowledge_fts "
                "WHERE knowledge_fts MATCH :match ORDER BY rank LIMIT 30"
            ),
            {"match": match},
        ).fetchall()
    except Exception:
        return {}
    scores = {}
    for chunk_id, rank in rows:
        if chunk_id not in allowed:
            continue
        scores[chunk_id] = 1.0 / (1.0 + abs(float(rank)))
    if not scores:
        return {}
    best = max(scores.values()) or 1.0
    return {key: value / best for key, value in scores.items()}
