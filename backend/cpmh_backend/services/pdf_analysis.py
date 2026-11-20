from __future__ import annotations

from pathlib import Path

from PIL import Image

from cpmh_backend.hashing import crop_normalized, looks_blank, looks_partial
from cpmh_backend.intelligence import (
    Block,
    assess_formula,
    blocks_from_pdf_chars,
    classify_blocks,
    detect_text_table,
    guess_image_category,
    mark_repeated_chrome,
)
from cpmh_backend.services.ocr import recognize


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
    rendered = page.render(scale=2)
    image = rendered.to_pil().convert("RGB")
    rendered.close()
    text = "".join(char["ch"] for char in chars).strip()
    source = "pdf_text"
    notes: dict = {}
    if len(text) < 8:
        blocks, image, notes = recognize(image, languages)
        source = "ocr"
    else:
        blocks = blocks_from_pdf_chars(chars, page_width, page_height)
    embedded = _embedded_images(page, page_width, page_height)
    words = [word for block in blocks for word in block.words]
    table = detect_text_table(words, from_text_layer=source == "pdf_text")
    ruled = detect_ruled_tables(image)
    if table and ruled:
        table["confidence"] = max(table["confidence"], 94.0)
        table["reliable"] = True
        table["source"] = table["source"] + "+lines"
    elif not table and ruled:
        table = {
            "rows": [],
            "confidence": 35.0,
            "reliable": False,
            "source": "lines",
            "bbox": ruled[0]["bbox"],
            "notes": "Linhas de tabela detectadas sem células de texto confiáveis.",
        }
    if table and "bbox" not in table:
        table["bbox"] = (0.1, 0.2, 0.8, 0.3)
    kept: list[Block] = []
    for block in blocks:
        if table and table.get("rows") and _center_inside(block.bbox, table["bbox"]):
            continue
        kept.append(block)
    classify_blocks(kept)
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
                gap = block.bbox[1] - (iy + ih)
                overlap = min(ix + iw, block.bbox[0] + block.bbox[2]) - max(ix, block.bbox[0])
                if 0 <= gap < 0.06 and overlap > 0 and len(block.text) <= 180 and gap < best_gap:
                    best = block
                    best_gap = gap
            if best is not None:
                best.category = "caption"
                image["caption"] = best.text
