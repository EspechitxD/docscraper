"""Estrutura de página: colunas, ordem de leitura e montagem de parágrafos.

Tudo aqui é função pura sobre caixas normalizadas (0 a 1). Nada chama OCR.

Por que este módulo existe: em normas técnicas e artigos em duas colunas, a ordem do texto
e o ponto onde um parágrafo começa vêm da geometria da página, não só do espaço vertical.
A versão anterior juntava toda linha seguinte que estivesse perto da anterior. O resultado
era "1. Scope 1.1 This guide ... 1.2 Exclusions 1.2.1 This guide ..." num bloco só.
"""

from __future__ import annotations

import re
import statistics
from typing import Callable, Sequence

from cpmh_backend.intelligence import Block, WordBox

Box = tuple[float, float, float, float]

# Número de cláusula ou marcador de lista no começo da linha: 1.  1.2  7.3.5.1  (1)  (a)  a)  X1.2  Note 1
CLAUSE_START = re.compile(
    r"^(?:"
    r"\d{1,2}(?:\.\d{1,3}){1,5}\.?"  # 1.2   7.3.5.1
    r"|\d{1,2}\."  # 1.
    r"|[A-Z]{1,2}\d{1,2}(?:\.\d{1,3}){1,4}"  # X1.2  A2.3.1
    r"|\(\d{1,2}\)"  # (1)
    r"|\([a-z]\)"  # (a)
    r"|[a-z]\)"  # a)
    r"|(?:NOTE|Note|Nota|NOTA)\s*\d{0,2}\s*[—–:-]"  # Note 1—
    r")\s+\S"
)

# Prefixos que formam palavra composta de verdade ("non-specific", "in-process").
# Quando a linha termina nesse prefixo + hífen, o hífen é do autor e fica.
COMPOUND_PREFIXES = frozenset(
    {
        "non", "in", "re", "pre", "post", "anti", "semi", "multi", "self", "cross", "well", "low",
        "high", "long", "short", "real", "sub", "co", "ex", "inter", "intra", "micro", "bi", "uni",
        "tri", "all", "half", "ill", "mid", "off", "on", "out", "over", "under", "up", "down",
        "single", "double", "end", "full", "time", "day", "year", "case", "risk", "so", "by",
        "não", "sem", "auto", "ex", "pós", "pré", "vice",
    }
)

_DANGLING = re.compile(
    r"\b(?:and|or|of|the|to|in|for|with|by|at|on|an|as|is|are|be|that|which|from|"
    r"de|da|do|das|dos|e|ou|para|com|em|os|um|uma|que|se|por)$",
    re.IGNORECASE,
)
_TERMINAL = (".", "?", "!", ":", ";", "。", "！", "？", "”", '"')


def box_of(block: Block) -> Box:
    return block.bbox


# ---------------------------------------------------------------------------
# Colunas
# ---------------------------------------------------------------------------


def find_gutters(
    boxes: Sequence[Box],
    *,
    min_width: float = 0.009,
    wide: float = 0.55,
    lo: float = 0.18,
    hi: float = 0.82,
    min_side: int = 2,
    tolerance: float = 0.04,
) -> list[tuple[float, float]]:
    """Acha as calhas verticais entre colunas de texto.

    Blocos largos (títulos, figuras) não contam. Um bloco estreito que cruza a calha, como um
    título centralizado, também não a desfaz, porque a cobertura é medida por peso de linhas e
    aceita uma pequena fração de invasão.
    """
    narrow = [box for box in boxes if 0 < box[2] <= wide and box[3] > 0]
    if len(narrow) < 2 * min_side:
        return []
    bins = 400
    coverage = [0.0] * bins
    total = 0.0
    for x, _y, w, h in narrow:
        total += h
        first = max(int(x * bins), 0)
        last = min(int((x + w) * bins), bins - 1)
        for index in range(first, last + 1):
            coverage[index] += h
    if total <= 0:
        return []
    limit = total * tolerance
    gutters: list[tuple[float, float]] = []
    start: int | None = None
    for index in range(bins + 1):
        empty = index < bins and coverage[index] <= limit
        if empty and start is None:
            start = index
        elif not empty and start is not None:
            g0, g1 = start / bins, index / bins
            start = None
            if g1 - g0 < min_width or not (lo <= (g0 + g1) / 2 <= hi):
                continue
            left = [box for box in narrow if box[0] + box[2] <= g0 + 0.004]
            right = [box for box in narrow if box[0] >= g1 - 0.004]
            if len(left) >= min_side and len(right) >= min_side:
                gutters.append((g0, g1))
    return gutters


