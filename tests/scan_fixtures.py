"""Página escaneada sintética em duas colunas, no estilo de norma técnica. Texto original."""

from __future__ import annotations

import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

_FONTS = "/usr/share/fonts/truetype/dejavu/"

PARAGRAPHS = [
    ("h", "1. Scope"),
    ("p", "1.1 This guide provides considerations for validating inspection processes for medical devices during initial fabrication and assembly prior to first use."),
    ("h", "1.2 Exclusions"),
    ("p", "1.2.1 This guide does not describe the validation of reusable medical devices in health care facilities. Although inspection of reusable devices is beyond the scope of this guide, many principles may be applicable."),
    ("p", "1.3 This standard does not purport to address all of the safety concerns, if any, associated with its use. It is the responsibility of the user to establish appropriate practices."),
    ("h", "2. Referenced Documents"),
    ("p", "2.1 Reference Standards: F2459 Test Method for Extracting Residue; F2459 is cited again here; E200 Guide for Validating Analytical Methods."),
    ("h", "3. Terminology"),
    ("p", "3.1.1 analyte, n\u2014a substance for which an analysis is being performed. The determination may be qualitative, quantitative, or non-specific in nature and depends on the method."),
    ("p", "3.1.2 blank, n\u2014an analytical sample taken to establish the background value for a measurement which may be subtracted from an experimental value."),
    ("p", "3.1.3 residue, n\u2014a substance present at the surface of an item that is not explicitly recognized as part of the specification of the item under test."),
    ("h", "4. Summary of Practice"),
    ("p", "4.1 This guide provides an approach for validating the removal of contaminants and residues introduced during intermediate process steps so that the terminal process can result in a consistently clean medical device."),
    ("h", "5. Significance and Use"),
    ("p", "5.1 This guide describes an approach to validate a system for a medical device. It is based on the manufacturer's accurate and comprehensive understanding of internal manufacturing and inspection processes."),
    ("p", "5.2 This guide is not intended to provide a detailed plan or road map, but will provide considerations that can be used by the device manufacturer to develop a detailed plan."),
    ("h", "6. General Requirements"),
    ("p", "6.1 This guidance is divided into three sets of activities: understanding the upstream manufacturing process, documenting the inspection process, and establishing the measurement tools."),
]


def build_two_column_scan(path: Path, dpi: int = 200, noise: float = 0.0008) -> None:
    width, height = int(8.5 * dpi), int(11 * dpi)
    scale = dpi / 72.0

    def font(size, bold=False, serif=True):
        name = {(True, True): "DejaVuSerif-Bold", (True, False): "DejaVuSerif", (False, True): "DejaVuSans-Bold"}[(serif, bold)]
        return ImageFont.truetype(f"{_FONTS}{name}.ttf", int(size * scale))

    image = Image.new("L", (width, height), 255)
    draw = ImageDraw.Draw(image)
    margin, gutter = int(0.8 * dpi), int(0.3 * dpi)
    col_w = (width - 2 * margin - gutter) // 2
    body, bold = font(9.2), font(9.2, True)
    draw.text((margin, int(0.55 * dpi)), "Designation: E9999 \u2212 16", font=font(10, True, False), fill=0)
    draw.text((margin, int(0.95 * dpi)), "Standard Guide for Validating Inspection Processes", font=font(15, True, False), fill=0)
    draw.text((margin, int(1.25 * dpi)), "Used During the Manufacture of Medical Devices", font=font(15, True, False), fill=0)

    def wrap(text, f, limit):
        lines, current = [], ""
        for word in text.split():
            trial = (current + " " + word).strip()
            if draw.textlength(trial, font=f) <= limit:
                current = trial
            else:
                lines.append(current)
                current = word
        return lines + ([current] if current else [])

    line_h = int(9.2 * scale * 1.32)
    y0, y_max = int(1.85 * dpi), height - int(1.0 * dpi)
    col, y = 0, y0
    for kind, text in PARAGRAPHS:
        f = bold if kind == "h" else body
        if kind == "h":
            y += int(line_h * 0.5)
        for index, line in enumerate(wrap(text, f, col_w - int(0.2 * dpi))):
            if y + line_h > y_max and col == 0:
                col, y = 1, y0
            indent = int(0.18 * dpi) if kind == "p" and index == 0 else 0
            draw.text((margin + col * (col_w + gutter) + indent, y), line, font=f, fill=0)
            y += line_h
        y += int(line_h * 0.35)
    draw.text((margin, height - int(0.7 * dpi)), "Copyright by Example Org. Licensed to a test user.", font=font(7.4), fill=0)
    image = image.filter(ImageFilter.GaussianBlur(0.5))
    rnd = random.Random(1)
    pixels = image.load()
    for _ in range(int(width * height * noise)):
        pixels[rnd.randrange(width), rnd.randrange(height)] = rnd.randrange(120, 255)
    image = image.rotate(0.4, resample=Image.BICUBIC, fillcolor=255)
    image.convert("RGB").save(path, "PDF", resolution=dpi)
