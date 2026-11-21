from __future__ import annotations

import re
import shutil
import subprocess
import unicodedata

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


_HYPHEN_BREAK = re.compile(r"([A-Za-zÀ-ÿ]{2,})-\s+([a-zà-ÿ])")


def dehyphenate_text(text: str) -> str:
    """Junta a palavra partida no fim da linha, como 'clean-' + 'ing'."""
    previous = None
    current = text or ""
    while current != previous:
        previous = current
        current = _HYPHEN_BREAK.sub(r"\1\2", current)
    return current


_SPACE_BEFORE = re.compile(r"[ \t]+([,.;:!?%)\]])")
_SPACE_AFTER = re.compile(r"([(\[])[ \t]+")
_MULTI_SPACE = re.compile(r"[ \t]{2,}")


def polish_ocr_text(text: str) -> str:
    """Limpa a leitura sem trocar letras: hífen de fim de linha, espaços e pontuação."""
    current = unicodedata.normalize("NFKC", (text or "").replace("\u00ad", ""))
    current = dehyphenate_text(current)
    current = _SPACE_BEFORE.sub(r"\1", current)
    current = _SPACE_AFTER.sub(r"\1", current)
    current = _MULTI_SPACE.sub(" ", current)
    return current.strip()


def _read_osd(image: Image.Image) -> tuple[int, float]:
    try:
        import pytesseract

        osd = pytesseract.image_to_osd(image)
    except Exception:
        return 0, 0.0
    angle = 0
    confidence = 0.0
    for line in osd.splitlines():
        lowered = line.lower()
        if lowered.startswith("rotate:"):
            try:
                angle = int(line.split(":", 1)[1].strip())
            except ValueError:
                angle = 0
        elif lowered.startswith("orientation confidence:"):
            try:
                confidence = float(line.split(":", 1)[1].strip())
            except ValueError:
                confidence = 0.0
    return angle, confidence


def _sample_score(image: Image.Image) -> tuple[float, int]:
    import pytesseract
    from pytesseract import Output

    sample = image.convert("L")
    sample.thumbnail((1000, 1400))
    try:
        data = pytesseract.image_to_data(sample, lang="eng", output_type=Output.DICT)
    except Exception:
        return 0.0, 0
    confidences: list[float] = []
    letters = 0
    for text, conf in zip(data["text"], data["conf"]):
        token = (text or "").strip()
        try:
            value = float(conf)
        except (TypeError, ValueError):
            continue
        if not token or value < 0:
            continue
        confidences.append(value)
        letters += sum(character.isalpha() for character in token)
    if not confidences:
        return 0.0, 0
    return sum(confidences) / len(confidences), letters


def _apply_angle(image: Image.Image, angle: int) -> tuple[Image.Image, int]:
    if angle == 90:
        return image.rotate(-90, expand=True), 90
    if angle == 180:
        return image.rotate(180, expand=True), 180
    if angle == 270:
        return image.rotate(90, expand=True), 270
    return image, 0


def _rotate_right_angles(image: Image.Image) -> tuple[Image.Image, int]:
    image = image.convert("RGB")
    angle, confidence = _read_osd(image)
    if confidence >= 2 and angle in {0, 90, 180, 270}:
        return _apply_angle(image, angle)
    upright = _sample_score(image)
    turned = _sample_score(image.rotate(180, expand=True))
    if turned[0] >= upright[0] + 12 and turned[1] >= upright[1]:
        return image.rotate(180, expand=True), 180
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
        text = dehyphenate_text(" ".join(word.text for word in words))
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
                if previous.text.endswith("-") and line.text[:1].islower():
                    previous.text = dehyphenate_text(previous.text[:-1] + line.text)
                else:
                    previous.text = dehyphenate_text(f"{previous.text} {line.text}".strip())
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
