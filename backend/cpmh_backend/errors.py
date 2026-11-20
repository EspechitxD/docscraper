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
