"""Prepara a pasta de runtime sem baixar binários.

O resultado descreve o que foi encontrado nesta máquina. Um binário do
Linux não é um backend de Windows. O manifesto registra a ausência em vez
de fingir que o componente foi empacotado.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DESTINATION = ROOT / "build" / "runtime"


def fingerprint(path: Path) -> dict:
    data = path.read_bytes()
    return {"path": str(path), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def discover() -> dict:
    components = []
    tesseract = shutil.which("tesseract")
    if tesseract:
        version = subprocess.check_output([tesseract, "--version"], text=True, stderr=subprocess.STDOUT).splitlines()[0]
        components.append({"name": "tesseract", "present": True, "version": version, "license": "Apache-2.0", **fingerprint(Path(tesseract))})
        tessdata = Path("/usr/share/tesseract-ocr/5/tessdata")
        models = []
        if tessdata.exists():
            for model in sorted(tessdata.glob("*.traineddata")):
                if model.name.split(".")[0] in {"por", "eng", "chi_sim", "chi_tra", "osd"}:
                    models.append({"name": model.name, "license": "Apache-2.0", **fingerprint(model)})
        components.append({"name": "tessdata", "present": bool(models), "models": models, "copied": False})
    else:
        components.append({"name": "tesseract", "present": False, "copied": False})
    chrome = shutil.which("google-chrome") or shutil.which("chromium")
    components.append({
        "name": "chromium",
        "present": bool(chrome),
        "path": chrome or "",
        "copied": False,
        "note": "O empacotamento do Chromium do Playwright ocorre no runner Windows. Esta máquina não copia o Chrome do sistema para o instalador.",
    })
    frozen = ROOT / "dist" / "cpmh-backend"
    components.append({
        "name": "python-backend",
        "present": frozen.exists(),
        "copied": False,
        "note": "Gere com PyInstaller no sistema de destino. Um freezer Linux não produz o executável Windows.",
    })
    return {
        "platform_observed": "linux" if Path("/proc").exists() else "unknown",
        "windows_installer_tested": False,
        "silent_download": False,
        "components": components,
    }


def main() -> None:
    DESTINATION.mkdir(parents=True, exist_ok=True)
    manifest = discover()
    (DESTINATION / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (DESTINATION / "README.txt").write_text(
        "Runtime preparado para inspeção. Nenhum binário foi baixado. "
        "O instalador Windows só fica completo depois do freezer e do teste em Windows.\n",
        encoding="utf-8",
    )
    print(DESTINATION / "manifest.json")


if __name__ == "__main__":
    main()
