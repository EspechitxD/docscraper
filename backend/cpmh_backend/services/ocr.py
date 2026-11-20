from __future__ import annotations

import shutil
import subprocess

from PIL import Image

from cpmh_backend.intelligence import Block, WordBox

_LANG_MAP = {
    "por": "por",
    "eng": "eng",
    "chi_sim": "chi_sim",
    "chi_tra": "chi_tra",
}


def tesseract_status() -> dict:
    binary = shutil.which("tesseract")
    if not binary:
        return {"installed": False, "version": "", "languages": [], "missing": ["por", "eng", "chi_sim", "chi_tra"]}
    try:
        version = subprocess.check_output([binary, "--version"], text=True, stderr=subprocess.STDOUT).splitlines()[0]
    except Exception as exc:
        version = f"indisponível ({exc})"
    try:
        import pytesseract

        languages = pytesseract.get_languages(config="")
    except Exception:
        languages = []
    required = ["por", "eng", "chi_sim", "chi_tra"]
    return {
        "installed": True,
        "version": version,
        "languages": languages,
        "missing": [language for language in required if language not in languages],
    }


def _rotate_right_angles(image: Image.Image) -> tuple[Image.Image, int]:
    try:
        import pytesseract

        osd = pytesseract.image_to_osd(image)
    except Exception:
        return image, 0
    angle = 0
    for line in osd.splitlines():
        if line.lower().startswith("rotate:"):
            try:
                angle = int(line.split(":", 1)[1].strip())
            except ValueError:
                angle = 0
    if angle == 90:
        return image.rotate(-90, expand=True), 90
    if angle == 180:
        return image.rotate(180, expand=True), 180
    if angle == 270:
        return image.rotate(90, expand=True), 270
    return image, 0


def recognize(image: Image.Image, languages: list[str] | None = None) -> tuple[list[Block], Image.Image, dict]:
    import pytesseract
    from pytesseract import Output

    notes = {"orientation": 0, "languages": []}
    prepared, angle = _rotate_right_angles(image.convert("RGB"))
    notes["orientation"] = angle
    requested = [item for item in (languages or ["por", "eng"]) if item in _LANG_MAP]
    if not requested:
        requested = ["por", "eng"]
    installed = set(tesseract_status().get("languages") or [])
    usable = [item for item in requested if not installed or item in installed]
    if not usable:
        usable = ["eng"] if "eng" in installed or not installed else sorted(installed)[:1]
    # Chinês e latino juntos degradam páginas de um só idioma. Escolhemos o conjunto pedido.
    lang = "+".join(usable)
    notes["languages"] = usable
    data = pytesseract.image_to_data(prepared, lang=lang, output_type=Output.DICT)
    width, height = prepared.size
    grouped: dict[tuple, list[WordBox]] = {}
    order: list[tuple] = []
    total = len(data["text"])
    for index in range(total):
        text = (data["text"][index] or "").strip()
        try:
            confidence = float(data["conf"][index])
        except (TypeError, ValueError):
            confidence = -1
        if not text or confidence < 0:
            continue
        x = float(data["left"][index]) / width
        y = float(data["top"][index]) / height
        w = float(data["width"][index]) / width
        h = float(data["height"][index]) / height
        word = WordBox(text, (x, y, w, h), confidence)
        key = (int(data["block_num"][index]), int(data["par_num"][index]), int(data["line_num"][index]))
        if key not in grouped:
            grouped[key] = []
            order.append(key)
        grouped[key].append(word)
    lines: list[Block] = []
    for key in order:
        words = grouped[key]
        if not words:
            continue
        text = " ".join(word.text for word in words)
        x = min(word.bbox[0] for word in words)
        y = min(word.bbox[1] for word in words)
        right = max(word.bbox[0] + word.bbox[2] for word in words)
        bottom = max(word.bbox[1] + word.bbox[3] for word in words)
        confidence = sum(word.confidence for word in words) / len(words)
        lines.append(
            Block(
                text=text,
                bbox=(x, y, right - x, bottom - y),
                confidence=round(confidence, 2),
                source="ocr",
                font_size=bottom - y,
                words=words,
            )
        )
    paragraphs: list[Block] = []
    for line in lines:
        if paragraphs:
            previous = paragraphs[-1]
            gap = line.bbox[1] - (previous.bbox[1] + previous.bbox[3])
            same_column = abs(line.bbox[0] - previous.bbox[0]) < 0.08
            if 0 <= gap < max(line.font_size, 0.012) * 0.9 and same_column:
                previous.text = (previous.text + " " + line.text).strip()
                x = min(previous.bbox[0], line.bbox[0])
                y = previous.bbox[1]
                right = max(previous.bbox[0] + previous.bbox[2], line.bbox[0] + line.bbox[2])
                bottom = line.bbox[1] + line.bbox[3]
                previous.bbox = (x, y, right - x, bottom - y)
                previous.words.extend(line.words)
                previous.confidence = round(
                    (previous.confidence + line.confidence) / 2,
                    2,
                )
                continue
        paragraphs.append(line)
    return paragraphs, prepared, notes
