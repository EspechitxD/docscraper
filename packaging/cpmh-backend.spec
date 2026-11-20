# -*- mode: python ; coding: utf-8 -*-
"""Backend congelado. Execute no sistema operacional de destino.

No Windows o produto é cpmh-backend.exe. Neste Linux o mesmo spec gera um
binário Linux, útil para validar o freezer, não para o instalador NSIS.
"""

from PyInstaller.utils.hooks import collect_submodules

hidden = collect_submodules("uvicorn") + collect_submodules("cpmh_backend")
hidden += [
    "sqlalchemy.dialects.sqlite",
    "PIL",
    "cv2",
    "pytesseract",
    "pypdfium2",
    "docx",
    "reportlab",
]

a = Analysis(
    ["backend/cpmh_backend/__main__.py"],
    pathex=["backend"],
    binaries=[],
    datas=[],
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="cpmh-backend",
    console=True,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    name="cpmh-backend",
)
