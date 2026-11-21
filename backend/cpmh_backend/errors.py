from __future__ import annotations


class AppError(Exception):
    def __init__(self, message: str, *, status_code: int = 400, code: str = "error"):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code


class UrlRejected(AppError):
    def __init__(self, message: str):
        super().__init__(message, status_code=400, code="url_rejected")


class HttpAccess(UrlRejected):
    """Resposta HTTP de bloqueio. O trecho não entra em log."""

    def __init__(self, status_code: int, url: str, snippet: str, retry_after: float | None = None):
        super().__init__(f"O servidor respondeu {status_code} e o acesso foi interrompido.")
        self.http_status = status_code
        self.final_url = url
        self.snippet = snippet[:4000]
        self.retry_after = retry_after


class AccessPaused(AppError):
    def __init__(self, verdict: dict | None):
        if not isinstance(verdict, dict):
            verdict = {
                "state": "UNKNOWN_BLOCK",
                "message": "A captura foi interrompida porque a resposta de acesso veio vazia.",
            }
        super().__init__(verdict.get("message") or "Acesso pausado.", status_code=409, code="access_paused")
        self.verdict = verdict


class CollisionError(AppError):
    def __init__(self, path: str):
        super().__init__(
            "Já existe um arquivo com esse nome. Escolha substituir, criar nova versão, renomear ou cancelar.",
            status_code=409,
            code="name_collision",
        )
        self.path = path


class ConsentRequired(AppError):
    def __init__(self, message: str | None = None):
        super().__init__(
            message
            or "A tradução externa exige consentimento explícito. Nenhum conteúdo foi enviado.",
            status_code=403,
            code="consent_required",
        )
