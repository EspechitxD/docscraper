"""Funções puras de idioma, layout, continuidade, tabelas, fórmulas e fim de captura."""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field

CATEGORIES = (
    "title",
    "subtitle",
    "paragraph",
    "running_text",
    "header",
    "footer",
    "page_number",
    "image",
    "photograph",
    "chart",
    "table",
    "formula",
    "caption",
    "footnote",
    "reference",
    "equation",
    "diagram",
    "unknown",
)

TRADITIONAL_MARKERS = set(
    "醫國書東車門長頭體學電對過還這時開個會說現發點線經當應種樣關問動員機給實業產義親歷條達選適節鐵題藥術與為來們從鈦廣漢語"
)
SIMPLIFIED_MARKERS = set(
    "医国书东车门长头体学电对过还这时开个会说现发点线经当应种样关问动员机给实业产义亲历条达选适节铁题药术与为来们从钛广汉语"
)

_PAGE_NUMBER = re.compile(r"^(p[áa]g(?:ina)?\.?\s*)?\d{1,4}(\s*(/|de|of)\s*\d{1,4})?$", re.IGNORECASE)
_CAPTION = re.compile(r"^(fig(?:ura|\.)?|tabela|table|quadro|imagem|gr[áa]fico)\b", re.IGNORECASE)
_REFERENCE = re.compile(r"^(\[\d+\]|\d+\.\s+\S.+\(\d{4}\))")
_SIMPLE_EQUATION = re.compile(r"^[A-Za-zα-ωΑ-Ωµ][A-Za-zα-ωΑ-Ωµ0-9_ ]{0,16}=\s*\S+")
_MATH = set("=+-−±×÷∑∫√∞≤≥≠≈∂∆παβγμσθλφωΩ^_/{}[]²³¹⁰")


@dataclass
class WordBox:
    text: str
    bbox: tuple[float, float, float, float]
    confidence: float = 99.0


@dataclass
class Block:
    text: str
    bbox: tuple[float, float, float, float]
    confidence: float = 99.0
    source: str = "pdf_text"
    font_size: float = 0.0
    category: str = "paragraph"
    language: str = ""
    level: int = 0
    words: list[WordBox] = field(default_factory=list)


@dataclass
class PageObservation:
    content_hash: str
    phash: str
    counter_current: int | None = None
    counter_total: int | None = None
    next_present: bool = False
    next_disabled: bool | None = None
    blank: bool = False
    partial: bool = False


def confidence_band(score: float, high: float, medium: float) -> str:
    if score >= high:
        return "high"
    if score >= medium:
        return "medium"
    return "low"


def detect_language(text: str) -> str:
    chars = [char for char in text if not char.isspace()]
    if len(chars) < 2:
        return ""
    han = [char for char in chars if "\u4e00" <= char <= "\u9fff"]
    latin = [char for char in chars if char.isascii() and char.isalpha() or char in "áàâãéêíóôõúçÁÀÂÃÉÊÍÓÔÕÚÇ"]
    if len(han) >= 2 and len(latin) >= 8:
        return "mul"
    if len(han) >= 2 and len(han) >= len(latin):
        traditional = sum(1 for char in chars if char in TRADITIONAL_MARKERS)
        simplified = sum(1 for char in chars if char in SIMPLIFIED_MARKERS)
        if traditional > simplified:
            return "chi_tra"
        if simplified > traditional:
            return "chi_sim"
        return "zh"
    if len(latin) < 12:
        return ""
    if any(char in text for char in "ãõçáéíóúâêôÃÕÇÁÉÍÓÚÂÊÔ") and not re.search(r"\b(the|and|of|for)\b", text, re.I):
        return "por"
    try:
        from langdetect import DetectorFactory, detect

        DetectorFactory.seed = 0
        code = detect(text)
    except Exception:
        return "unknown"
    return {"pt": "por", "en": "eng", "zh-cn": "chi_sim", "zh-tw": "chi_tra"}.get(code, code)


