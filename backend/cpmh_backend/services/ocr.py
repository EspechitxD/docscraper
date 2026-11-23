from __future__ import annotations

import os
import re
import shutil
import subprocess
import unicodedata

from PIL import Image, ImageOps

from pathlib import Path

from cpmh_backend.errors import OcrUnavailable
from cpmh_backend.intelligence import Block, WordBox
from cpmh_backend.layout import (
    COMPOUND_PREFIXES,
    line_block,
    lines_to_paragraphs,
    order_by_zones,
    split_words_at_gutters,
)

# Resolução alvo do OCR: cerca de 300 DPI numa página carta ou A4.
OCR_TARGET_WIDTH = 2480
OCR_MIN_WIDTH = 1800
OCR_MAX_SIDE = 4200
TESSERACT_CONFIG = "--oem 1 --psm 3 -c preserve_interword_spaces=1 -c user_defined_dpi=300"

_LANG_MAP = {
    "por": "por",
    "eng": "eng",
    "chi_sim": "chi_sim",
    "chi_tra": "chi_tra",
    "jpn": "jpn",
}

_TESSERACT_HINT = "winget install --id UB-Mannheim.TesseractOCR -e (marque Portuguese, Chinese e Japanese) ou defina CPMH_TESSERACT_PATH"


def find_tesseract() -> str:
    """Caminho do tesseract. Procura em variáveis, PATH e nas pastas padrão do Windows, Scoop, Chocolatey e Homebrew.

    No Windows o instalador não costuma pôr o Tesseract no PATH, então shutil.which sozinho falhava.
    """
    for variable in ("CPMH_TESSERACT_PATH", "TESSERACT_CMD"):
        value = os.environ.get(variable, "").strip().strip('"')
        if value and Path(value).is_file():
            return value
    for name in ("tesseract", "tesseract.exe"):
        found = shutil.which(name)
        if found:
            return found
    home = Path.home()
    candidates: list[Path] = []
    for variable in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA", "PROGRAMW6432"):
        base = os.environ.get(variable)
        if base:
            candidates.append(Path(base) / "Tesseract-OCR" / "tesseract.exe")
            candidates.append(Path(base) / "Programs" / "Tesseract-OCR" / "tesseract.exe")
    candidates += [
        Path("C:/Tesseract-OCR/tesseract.exe"),
        home / "scoop" / "apps" / "tesseract" / "current" / "tesseract.exe",
        Path(os.environ.get("ProgramData", "C:/ProgramData")) / "chocolatey" / "bin" / "tesseract.exe",
        Path("/opt/homebrew/bin/tesseract"),
        Path("/usr/local/bin/tesseract"),
        Path("/usr/bin/tesseract"),
    ]
    for path in candidates:
        if path.is_file():
            return str(path)
    return ""


def configure_tesseract() -> str:
    """Aponta o pytesseract para o executável achado (e o tessdata ao lado, se faltar a variável)."""
    path = find_tesseract()
    if not path:
        return ""
    try:
        import pytesseract

        pytesseract.pytesseract.tesseract_cmd = path
    except Exception:
        return path
    tessdata = Path(path).parent / "tessdata"
    if tessdata.is_dir() and not os.environ.get("TESSDATA_PREFIX"):
        os.environ["TESSDATA_PREFIX"] = str(tessdata)
    return path


_STATUS_CACHE: dict[str, dict] = {}


def tesseract_status(*, refresh: bool = False) -> dict:
    binary = configure_tesseract()
    required = ["por", "eng", "chi_sim", "chi_tra"]
    if not binary:
        return {"installed": False, "path": "", "hint": _TESSERACT_HINT, "version": "", "languages": [], "missing": required}
    if binary in _STATUS_CACHE and not refresh:
        return _STATUS_CACHE[binary]
    try:
        version = subprocess.check_output([binary, "--version"], text=True, stderr=subprocess.STDOUT).splitlines()[0]
    except Exception as exc:
        version = f"indisponível ({exc})"
    try:
        import pytesseract

        languages = pytesseract.get_languages(config="")
    except Exception:
        languages = []
    status = {
        "installed": True,
        "path": binary,
        "hint": "" if all(item in languages for item in required) else "Faltam idiomas: reinstale o Tesseract marcando Portuguese, Chinese e Japanese.",
        "version": version,
        "languages": languages,
        "missing": [language for language in required if language not in languages],
    }
    _STATUS_CACHE[binary] = status
    return status


_HYPHEN_BREAK = re.compile(r"([A-Za-zÀ-ÿ]{2,})-\s+([a-zà-ÿ])")


def _join_break(match: re.Match) -> str:
    left, right = match.group(1), match.group(2)
    if left.lower() in COMPOUND_PREFIXES:
        return f"{left}-{right}"  # "non- specific" é "non-specific", não "nonspecific"
    return f"{left}{right}"


def dehyphenate_text(text: str) -> str:
    """Junta a palavra partida no fim da linha, como 'clean-' + 'ing'.

    Prefixos que formam composto de verdade ('non-', 'in-', 'self-') mantêm o hífen.
    """
    previous = None
    current = text or ""
    while current != previous:
        previous = current
        current = _HYPHEN_BREAK.sub(_join_break, current)
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