def is_multicolumn(boxes: Sequence[Box]) -> bool:
    return bool(find_gutters(boxes))


def order_by_zones(items: Sequence, box: Callable = box_of) -> list:
    """Ordem de leitura: faixa de largura total, depois cada coluna de cima para baixo.

    Um bloco que cruza a calha (título, figura larga) fecha a faixa anterior e abre outra.
    """
    items = list(items)
    if len(items) < 2:
        return items

    def top_left(item):
        b = box(item)
        return (round(b[1], 3), b[0])

    gutters = find_gutters([box(item) for item in items])
    if not gutters:
        return sorted(items, key=top_left)
    centers = [(g0 + g1) / 2 for g0, g1 in gutters]
    columns = len(centers) + 1
    buckets: list[list] = [[] for _ in range(columns)]
    ordered: list = []

    def flush() -> None:
        for column in buckets:
            column.sort(key=top_left)
            ordered.extend(column)
            column.clear()

    for item in sorted(items, key=top_left):
        x, _y, w, _h = box(item)
        right = x + w
        # Cruza a calha se passa pelo meio dela. Uma linha que só invade a borda não é largura total.
        spans = any(x < (g0 + g1) / 2 < right for g0, g1 in gutters)
        if spans:
            flush()
            ordered.append(item)
            continue
        center = x + w / 2
        index = sum(1 for edge in centers if center > edge)
        buckets[index].append(item)
    flush()
    return ordered


# ---------------------------------------------------------------------------
# Hífen de fim de linha
# ---------------------------------------------------------------------------

_END_HYPHEN = re.compile(r"([A-Za-zÀ-ÿ]{1,})[-\u2010\u2011]$")


def join_lines(previous: str, following: str) -> str:
    """Junta duas linhas de um mesmo parágrafo, tratando o hífen de quebra."""
    previous = previous.rstrip()
    following = following.lstrip()
    if not previous:
        return following
    if not following:
        return previous
    match = _END_HYPHEN.search(previous)
    if match:
        left = match.group(1).lower()
        if following[:1].islower():
            if left in COMPOUND_PREFIXES:
                return previous + following  # "non-" + "specific" = "non-specific"
            return previous[:-1] + following  # "clean-" + "ing" = "cleaning"
        return previous + following  # "ISO-" + "10993": mantém o hífen
    return f"{previous} {following}"


# ---------------------------------------------------------------------------
# Parágrafos
# ---------------------------------------------------------------------------


def _ends_closed(text: str) -> bool:
    stripped = text.rstrip()
    return bool(stripped) and stripped.endswith(_TERMINAL)


def looks_like_heading_line(text: str) -> bool:
    """Linha curta sem ponto final que parece título: 'Scope', 'INTRODUCTION', '1.2 Exclusions'."""
    stripped = text.strip()
    if not stripped or len(stripped) > 90:
        return False
    if stripped.endswith((".", ",", ";", "-", "\u2010")):
        return False
    words = stripped.split()
    if len(words) > 10:
        return False
    if not (stripped[0].isalnum() and (stripped[0].isupper() or stripped[0].isdigit())):
        return False
    letters = [word for word in words if word[:1].isalpha()]
    if not letters:
        return True
    if stripped.isupper():
        return True
    capitalised = sum(1 for word in letters if word[0].isupper() or len(word) <= 3)
    return capitalised / len(letters) >= 0.6


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = min(max(int(round((len(ordered) - 1) * fraction)), 0), len(ordered) - 1)
    return ordered[index]


