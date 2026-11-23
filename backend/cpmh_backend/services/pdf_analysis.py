from __future__ import annotations

from pathlib import Path

from PIL import Image

from cpmh_backend.hashing import crop_normalized, looks_blank, looks_partial
from cpmh_backend.intelligence import (
    Block,
    assess_formula,
    blocks_from_pdf_chars,
    classify_blocks,
    demote_open_headings,
    detect_text_table,
    guess_image_category,
    lines_from_words,
    mark_repeated_chrome,
    reading_order,
)
from cpmh_backend.layout import is_multicolumn
from cpmh_backend.services.ocr import recognize

# O OCR lê a página em cerca de 300 DPI. A 144 DPI (escala 2) o Tesseract erra letras
# pequenas: "immeitely", "nates", "Parentheses". O texto digital não precisa disso.
OCR_RENDER_SCALE = 300 / 72
DISPLAY_RENDER_SCALE = 2


def _center_inside(block_bbox: tuple[float, float, float, float], table_bbox: tuple[float, float, float, float]) -> bool:
    cx = block_bbox[0] + block_bbox[2] / 2
    cy = block_bbox[1] + block_bbox[3] / 2
    x, y, width, height = table_bbox
    pad_x = min(0.008, width * 0.04)
    pad_y = min(0.008, max(height * 0.15, 0.002))
    return (x - pad_x) <= cx <= (x + width + pad_x) and (y - pad_y) <= cy <= (y + height + pad_y)