def estimate_skew(gray: Image.Image, limit: float = 4.0) -> float:
    """Inclinação da página em graus, pela variância do perfil de linhas. 0 quando não há texto."""
    try:
        import numpy as np
    except Exception:
        return 0.0
    sample = gray.copy()
    sample.thumbnail((900, 1200))
    array = np.array(sample, dtype="uint8")
    if array.size == 0:
        return 0.0
    threshold = float(array.mean()) - 0.5 * float(array.std())
    binary = Image.fromarray(((array < threshold) * 255).astype("uint8"))
    if (np.array(binary) > 0).mean() < 0.005:
        return 0.0

    def score(angle: float) -> float:
        turned = binary.rotate(angle, resample=Image.BILINEAR, expand=False, fillcolor=0)
        profile = np.array(turned, dtype="float32").sum(axis=1)
        return float(profile.var())

    best, best_score = 0.0, score(0.0)
    angle = -limit
    while angle <= limit + 1e-9:
        value = score(angle)
        if value > best_score:
            best, best_score = angle, value
        angle += 0.25
    fine = best - 0.25
    while fine <= best + 0.25 + 1e-9:
        value = score(fine)
        if value > best_score:
            best, best_score = fine, value
        fine += 0.05
    return round(best, 2)


def prepare_for_ocr(image: Image.Image) -> tuple[Image.Image, Image.Image, dict]:
    """Devolve (imagem colorida endireitada, imagem cinza melhorada para o OCR, notas).

    Os boxes do Tesseract são medidos sobre a imagem cinza, que tem o mesmo tamanho da colorida.
    """
    rgb = image.convert("RGB")
    longest = max(rgb.size)
    if longest > OCR_MAX_SIDE:
        factor = OCR_MAX_SIDE / longest
        rgb = rgb.resize((max(int(rgb.width * factor), 1), max(int(rgb.height * factor), 1)), Image.LANCZOS)
    notes: dict = {}
    if rgb.width < OCR_MIN_WIDTH:
        factor = min(OCR_TARGET_WIDTH / rgb.width, 3.0)
        rgb = rgb.resize((int(rgb.width * factor), int(rgb.height * factor)), Image.LANCZOS)
        notes["upscaled"] = round(factor, 2)
    gray = ImageOps.grayscale(rgb)
    angle = estimate_skew(gray)
    if 0.25 <= abs(angle) <= 6:
        gray = gray.rotate(angle, resample=Image.BICUBIC, expand=False, fillcolor=255)
        rgb = rgb.rotate(angle, resample=Image.BICUBIC, expand=False, fillcolor=(255, 255, 255))
        notes["skew_corrected"] = angle
    gray = ImageOps.autocontrast(gray, cutoff=1)
    return rgb, gray, notes


_ONLY_MARKS = re.compile(r"^[|\\/_\-–—.,':;`~^*]{1,3}$")


def _keep_word(text: str, confidence: float) -> bool:
    """Descarta o risco de borda do scanner e o resto de tinta sem leitura."""
    if _ONLY_MARKS.match(text) and confidence < 85:
        return False
    if confidence < 10 and len(text) <= 2:
        return False
    return True


def recognize(image: Image.Image, languages: list[str] | None = None) -> tuple[list[Block], Image.Image, dict]:
    import pytesseract
    from pytesseract import Output

    if not configure_tesseract():
        raise OcrUnavailable()
    notes: dict = {"orientation": 0, "languages": []}
    oriented, angle = _rotate_right_angles(image.convert("RGB"))
    notes["orientation"] = angle
    prepared, gray, prep_notes = prepare_for_ocr(oriented)
    notes.update(prep_notes)
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
    try:
        data = pytesseract.image_to_data(gray, lang=lang, config=TESSERACT_CONFIG, output_type=Output.DICT)
    except pytesseract.TesseractNotFoundError as exc:
        raise OcrUnavailable(str(exc)) from exc
    except pytesseract.TesseractError:
        data = pytesseract.image_to_data(gray, lang=lang, output_type=Output.DICT)
    width, height = prepared.size
    grouped: dict[tuple, list[WordBox]] = {}
    order: list[tuple] = []
    for index in range(len(data["text"])):
        text = (data["text"][index] or "").strip()
        try:
            confidence = float(data["conf"][index])
        except (TypeError, ValueError):
            confidence = -1
        if not text or confidence < 0 or not _keep_word(text, confidence):
            continue
        word = WordBox(
            text,
            (
                float(data["left"][index]) / width,
                float(data["top"][index]) / height,
                float(data["width"][index]) / width,
                float(data["height"][index]) / height,
            ),
            confidence,
        )
        key = (int(data["block_num"][index]), int(data["par_num"][index]), int(data["line_num"][index]))
        if key not in grouped:
            grouped[key] = []
            order.append(key)
        grouped[key].append(word)
    lines: list[Block] = []
    for key in order:
        # Uma linha do Tesseract que atravessa a calha entre colunas vira duas.
        for segment in split_words_at_gutters(grouped[key]):
            block = line_block(segment, source="ocr")
            if block is not None:
                block.text = dehyphenate_text(block.text) if "- " in block.text else block.text
                lines.append(block)
    ordered = order_by_zones(lines)
    paragraphs = lines_to_paragraphs(ordered)
    return paragraphs, prepared, notes