def aggregate_language(texts: list[tuple[str, str]]) -> str:
    scores: dict[str, int] = {}
    for language, text in texts:
        if not language or language in {"unknown", "mul", "zh"}:
            continue
        scores[language] = scores.get(language, 0) + max(len(text), 1)
    if not scores:
        return ""
    ordered = sorted(scores, key=scores.get, reverse=True)
    if len(ordered) > 1 and scores[ordered[1]] > scores[ordered[0]] * 0.45:
        return "mul"
    return ordered[0]


def _is_formula(text: str) -> bool:
    stripped = " ".join(text.split())
    if not stripped or len(stripped) > 180:
        return False
    if _SIMPLE_EQUATION.match(stripped) and len(stripped.split()) <= 8:
        return True
    chars = [char for char in stripped if not char.isspace()]
    if not chars:
        return False
    symbolish = sum(1 for char in chars if char in _MATH or char.isdigit())
    has_relation = any(char in stripped for char in "=∫∑√≤≥±×÷")
    return bool(has_relation and len(stripped.split()) <= 10 and symbolish / len(chars) >= 0.45)


def assess_formula(text: str) -> tuple[bool, str]:
    stripped = text.strip()
    if any(char in stripped for char in "∫∑∏√"):
        return False, "Fórmula com símbolos complexos. O recorte original é preservado para revisão."
    if len(stripped) > 80 or stripped.count("=") > 1:
        return False, "Expressão longa demais para reconstrução editável confiável."
    if _is_formula(stripped):
        return True, "Expressão linear simples preservada como texto."
    return False, "Reconhecimento insuficiente. O recorte original é preservado."