def _window(lines: list[Block], index: int, size: int = 6) -> list[Block]:
    return lines[max(0, index - size) : index + size + 1]


def _centre(block: Block) -> float:
    return block.bbox[1] + block.bbox[3] / 2


def _local_edges(lines: list[Block], index: int) -> tuple[float, float]:
    """Margem esquerda e direita locais. O quinto percentil ignora a linha recuada do parágrafo."""
    near = [line for line in _window(lines, index) if abs(line.bbox[0] - lines[index].bbox[0]) < 0.45]
    if not near:
        near = [lines[index]]
    left = _percentile([line.bbox[0] for line in near], 0.2)
    right = _percentile([line.bbox[0] + line.bbox[2] for line in near], 0.8)
    return left, right


def _typical_pitch(lines: list[Block], index: int) -> float:
    pitches = []
    near = _window(lines, index, 8)
    for first, second in zip(near, near[1:]):
        step = _centre(second) - _centre(first)
        same_column = abs(first.bbox[0] - second.bbox[0]) < 0.12
        if same_column and step > 0:
            pitches.append(step)
    if not pitches:
        return max(lines[index].bbox[3] * 1.4, 0.008)
    return statistics.median(pitches)


def starts_new_paragraph(lines: list[Block], index: int) -> bool:
    """Decide se lines[index] abre um parágrafo novo em relação a lines[index - 1]."""
    if index <= 0:
        return True
    previous, current = lines[index - 1], lines[index]
    left, right = _local_edges(lines, index)
    width = max(right - left, 0.05)
    near_heights = [line.bbox[3] for line in _window(lines, index, 8) if line.bbox[3] > 0]
    scale = max(1.0, min(current.bbox[3], previous.bbox[3]) / statistics.median(near_heights)) if near_heights else 1.0
    pitch = min(_typical_pitch(lines, index) * scale, max(current.bbox[3], previous.bbox[3]) * 1.75)
    step = _centre(current) - _centre(previous)

    # Outra coluna ou salto para trás: quem junta é a continuidade entre colunas, não este passo.
    if abs(current.bbox[0] - previous.bbox[0]) > 0.2 or step < 0:
        return True
    if step > pitch * 1.42:
        return True

    # Salto de tamanho de fonte. Altura de tinta do OCR varia até 30% entre uma linha com letras
    # altas e descendentes e outra sem elas, e uma linha de uma palavra ("use.") só tem altura-x.
    # Por isso, no OCR só se compara linha com 3 palavras ou mais e a tolerância é maior.
    prev_size = previous.font_size or previous.bbox[3]
    size = current.font_size or current.bbox[3]
    tolerance = 0.40 if current.source == "ocr" else 0.25
    comparable = len(previous.words) >= 3 and len(current.words) >= 3 if current.source == "ocr" else True
    if comparable and prev_size > 0 and abs(size - prev_size) / prev_size > tolerance:
        return True

    prev_short = (previous.bbox[0] + previous.bbox[2]) < right - width * 0.10
    closed = _ends_closed(previous.text) or prev_short

    if CLAUSE_START.match(current.text) and closed:
        return True

    indent = current.bbox[0] - left
    if indent > 0.011 and closed and (indent > 0.016 or CLAUSE_START.match(current.text)):
        return True

    # Título curto sem pontuação seguido de texto que começa em maiúscula: 'INTRODUCTION' + 'Each ...'
    if (
        prev_short
        and looks_like_heading_line(previous.text)
        and not _DANGLING.search(previous.text)
        and current.text[:1].isupper()
    ):
        return True
    return False