def detect_ruled_tables(image: Image.Image) -> list[dict]:
    try:
        import cv2
        import numpy as np
    except Exception:
        return []
    rgb = np.array(image.convert("RGB"))
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    binary = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 15, 8)
    height, width = binary.shape
    horizontal = cv2.morphologyEx(
        binary,
        cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_RECT, (max(18, width // 25), 1)),
    )
    vertical = cv2.morphologyEx(
        binary,
        cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(18, height // 25))),
    )
    grid = cv2.bitwise_or(horizontal, vertical)
    contours, _hierarchy = cv2.findContours(grid, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    found = []
    for contour in contours:
        x, y, box_w, box_h = cv2.boundingRect(contour)
        if box_w < width * 0.18 or box_h < height * 0.03:
            continue
        roi_h = horizontal[y : y + box_h, x : x + box_w]
        roi_v = vertical[y : y + box_h, x : x + box_w]
        row_lines = _line_centers(roi_h.sum(axis=1) > box_w * 0.35)
        col_lines = _line_centers(roi_v.sum(axis=0) > box_h * 0.35)
        if len(row_lines) < 2 or len(col_lines) < 2:
            continue
        found.append(
            {
                "bbox": (x / width, y / height, box_w / width, box_h / height),
                "rows": max(len(row_lines) - 1, 1),
                "cols": max(len(col_lines) - 1, 1),
                "row_lines": [(y + center) / height for center in row_lines],
                "col_lines": [(x + center) / width for center in col_lines],
            }
        )
    return found


def _line_centers(mask) -> list[int]:
    centers = []
    start = None
    for index, value in enumerate(mask):
        if value and start is None:
            start = index
        elif not value and start is not None:
            centers.append((start + index) // 2)
            start = None
    if start is not None:
        centers.append((start + len(mask)) // 2)
    return centers


def _embedded_images(page, page_width: float, page_height: float) -> list[tuple[Image.Image, tuple[float, float, float, float]]]:
    import pypdfium2 as pdfium

    extracted = []
    for obj in page.get_objects():
        if not isinstance(obj, pdfium.PdfImage):
            continue
        try:
            left, bottom, right, top = obj.get_bounds()
            bitmap = obj.get_bitmap()
            image = bitmap.to_pil().convert("RGB")
        except Exception:
            continue
        box_w = right - left
        box_h = top - bottom
        if page_width <= 0 or page_height <= 0:
            continue
        bbox = (
            left / page_width,
            (page_height - top) / page_height,
            box_w / page_width,
            box_h / page_height,
        )
        if bbox[2] > 0.9 and bbox[3] > 0.9:
            continue
        extracted.append((image, bbox))
    return extracted


def analyze_pdf(path: Path, languages: list[str]) -> dict:
    import pypdfium2 as pdfium

    document = pdfium.PdfDocument(str(path))
    pages = []
    try:
        for index in range(len(document)):
            page = document[index]
            try:
                pages.append(_analyze_page(page, index, languages))
            finally:
                page.close()
    finally:
        document.close()
    mark_repeated_chrome([page["blocks"] for page in pages])
    _attach_captions(pages)
    return {"page_count": len(pages), "pages": pages}


def _overlaps(first: tuple[float, float, float, float], second: tuple[float, float, float, float]) -> float:
    ax, ay, aw, ah = first
    bx, by, bw, bh = second
    width = min(ax + aw, bx + bw) - max(ax, bx)
    height = min(ay + ah, by + bh) - max(ay, by)
    if width <= 0 or height <= 0:
        return 0.0
    return width * height


def _grid_from_ruled_box(words: list, box: dict) -> list[list[str]] | None:
    row_lines = box.get("row_lines") or []
    col_lines = box.get("col_lines") or []
    if len(row_lines) < 2 or len(col_lines) < 2:
        return None
    buckets = [[[] for _ in range(len(col_lines) - 1)] for _ in range(len(row_lines) - 1)]
    for word in words:
        cx = word.bbox[0] + word.bbox[2] / 2
        cy = word.bbox[1] + word.bbox[3] / 2
        row = next((index for index in range(len(row_lines) - 1) if row_lines[index] <= cy < row_lines[index + 1]), None)
        column = next((index for index in range(len(col_lines) - 1) if col_lines[index] <= cx < col_lines[index + 1]), None)
        if row is None or column is None:
            continue
        buckets[row][column].append(word)
    grid = []
    for row in buckets:
        cells = []
        for words_in_cell in row:
            # Agrupa por linha com tolerância de base e ordena cada linha da esquerda para a direita.
            # Ordenar por (y arredondado, x) embaralhava a segunda linha com a primeira.
            lines = lines_from_words(words_in_cell)
            cells.append(" ".join(" ".join(item.text for item in line) for line in lines).strip())
        grid.append(cells)
    filled = sum(1 for row in grid for cell in row if cell)
    if filled < 4:
        return None
    return grid


def _table_from_rules_or_text(
    words: list, ruled: list[dict], *, from_text_layer: bool, multicolumn: bool = False
) -> dict | None:
    if not ruled:
        # Duas colunas de texto corrido têm um vão em toda linha e parecem uma tabela de duas
        # colunas. Sem linhas desenhadas, a página em colunas não gera tabela.
        if multicolumn:
            return None
        return detect_text_table(words, from_text_layer=from_text_layer)
    diagrams = _diagram_crops_boxes(ruled)
    candidates = []
    for box in ruled:
        if any(_center_inside((box["bbox"][0], box["bbox"][1], box["bbox"][2], box["bbox"][3]), diagram) for diagram in diagrams):
            continue
        candidates.append(box)
    if not candidates:
        return None
    best = max(candidates, key=lambda item: item["bbox"][2] * item["bbox"][3])
    inside = [word for word in words if _center_inside(word.bbox, best["bbox"])]
    grid = _grid_from_ruled_box(inside, best)
    if grid:
        return {
            "rows": grid,
            "confidence": 94.0,
            "reliable": True,
            "source": "lines+text",
            "bbox": best["bbox"],
        }
    return {
        "rows": [],
        "confidence": 35.0,
        "reliable": False,
        "source": "lines",
        "bbox": best["bbox"],
        "notes": "Linhas de tabela detectadas sem células de texto confiáveis.",
    }


def _diagram_crops_boxes(ruled: list[dict]) -> list[tuple[float, float, float, float]]:
    if len(ruled) < 2:
        return []
    ordered = sorted(ruled, key=lambda item: item["bbox"][1])
    groups: list[list[dict]] = [[ordered[0]]]
    for box in ordered[1:]:
        previous = groups[-1][-1]["bbox"]
        if box["bbox"][1] - (previous[1] + previous[3]) < 0.08:
            groups[-1].append(box)
        else:
            groups.append([box])
    boxes = []
    for group in groups:
        if len(group) < 2:
            continue
        x = min(item["bbox"][0] for item in group)
        y = min(item["bbox"][1] for item in group)
        right = max(item["bbox"][0] + item["bbox"][2] for item in group)
        bottom = max(item["bbox"][1] + item["bbox"][3] for item in group)
        bbox = (max(x - 0.07, 0.0), max(y - 0.04, 0.0), min(right - x + 0.08, 1.0), min(bottom - y + 0.05, 1.0))
        area = bbox[2] * bbox[3]
        if bbox[2] < 0.25 or bbox[3] < 0.1:
            continue
        if any(item["bbox"][2] * item["bbox"][3] > area * 0.75 for item in group):
            continue
        boxes.append(bbox)
    return boxes


def _diagram_crops(image: Image.Image, ruled: list[dict]) -> list[dict]:
    return [
        {
            "image": crop_normalized(image, bbox),
            "bbox": bbox,
            "category": "diagram",
            "confidence": 70.0,
        }
        for bbox in _diagram_crops_boxes(ruled)
    ]


def _analyze_page(page, index: int, languages: list[str]) -> dict:
    page_width, page_height = page.get_size()
    text_page = page.get_textpage()
    chars = []
    try:
        for char_index in range(text_page.count_chars()):
            box = text_page.get_charbox(char_index)
            chars.append(
                {
                    "ch": text_page.get_text_range(char_index, 1),
                    "x0": box[0],
                    "y0": box[1],
                    "x1": box[2],
                    "y1": box[3],
                }
            )
    finally:
        text_page.close()
    text = "".join(char["ch"] for char in chars).strip()
    source = "pdf_text"
    notes: dict = {}
    if len(text) < 8:
        rendered = page.render(scale=OCR_RENDER_SCALE)
        image = rendered.to_pil().convert("RGB")
        rendered.close()
        blocks, image, notes = recognize(image, languages)
        source = "ocr"
    else:
        rendered = page.render(scale=DISPLAY_RENDER_SCALE)
        image = rendered.to_pil().convert("RGB")
        rendered.close()
        blocks = blocks_from_pdf_chars(chars, page_width, page_height)
    embedded = _embedded_images(page, page_width, page_height)
    words = [word for block in blocks for word in block.words]
    ruled = detect_ruled_tables(image)
    table = _table_from_rules_or_text(
        words,
        ruled,
        from_text_layer=source == "pdf_text",
        multicolumn=is_multicolumn([block.bbox for block in blocks]),
    )
    diagram_boxes = _diagram_crops_boxes(ruled)
    # Tabela deduzida só do alinhamento do OCR não é confiável. Ela não pode apagar o texto da página.
    removes_text = bool(table and table.get("rows") and (table.get("reliable") or table.get("source") == "lines+text"))
    kept: list[Block] = []
    for block in blocks:
        if removes_text and _center_inside(block.bbox, table["bbox"]):
            continue
        if any(_center_inside(block.bbox, box) for box in diagram_boxes):
            continue
        kept.append(block)
    classify_blocks(kept)
    demote_open_headings(reading_order(kept))
    formulas = []
    for block in kept:
        if block.category in {"formula", "equation"}:
            reliable, note = assess_formula(block.text)
            crop = crop_normalized(image, block.bbox)
            formulas.append({"block": block, "reliable": reliable, "notes": note, "crop": crop})
    images = []
    for embedded_image, bbox in embedded:
        category, confidence = guess_image_category(embedded_image)
        images.append({"image": embedded_image, "bbox": bbox, "category": category, "confidence": confidence})
    for diagram in _diagram_crops(image, ruled):
        images.append(diagram)
    blank = looks_blank(image) and not text
    partial = looks_partial(image) and not text
    return {
        "sequence": index + 1,
        "image": image,
        "width": image.width,
        "height": image.height,
        "blocks": kept,
        "table": table,
        "formulas": formulas,
        "images": images,
        "blank": blank,
        "partial": partial,
        "source": source,
        "notes": notes,
        "reported_number": _page_number(kept),
    }


def _page_number(blocks: list[Block]) -> str:
    for block in blocks:
        if block.category == "page_number":
            return block.text
    return ""


def _attach_captions(pages: list[dict]) -> None:
    for page in pages:
        for image in page["images"]:
            ix, iy, iw, ih = image["bbox"]
            best = None
            best_gap = 1.0
            for block in page["blocks"]:
                below = block.bbox[1] - (iy + ih)
                above = iy - (block.bbox[1] + block.bbox[3])
                gap = below if 0 <= below else above
                overlap = min(ix + iw, block.bbox[0] + block.bbox[2]) - max(ix, block.bbox[0])
                if 0 <= gap < 0.08 and overlap > 0 and len(block.text) <= 180 and gap < best_gap:
                    best = block
                    best_gap = gap
            if best is not None:
                best.category = "caption"
                image["caption"] = best.text
