"""Pausa e retomada quando a captura encontra um bloqueio."""

from __future__ import annotations

import datetime as dt
import uuid

from cpmh_backend.models import AccessEvent, utcnow

SESSION_TTL = dt.timedelta(minutes=30)


def partition_name(project_id: str, job_id: str) -> str:
    return f"persist:cpmh-{project_id}-{job_id}"


def remember(session, job, document, verdict: dict, *, source: str) -> dict:
    checkpoint = dict(job.checkpoint or {})
    access = dict(checkpoint.get("access") or {})
    attempts = list(access.get("attempts") or [])
    last = attempts[-1] if attempts else {}
    same = last.get("state") == verdict["state"] and last.get("url") == (verdict.get("final_url") or verdict.get("url")) and last.get("source") == source
    duplicate = bool(same and job.state == "paused" and source == "capture")
    if not duplicate:
        attempts.append(
            {
                "state": verdict["state"],
                "provider": verdict.get("provider") or "none",
                "url": (verdict.get("final_url") or verdict.get("url") or "")[:500],
                "source": source,
                "at": utcnow().isoformat(),
            }
        )
    repeated = [item for item in attempts if item["state"] not in {"", "ACCESS_GRANTED"}]
    persistent = len(repeated) >= 3 and verdict["state"] != "ACCESS_GRANTED"
    cleared = verdict["state"] == "ACCESS_GRANTED" and source == "recheck"
    access.update(
        {
            "state": verdict["state"],
            "provider": verdict.get("provider") or "none",
            "confidence": verdict.get("confidence") or 0,
            "evidence": list(verdict.get("evidence") or [])[:8],
            "message": verdict.get("message") or "",
            "url": (verdict.get("url") or "")[:500],
            "final_url": (verdict.get("final_url") or "")[:500],
            "cleared": cleared,
            "cleared_at": utcnow().isoformat() if cleared else access.get("cleared_at") or "",
            "persistent": persistent,
            "attempts": attempts[-12:],
            "partition": partition_name(document.project_id, job.id),
        }
    )
    if not cleared:
        access["cleared_at"] = ""
    else:
        job.error = ""
        document.error_message = ""
    checkpoint["access"] = access
    job.checkpoint = checkpoint
    if verdict["state"] != "ACCESS_GRANTED":
        job.state = "paused"
        job.stage = "capturing"
        job.error = access["message"][:500]
        document.state = "paused"
        document.capture_status = "blocked"
        document.error_message = job.error
    if not duplicate:
        session.add(
            AccessEvent(
                id=str(uuid.uuid4()),
                job_id=job.id,
                document_id=document.id,
                project_id=document.project_id,
                state=verdict["state"],
                provider=access["provider"],
                confidence=float(access["confidence"] or 0),
                url=access["final_url"] or access["url"],
                evidence=access["evidence"],
                created_at=utcnow(),
            )
        )
    return access


def resume_reason(checkpoint: dict | None, *, now: dt.datetime | None = None) -> str | None:
    access = dict((checkpoint or {}).get("access") or {})
    if not access:
        return None
    if access.get("persistent"):
        return "O bloqueio se repetiu. A captura por URL não continua. Importe o documento manualmente."
    if not access.get("cleared"):
        return access.get("message") or "A tarefa segue pausada até uma checagem da captura."
    raw = access.get("cleared_at") or ""
    try:
        cleared_at = dt.datetime.fromisoformat(raw)
    except ValueError:
        return "A verificação não tem horário válido. Peça uma nova checagem."
    if cleared_at.tzinfo is None:
        cleared_at = cleared_at.replace(tzinfo=dt.timezone.utc)
    current = now or utcnow()
    if current - cleared_at > SESSION_TTL:
        return "A verificação expirou. Abra a página e peça uma nova checagem. A captura não continua sozinha."
    return None