def _merge_lines(group: list[Block]) -> Block:
    text = group[0].text
    words: list[WordBox] = list(group[0].words)
    for line in group[1:]:
        text = join_lines(text, line.text)
        words.extend(line.words)
    x = min(line.bbox[0] for line in group)
    y = min(line.bbox[1] for line in group)
    right = max(line.bbox[0] + line.bbox[2] for line in group)
    bottom = max(line.bbox[1] + line.bbox[3] for line in group)
    weights = [max(len(line.text), 1) for line in group]
    confidence = sum(line.confidence * weight for line, weight in zip(group, weights)) / sum(weights)
    sizes = [line.font_size for line in group if line.font_size]
    return Block(
        text=text,
        bbox=(x, y, right - x, bottom - y),
        confidence=round(confidence, 2),
        source=group[0].source,
        font_size=statistics.median(sizes) if sizes else group[0].font_size,
        words=words,
    )


def lines_to_paragraphs(
    lines: Sequence[Block],
    *,
    keep_apart: Callable[[Block, Block], bool] | None = None,
) -> list[Block]:
    """Agrupa linhas, já na ordem de leitura, em parágrafos.

    `keep_apart(anterior, atual)` devolve True para impedir a junção (fórmula, por exemplo).
    """
    lines = [line for line in lines if line.text.strip()]
    if not lines:
        return []
    groups: list[list[Block]] = [[lines[0]]]
    for index in range(1, len(lines)):
        apart = keep_apart(lines[index - 1], lines[index]) if keep_apart else False
        if apart or starts_new_paragraph(lines, index):
            groups.append([lines[index]])
        else:
            groups[-1].append(lines[index])
    return [_merge_lines(group) for group in groups]


# ---------------------------------------------------------------------------
# Linhas a partir de palavras
# ---------------------------------------------------------------------------


def robust_height(words: Sequence[WordBox]) -> float:
    """Altura de tinta da linha. O percentil 75 ignora palavras sem ascendente e o ruído de um box."""
    heights = [word.bbox[3] for word in words if sum(ch.isalnum() for ch in word.text) >= 2 and word.bbox[3] > 0]
    if not heights:
        heights = [word.bbox[3] for word in words if word.bbox[3] > 0]
    if not heights:
        return 0.0
    return _percentile(heights, 0.75)


def split_words_at_gutters(words: Sequence[WordBox], *, min_gap: float = 0.022, factor: float = 4.5) -> list[list[WordBox]]:
    """Parte uma linha do OCR quando há um vão largo no meio, como a calha entre colunas."""
    ordered = sorted(words, key=lambda word: word.bbox[0])
    if len(ordered) < 2:
        return [list(ordered)] if ordered else []
    gaps = [
        right.bbox[0] - (left.bbox[0] + left.bbox[2])
        for left, right in zip(ordered, ordered[1:])
    ]
    positive = [gap for gap in gaps if gap > 0]
    typical = statistics.median(positive) if positive else 0.0
    threshold = max(min_gap, typical * factor)
    segments: list[list[WordBox]] = [[ordered[0]]]
    for gap, word in zip(gaps, ordered[1:]):
        if gap >= threshold:
            segments.append([word])
        else:
            segments[-1].append(word)
    return segments


def line_block(words: Sequence[WordBox], *, source: str = "ocr") -> Block | None:
    words = [word for word in words if word.text.strip()]
    if not words:
        return None
    x = min(word.bbox[0] for word in words)
    y = min(word.bbox[1] for word in words)
    right = max(word.bbox[0] + word.bbox[2] for word in words)
    bottom = max(word.bbox[1] + word.bbox[3] for word in words)
    confidence = sum(word.confidence for word in words) / len(words)
    return Block(
        text=" ".join(word.text for word in words),
        bbox=(x, y, right - x, bottom - y),
        confidence=round(confidence, 2),
        source=source,
        font_size=robust_height(words),
        words=list(words),
    )
