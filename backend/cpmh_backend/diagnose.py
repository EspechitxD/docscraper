"""Linha de comando: python -m cpmh_backend.diagnose URL [--out relatorio.json]

Inspeciona a página no Chrome do computador e grava um diagnóstico. Não baixa nem captura páginas.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from cpmh_backend.services.document_recovery import diagnose_url, save_report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Diagnóstico de documento em visualizador web")
    parser.add_argument("url")
    parser.add_argument("--out", default="diagnostico_documento_web.json")
    parser.add_argument("--timeout", type=float, default=25.0)
    args = parser.parse_args(argv)
    report = diagnose_url(args.url, timeout=args.timeout)
    save_report(report, Path(args.out))
    print(report.get("summary", ""))
    print(f"\nRelatório completo: {args.out}")
    return 0 if report.get("primary_state") != "processing_failed" else 2


if __name__ == "__main__":
    sys.exit(main())