def _norm_key(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def classify_blocks(blocks: list[Block]) -> list[Block]:
    heights = [
        block.font_size or block.bbox[3]
        for block in blocks
        if len(block.text.strip()) >= 8 and (block.font_size or block.bbox[3]) > 0
    ]
    median = statistics.median(heights) if heights else 0.02
    for block in blocks:
        text = " ".join(block.text.split())
        block.text = text
        y = block.bbox[1]
        height = block.font_size or block.bbox[3]
        if _PAGE_NUMBER.match(text):
            block.category = "page_number"
            block.level = 0
            continue
        if _is_formula(text):
            block.category = "equation" if any(char in text for char in "∫∑∏√") else "formula"
            block.level = 0
            continue
        if y < 0.055 and len(text) <= 160:
            block.category = "header"
            continue
        if y > 0.925 and len(text) <= 180:
            block.category = "footer"
            continue
        if _CAPTION.match(text):
            block.category = "caption"
            continue
        if _REFERENCE.match(text):
            block.category = "reference"
            continue
        if height >= median * 1.22 and len(text) <= 90 and y < 0.35 and not text.endswith("."):
            block.category = "title"
            block.level = 1
            continue
        if height >= median * 1.18 and len(text) <= 120 and not text.endswith(".") and y < 0.7:
            block.category = "subtitle"
            block.level = 2
            continue
        block.category = "paragraph"
        block.level = 0
    return blocks


def mark_repeated_chrome(pages: list[list[Block]]) -> None:
    if len(pages) < 2:
        return
    tops: dict[str, int] = {}
    bottoms: dict[str, int] = {}
    for blocks in pages:
        seen_top: set[str] = set()
        seen_bottom: set[str] = set()
        for block in blocks:
            key = _norm_key(block.text)
            if len(key) < 2:
                continue
            if block.bbox[1] < 0.11 and key not in seen_top:
                tops[key] = tops.get(key, 0) + 1
                seen_top.add(key)
            if block.bbox[1] > 0.89 and key not in seen_bottom:
                bottoms[key] = bottoms.get(key, 0) + 1
                seen_bottom.add(key)
    for blocks in pages:
        for block in blocks:
            key = _norm_key(block.text)
            if block.category == "page_number":
                continue
            if key in tops and tops[key] >= 2 and block.bbox[1] < 0.12:
                block.category = "header"
            elif key in bottoms and bottoms[key] >= 2 and block.bbox[1] > 0.88:
                block.category = "footer"


def reading_order(blocks: list[Block]) -> list[Block]:
    chrome = [block for block in blocks if block.category in {"header", "footer", "page_number"}]
    body = [block for block in blocks if block not in chrome]
    ordered_body = _order_body(body)
    headers = sorted((block for block in chrome if block.category == "header"), key=lambda block: block.bbox[0])
    footers = sorted(
        (block for block in chrome if block.category in {"footer", "page_number"}),
        key=lambda block: block.bbox[0],
    )
    return headers + ordered_body + footers


def _order_body(body: list[Block]) -> list[Block]:
    if len(body) < 2:
        return list(body)
    lefts = sorted(block.bbox[0] for block in body)
    groups: list[list[float]] = []
    for value in lefts:
        if not groups or value - groups[-1][-1] > 0.15:
            groups.append([value])
        else:
            groups[-1].append(value)
    substantial = [group for group in groups if len(group) >= 2]
    if len(substantial) >= 2:
        boundary = (max(substantial[0]) + min(substantial[1])) / 2
        left = [block for block in body if (block.bbox[0] + block.bbox[2] / 2) < boundary]
        right = [block for block in body if block not in left]
        if left and right:
            left.sort(key=lambda block: (round(block.bbox[1], 3), block.bbox[0]))
            right.sort(key=lambda block: (round(block.bbox[1], 3), block.bbox[0]))
            return left + right
    return sorted(body, key=lambda block: (round(block.bbox[1], 3), block.bbox[0]))


def lines_from_words(words: list[WordBox]) -> list[list[WordBox]]:
    ordered = sorted(words, key=lambda word: (word.bbox[1], word.bbox[0]))
    lines: list[list[WordBox]] = []
    for word in ordered:
        if not word.text.strip():
            continue
        if lines:
            reference = lines[-1][0]
            tolerance = max(word.bbox[3], reference.bbox[3], 0.008) * 0.7
            if abs(word.bbox[1] - reference.bbox[1]) <= tolerance:
                lines[-1].append(word)
                continue
        lines.append([word])
    for line in lines:
        line.sort(key=lambda word: word.bbox[0])
    return lines


def detect_text_table(words: list[WordBox], *, from_text_layer: bool = False) -> dict | None:
    lines = lines_from_words(words)
    if len(lines) < 2:
        return None
    split_sets: list[list[float]] = []
    for line in lines:
        if len(line) < 2:
            split_sets.append([])
            continue
        gaps = []
        for left, right in zip(line, line[1:]):
            gap = right.bbox[0] - (left.bbox[0] + left.bbox[2])
            midpoint = (left.bbox[0] + left.bbox[2] + right.bbox[0]) / 2
            gaps.append((gap, midpoint))
        typical = statistics.median(gap for gap, _mid in gaps)
        # Células de uma palavra têm só lacunas grandes e parecidas.
        # Células com várias palavras têm lacunas internas pequenas e lacunas de coluna maiores.
        splits = [mid for gap, mid in gaps if gap >= 0.06]
        split_sets.append(splits)
    aligned = [splits for splits in split_sets if splits]
    if len(aligned) < 2:
        return None
    columns = _cluster_values([value for splits in aligned for value in splits], gap=0.03)
    if len(columns) < 1:
        return None
    # Uma divisão estável produz duas colunas.
    if len(columns) < 1 or len(aligned) < 2:
        return None
    usable = [index for index, splits in enumerate(split_sets) if splits]
    if len(usable) < 2:
        return None
    boundaries = [0.0, *columns, 1.0]
    grid: list[list[str]] = []
    confidences: list[float] = []
    for index in usable:
        cells = [""] * (len(boundaries) - 1)
        for word in lines[index]:
            center = word.bbox[0] + word.bbox[2] / 2
            column = 0
            for position, edge in enumerate(boundaries[1:]):
                if center <= edge:
                    column = position
                    break
            cells[column] = (cells[column] + " " + word.text).strip()
            confidences.append(word.confidence)
        if any(cell.strip() for cell in cells):
            grid.append(cells)
    if len(grid) < 2 or len(grid[0]) < 2:
        return None
    cell_lengths = [len(cell.split()) for row in grid for cell in row if cell.strip()]
    if cell_lengths and statistics.median(cell_lengths) >= 4:
        return None
    if grid and all(not re.search(r"[\w]", cell, re.UNICODE) for row in grid for cell in row):
        return None
    width = len(grid[0])
    if any(len(row) != width for row in grid):
        return None
    filled = sum(1 for row in grid for cell in row if cell.strip())
    if filled < 4:
        return None
    confidence = statistics.fmean(confidences) if confidences else 60.0
    # Texto digital alinhado não é inventado: veio da camada de texto.
    # OCR alinhado permanece para revisão até haver confirmação visual das linhas.
    if from_text_layer:
        reliable = True
        confidence = max(confidence, 92.0)
    else:
        reliable = False
        confidence = min(confidence, 78.0)
    used = [word for index in range(min(usable), max(usable) + 1) for word in lines[index]]
    x = min(word.bbox[0] for word in used)
    y = min(word.bbox[1] for word in used)
    right = max(word.bbox[0] + word.bbox[2] for word in used)
    bottom = max(word.bbox[1] + word.bbox[3] for word in used)
    return {
        "rows": grid,
        "confidence": round(confidence, 2),
        "reliable": reliable,
        "source": "text-layer" if from_text_layer else "text-alignment",
        "bbox": (x, y, max(right - x, 0.01), max(bottom - y, 0.01)),
    }


def _cluster_values(values: list[float], gap: float) -> list[float]:
    if not values:
        return []
    ordered = sorted(values)
    groups = [[ordered[0]]]
    for value in ordered[1:]:
        if value - groups[-1][-1] > gap:
            groups.append([value])
        else:
            groups[-1].append(value)
    return [statistics.fmean(group) for group in groups]


def merge_table_rows(rows: list[list[str]], continuation: list[list[str]]) -> list[list[str]]:
    if not rows or not continuation:
        return rows or continuation
    if len(rows[0]) != len(continuation[0]):
        return rows
    body = continuation
    if rows[0] == continuation[0]:
        body = continuation[1:]
    return rows + body


def tables_can_continue(previous: dict, nxt: dict) -> bool:
    if previous.get("page_sequence", -1) + 1 != nxt.get("page_sequence"):
        return False
    prev_rows = previous.get("rows") or []
    next_rows = nxt.get("rows") or []
    if not prev_rows or not next_rows or len(prev_rows[0]) != len(next_rows[0]):
        return False
    if previous.get("y", 0) + previous.get("h", 0) < 0.72:
        return False
    if nxt.get("y", 1) > 0.28:
        return False
    return True


@dataclass
class FlowPiece:
    id: str
    kind: str
    text: str
    page_index: int
    bbox: tuple[float, float, float, float]
    skip: bool = False
    continued_from: str | None = None
    continued_in: str | None = None


def link_page_continuity(pieces: list[FlowPiece]) -> list[FlowPiece]:
    candidates = [piece for piece in pieces if piece.kind in {"paragraph", "running_text"}]
    for previous, nxt in zip(candidates, candidates[1:]):
        if previous.skip or nxt.skip:
            continue
        if nxt.page_index != previous.page_index + 1:
            continue
        left = previous.text.rstrip()
        right = nxt.text.lstrip()
        if not left or not right:
            continue
        hyphenated = left.endswith("-")
        open_sentence = not left.endswith((".", "?", "!", "。", "！", "？", ";", ":"))
        continues_lower = right[:1].islower()
        if hyphenated or (open_sentence and continues_lower):
            if hyphenated:
                previous.text = left[:-1] + right
            else:
                previous.text = left + " " + right
            previous.continued_in = nxt.id
            nxt.continued_from = previous.id
            nxt.skip = True
    return pieces


def guess_image_category(image) -> tuple[str, float]:
    sample = image.convert("RGB").resize((24, 24))
    colors = sample.getcolors(24 * 24) or []
    unique = len(colors)
    if unique <= 6:
        return "diagram", 42.0
    if unique <= 18:
        return "chart", 40.0
    return "photograph", 38.0


def decide_capture(history: list[PageObservation], *, hit_max: bool = False) -> str:
    """Combina sinais. Não declara captura completa só porque a rolagem parou."""
    if not history:
        return "continue"
    last = history[-1]
    end_by_counter = (
        last.counter_current is not None
        and last.counter_total is not None
        and last.counter_total > 0
        and last.counter_current >= last.counter_total
    )
    end_by_button = bool(last.next_present and last.next_disabled is True)
    if end_by_counter or end_by_button:
        return "complete"
    if last.blank or last.partial:
        blanks = 0
        for item in reversed(history):
            if item.blank or item.partial:
                blanks += 1
            else:
                break
        if blanks >= 2:
            return "inconclusive"
        return "continue"
    if len(history) >= 2:
        previous = history[-2]
        if (
            previous.counter_current is not None
            and last.counter_current is not None
            and last.counter_current > previous.counter_current + 1
        ):
            return "inconclusive"
    if len(history) >= 2:
        previous = history[-2]
        same = last.content_hash == previous.content_hash
        if not same and last.phash and previous.phash and len(last.phash) == len(previous.phash):
            distance = sum(a != b for a, b in zip(last.phash, previous.phash))
            same = distance <= 4
        if same:
            if end_by_counter or end_by_button:
                return "complete"
            duplicates = 1
            for older in reversed(history[:-1]):
                if older.content_hash == last.content_hash:
                    duplicates += 1
                else:
                    break
            if duplicates >= 3:
                return "inconclusive"
            return "continue"
    if end_by_counter or end_by_button:
        return "complete"
    if not last.next_present and last.counter_total is None:
        return "complete"
    if hit_max:
        return "inconclusive"
    return "continue"


def blocks_from_pdf_chars(chars: list[dict], page_width: float, page_height: float) -> list[Block]:
    if page_width <= 0 or page_height <= 0:
        return []
    items = []
    for char in chars:
        text = char.get("ch", "")
        if text == "":
            continue
        if text in {"\n", "\r"}:
            items.append({"break": True, "top": page_height, "x0": 0, "height": 1, "ch": text, "x1": 0})
            continue
        x0, y0, x1, y1 = char["x0"], char["y0"], char["x1"], char["y1"]
        height = max(y1 - y0, 0.0)
        top = page_height - max(y1, y0)
        baseline = page_height - min(y0, y1)
        if height < 0.8 and text.strip() == "":
            # Espaço com caixa degenerada: entra no texto, sem definir a altura da linha.
            items.append(
                {
                    "ch": " ",
                    "x0": x0,
                    "x1": max(x1, x0 + 0.5),
                    "top": top,
                    "baseline": baseline,
                    "height": 0.0,
                    "space": True,
                }
            )
            continue
        items.append(
            {
                "ch": text,
                "x0": x0,
                "x1": x1,
                "top": top,
                "baseline": baseline,
                "height": max(height, 0.4),
            }
        )
    lines: list[dict] = []
    for item in items:
        if item.get("break"):
            lines.append({"top": 0, "height": 1, "items": [], "break": True})
            continue
        if item.get("space") and lines and lines[-1]["items"]:
            lines[-1]["items"].append(item)
            continue
        if lines and not lines[-1].get("break") and lines[-1]["items"]:
            reference = next((entry for entry in lines[-1]["items"] if entry.get("height", 0) >= 0.8), lines[-1]["items"][-1])
            tolerance = max(reference.get("height", 1), item["height"], 1) * 0.65
            line_right = max(entry["x1"] for entry in lines[-1]["items"])
            column_gap = item["x0"] - line_right
            same_baseline = abs(item.get("baseline", item["top"]) - reference.get("baseline", reference["top"])) <= tolerance
            if same_baseline and column_gap < 28:
                lines[-1]["items"].append(item)
                lines[-1]["height"] = max(lines[-1]["height"], item["height"])
                lines[-1]["top"] = min(entry["top"] for entry in lines[-1]["items"] if not entry.get("space"))
                continue
        lines.append({"top": item["top"], "height": max(item["height"], 1), "items": [item]})
    line_blocks: list[Block] = []
    for line in lines:
        ordered = sorted(line["items"], key=lambda item: item["x0"])
        widths = [item["x1"] - item["x0"] for item in ordered if item["ch"].strip()]
        typical = statistics.median(widths) if widths else 4
        text = ""
        previous = None
        for item in ordered:
            if previous is not None:
                gap = item["x0"] - previous["x1"]
                punctuation = {",", ".", ";", ":", ")", "]", "”", "_"}
                if (
                    gap > max(typical * 0.45, 2.4)
                    and not text.endswith(" ")
                    and item["ch"] not in punctuation
                    and previous["ch"] not in punctuation
                ):
                    text += " "
            text += item["ch"]
            previous = item
        text = re.sub(r"[ \t]+", " ", text).strip()
        if not text:
            continue
        x0 = min(item["x0"] for item in ordered)
        x1 = max(item["x1"] for item in ordered)
        top = min(item["top"] for item in ordered)
        bottom = max(item["top"] + item["height"] for item in ordered)
        bbox = (
            x0 / page_width,
            top / page_height,
            max(x1 - x0, 0.5) / page_width,
            max(bottom - top, 0.5) / page_height,
        )
        words = []
        for piece in text.split(" "):
            if piece:
                words.append(WordBox(piece, bbox, 99.0))
        # Palavras com caixas individuais aproximadas pela linha inteira não servem para tabela.
        words = _words_from_line_items(ordered, page_width, page_height)
        line_blocks.append(
            Block(
                text=text,
                bbox=bbox,
                confidence=99.0,
                source="pdf_text",
                font_size=line["height"] / page_height,
                words=words,
            )
        )
    paragraphs: list[Block] = []
    for line in line_blocks:
        if paragraphs:
            previous = paragraphs[-1]
            gap = line.bbox[1] - (previous.bbox[1] + previous.bbox[3])
            same_column = abs(line.bbox[0] - previous.bbox[0]) < 0.08
            same_size = abs(line.font_size - previous.font_size) <= max(previous.font_size, 0.001) * 0.25
            same_band = abs(line.bbox[1] - previous.bbox[1]) < 0.02
            if line.text.strip() in {".", ",", ";", ":", "?", "!"} and same_band:
                previous.text = (previous.text + line.text.strip()).strip()
                x = min(previous.bbox[0], line.bbox[0])
                right = max(previous.bbox[0] + previous.bbox[2], line.bbox[0] + line.bbox[2])
                bottom = line.bbox[1] + line.bbox[3]
                previous.bbox = (x, previous.bbox[1], right - x, bottom - previous.bbox[1])
                previous.words.extend(line.words)
                continue
            if (
                gap < max(line.font_size, 0.01) * 0.85
                and same_column
                and same_size
                and not _is_formula(line.text)
                and not _is_formula(previous.text)
            ):
                previous.text = (previous.text + " " + line.text).strip()
                x = min(previous.bbox[0], line.bbox[0])
                y = previous.bbox[1]
                right = max(previous.bbox[0] + previous.bbox[2], line.bbox[0] + line.bbox[2])
                bottom = line.bbox[1] + line.bbox[3]
                previous.bbox = (x, y, right - x, bottom - y)
                previous.words.extend(line.words)
                continue
        paragraphs.append(line)
    return paragraphs


def _words_from_line_items(items: list[dict], page_width: float, page_height: float) -> list[WordBox]:
    words: list[WordBox] = []
    buffer: list[dict] = []

    def flush() -> None:
        if not buffer:
            return
        text = "".join(item["ch"] for item in buffer).strip()
        if text:
            x0 = min(item["x0"] for item in buffer)
            x1 = max(item["x1"] for item in buffer)
            top = min(item["top"] for item in buffer)
            bottom = max(item["top"] + item["height"] for item in buffer)
            words.append(
                WordBox(
                    text,
                    (
                        x0 / page_width,
                        top / page_height,
                        max(x1 - x0, 0.4) / page_width,
                        max(bottom - top, 0.4) / page_height,
                    ),
                )
            )
        buffer.clear()

    widths = [item["x1"] - item["x0"] for item in items if item["ch"].strip()]
    typical = statistics.median(widths) if widths else 4
    previous = None
    for item in items:
        if item["ch"].isspace():
            flush()
            previous = item
            continue
        if previous is not None and not previous["ch"].isspace():
            gap = item["x0"] - previous["x1"]
            punctuation = {",", ".", ";", ":", ")", "]", "”", "_"}
            if gap > max(typical * 0.45, 2.4) and item["ch"] not in punctuation and previous["ch"] not in punctuation:
                flush()
        buffer.append(item)
        previous = item
    flush()
    return words
