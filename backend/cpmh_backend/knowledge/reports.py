"""Comparação e relatório a partir dos trechos, sem completar lacunas."""

from __future__ import annotations

from pathlib import Path

from docx import Document as DocxDocument

from cpmh_backend.knowledge.rag import REFUSAL, ask
from cpmh_backend.knowledge.search import search
from cpmh_backend.models import Document


def compare_documents(session, document_ids: list[str], question: str) -> dict:
    columns = []
    bags: list[set[str]] = []
    for document_id in document_ids:
        document = session.get(Document, document_id)
        hits = search(session, question, document_id=document_id, limit=4)
        columns.append(
            {
                "document_id": document_id,
                "title": document.title if document else "",
                "hits": [
                    {"page": hit["page"], "section": hit["section"], "content": hit["content"], "chunk_id": hit["chunk_id"]}
                    for hit in hits
                    if hit["score"] >= 0.18
                ],
            }
        )
        text = " ".join(item["content"].lower() for item in columns[-1]["hits"])
        bags.append(set(text.split()))
    divergences = []
    if len(bags) >= 2:
        shared = set.intersection(*bags) if all(bags) else set()
        for index, words in enumerate(bags):
            only = sorted(word for word in words - shared if len(word) > 6)[:12]
            if only:
                divergences.append({"document_id": document_ids[index], "terms_only_here": only})
    return {
        "question": question,
        "columns": columns,
        "divergences": divergences,
        "note": "A comparação lista trechos recuperados. Termos exclusivos não são uma conclusão experimental.",
    }


def write_report(session, document_ids: list[str], question: str, destination: Path) -> dict:
    compared = compare_documents(session, document_ids, question)
    parts = [ask(session, question, document_id=document_id) for document_id in document_ids]
    answer = {
        "answer": "\n\n".join(part["answer"] for part in parts),
        "citations": [citation for part in parts for citation in part["citations"]],
        "mode": "extractive" if any(part["mode"] == "extractive" for part in parts) else parts[0]["mode"],
    }
    document = DocxDocument()
    document.add_heading("Relatório CPMH Knowledge AI", level=1)
    document.add_paragraph(question)
    document.add_paragraph(answer["answer"] or REFUSAL)
    document.add_heading("Fontes", level=2)
    if not answer["citations"]:
        document.add_paragraph("Nenhuma fonte passou do limiar de evidência.")
    for citation in answer["citations"]:
        document.add_paragraph(
            f"{citation['document_title']} — página {citation['page']} — {citation['section'] or citation['element_type']} — {citation['chunk_id']}"
        )
    document.add_heading("Termos que aparecem em apenas uma fonte", level=2)
    for item in compared["divergences"]:
        document.add_paragraph(f"{item['document_id']}: {', '.join(item['terms_only_here'])}")
    document.add_paragraph(compared["note"])
    destination.parent.mkdir(parents=True, exist_ok=True)
    document.save(destination)
    return {"path": str(destination), "citations": answer["citations"], "mode": answer["mode"]}
