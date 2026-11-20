"""Runtime local. Não inicia processo e não baixa modelo."""

from __future__ import annotations

import json
import time
import urllib.request

_PROBE: dict = {"at": 0.0, "value": None}


def status() -> dict:
    ollama = _probe_ollama()
    return {
        "llm_ready": bool(ollama.get("models")),
        "provider": "ollama" if ollama.get("models") else None,
        "embedding_model": "cpmh-hash-v1",
        "embedding_kind": "hashing",
        "neural_embedding": False,
        "silent_download": False,
        "ollama": ollama,
        "note": (
            "O vetor ativo é local e léxico. Um modelo de linguagem só entra se o Ollama "
            "já estiver em execução nesta máquina, com um modelo instalado pelo usuário."
        ),
    }


def generate(question: str, context: str, allowed_ids: list[str]) -> str | None:
    info = _probe_ollama()
    models = info.get("models") or []
    if not models:
        return None
    model = models[0]
    prompt = (
        "Responda em português do Brasil. Use somente o contexto. "
        "Cada afirmação factual deve terminar com o identificador do trecho entre colchetes. "
        f"Identificadores permitidos: {', '.join(allowed_ids)}. "
        "Se o contexto não bastar, diga que não encontrou evidência suficiente.\n\n"
        f"Pergunta: {question}\n\nContexto:\n{context}"
    )
    payload = json.dumps({"model": model, "prompt": prompt, "stream": False}).encode("utf-8")
    request = urllib.request.Request(
        "http://127.0.0.1:11434/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = json.loads(response.read().decode("utf-8"))
    except Exception:
        return None
    text = (body.get("response") or "").strip()
    return text or None


def _probe_ollama() -> dict:
    now = time.monotonic()
    cached = _PROBE["value"]
    if cached is not None and now - float(_PROBE["at"]) < 8:
        return cached
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=0.4) as response:
            body = json.loads(response.read().decode("utf-8"))
        names = [item.get("name", "") for item in body.get("models") or [] if item.get("name")]
        value = {"reachable": True, "models": names}
    except Exception:
        value = {"reachable": False, "models": []}
    _PROBE["at"] = now
    _PROBE["value"] = value
    return value
