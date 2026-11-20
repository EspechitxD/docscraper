"""Projeção de caixas normalizadas para o documento aberto.

A caixa fica no sistema da página, não da janela. Zoom e rolagem do
navegador deslocam o documento inteiro, inclusive o overlay.
"""

from __future__ import annotations


def document_rect(
    bbox: tuple[float, float, float, float],
    page_width: float,
    page_height: float,
) -> tuple[float, float, float, float]:
    x, y, width, height = bbox
    return (x * page_width, y * page_height, width * page_width, height * page_height)


def viewport_rect(
    bbox: tuple[float, float, float, float],
    *,
    page_width: float,
    page_height: float,
    scroll_x: float,
    scroll_y: float,
    zoom: float,
) -> tuple[float, float, float, float]:
    x, y, width, height = document_rect(bbox, page_width, page_height)
    return ((x - scroll_x) * zoom, (y - scroll_y) * zoom, width * zoom, height * zoom)


def misalignment(expected: tuple[float, float], actual: tuple[float, float]) -> float:
    return max(abs(expected[0] - actual[0]), abs(expected[1] - actual[1]))
