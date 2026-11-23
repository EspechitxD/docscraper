from __future__ import annotations


class AppError(Exception):
    def __init__(self, message: str, *, status_code: int = 400, code: str = "error"):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code


class OcrUnavailable(AppError):
    """O Tesseract não foi encontrado. A mensagem diz como instalar, em vez de mostrar um traceback."""

    def __init__(self, detail: str = ""):
        message = (
            "O Tesseract (programa de OCR) não foi encontrado neste computador. "
            "Instale-o e tente de novo: no Windows, abra o Prompt de Comando e rode "
            "`winget install --id UB-Mannheim.TesseractOCR -e`; na instalação marque os idiomas "
            "Portuguese, Chinese (Simplified e Traditional) e Japanese. "
            "Se ele já está instalado em outra pasta, defina a variável CPMH_TESSERACT_PATH com o "
            "caminho do tesseract.exe."
        )
        super().__init__(message + (f" ({detail})" if detail else ""), status_code=503, code="ocr_unavailable")


class UrlRejected(AppError):
    def __init__(self, message: str):
        super().__init__(message, status_code=400, code="url_rejected")


class VpnRequired(UrlRejected):
    """A política da empresa exige VPN ativa antes de acessar endereços externos."""

    def __init__(self, message: str | None = None):
        super().__init__(
            message
            or "A VPN da empresa precisa estar ativa antes de acessar endereços externos. Conecte a VPN e tente de novo."
        )
        self.status_code = 409
        self.code = "vpn_required"


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
