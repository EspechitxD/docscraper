from __future__ import annotations

import hashlib
from pathlib import Path

from PIL import Image


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def dhash(image: Image.Image, hash_size: int = 8) -> str:
    gray = image.convert("L").resize((hash_size + 1, hash_size), Image.Resampling.LANCZOS)
    pixels = list(gray.getdata())
    width = hash_size + 1
    bits: list[str] = []
    for y in range(hash_size):
        for x in range(hash_size):
            left = pixels[y * width + x]
            right = pixels[y * width + x + 1]
            bits.append("1" if left > right else "0")
    return "".join(bits)


def hamming(left: str, right: str) -> int:
    if not left or not right or len(left) != len(right):
        return 64
    return sum(a != b for a, b in zip(left, right))


def looks_blank(image: Image.Image) -> bool:
    gray = image.convert("L")
    sample = gray.resize((48, 48))
    pixels = list(sample.getdata())
    if not pixels:
        return True
    white = sum(1 for pixel in pixels if pixel >= 245)
    return white / len(pixels) > 0.985


def looks_partial(image: Image.Image) -> bool:
    """Página quase vazia, mas com uma faixa de conteúdo — carregamento incompleto."""
    gray = image.convert("L").resize((40, 40))
    pixels = list(gray.getdata())
    width = 40
    row_ink = []
    for y in range(40):
        row = pixels[y * width : (y + 1) * width]
        row_ink.append(sum(1 for pixel in row if pixel < 240) / width)
    ink_rows = [value for value in row_ink if value > 0.08]
    if not ink_rows:
        return False
    # Conteúdo concentrado numa faixa estreita e o resto em branco.
    return len(ink_rows) <= 3 and (sum(row_ink) / len(row_ink)) < 0.08


def clamp_bbox(x: float, y: float, w: float, h: float) -> tuple[float, float, float, float]:
    x = min(max(float(x), 0.0), 1.0)
    y = min(max(float(y), 0.0), 1.0)
    w = min(max(float(w), 0.0), 1.0 - x)
    h = min(max(float(h), 0.0), 1.0 - y)
    return x, y, w, h


def crop_normalized(image: Image.Image, bbox: tuple[float, float, float, float], pad: int = 2) -> Image.Image | None:
    x, y, w, h = clamp_bbox(*bbox)
    width, height = image.size
    left = max(int(x * width) - pad, 0)
    top = max(int(y * height) - pad, 0)
    right = min(int((x + w) * width) + pad, width)
    bottom = min(int((y + h) * height) + pad, height)
    if right - left < 2 or bottom - top < 2:
        return None
    return image.crop((left, top, right, bottom))
