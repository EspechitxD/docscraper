"""Regressões do benchmark SciELO: título, tabela, palavras partidas e legenda no texto."""

from types import SimpleNamespace

from cpmh_backend.intelligence import Block, WordBox, blocks_from_pdf_chars, classify_blocks, detect_text_table, mark_repeated_chrome
from cpmh_backend.services.exporting import _plain_text


def test_repeated_running_header_does_not_demote_the_title():
    title = "Avaliação externa de escolas e sua relação com políticas e práticas inclusivas"
    first = [
        Block(title, bbox=(0.14, 0.10, 0.74, 0.14), font_size=0.024, source="pdf_text"),
        Block("Este estudo pretende analisar o impacto da avaliação externa nas escolas públicas.", bbox=(0.14, 0.40, 0.7, 0.2), font_size=0.015, source="pdf_text"),
    ]
    later = [
        Block(title, bbox=(0.14, 0.04, 0.66, 0.024), font_size=0.011, source="pdf_text"),
        Block("A discussão seguinte retoma os estudos incluídos na revisão.", bbox=(0.14, 0.2, 0.7, 0.2), font_size=0.015, source="pdf_text"),
    ]
    pages = [classify_blocks(first), classify_blocks(later), classify_blocks(later)]
    mark_repeated_chrome(pages)
    assert pages[0][0].category == "title"
    assert pages[1][0].category == "header"


def test_distant_gaps_do_not_swallow_the_page():
    words = []
    words.append(WordBox("Introdução", (0.12, 0.12, 0.2, 0.02), 99))
    words.append(WordBox("seguinte", (0.40, 0.12, 0.15, 0.02), 99))
    for index, text in enumerate(["O", "texto", "desta", "página", "permanece", "corrido."]):
        words.append(WordBox(text, (0.12 + index * 0.08, 0.3, 0.07, 0.02), 99))
    words.append(WordBox("fim", (0.12, 0.7, 0.08, 0.02), 99))
    words.append(WordBox("isolado", (0.45, 0.7, 0.12, 0.02), 99))
    assert detect_text_table(words, from_text_layer=True) is None


def test_superscript_marker_does_not_split_the_word():
    chars = []
    x = 58.0
    chars.append({"ch": "a", "x0": x, "y0": 129.1, "x1": x + 1.6, "y1": 131.2})
    x = 65.8
    for char, width in (("U", 3.6), ("n", 2.9), ("i", 0.8), ("v", 3.3), ("e", 3.0), ("r", 1.8), ("s", 2.3), ("i", 0.8), ("d", 3.2), ("a", 2.8), ("d", 3.2), ("e", 3.0)):
        chars.append({"ch": char, "x0": x, "y0": 126.8, "x1": x + width, "y1": 131.0})
        x += width + 0.6
    blocks = blocks_from_pdf_chars(chars, 425.2, 637.8)
    joined = " ".join(block.text for block in blocks)
    assert "Universidade" in joined
    assert "Uni versidade" not in joined


def test_plain_text_includes_a_changed_image_caption():
    element = SimpleNamespace(skip_export=False, kind="paragraph", id="1", text="Resumo do estudo.")
    image = SimpleNamespace(caption="Fluxograma PRISMA conferido na revisão")
    text = _plain_text([element], [], "editable", "none", images=[image])
    assert "Fluxograma PRISMA conferido na revisão" in text
    again = _plain_text([element, SimpleNamespace(skip_export=False, kind="caption", id="2", text=image.caption)], [], "editable", "none", images=[image])
    assert again.count("Fluxograma PRISMA conferido na revisão") == 1
    table = SimpleNamespace(rows=[["Artigo", "Autores"], ["A01", "Brauckmann"]])
    with_table = _plain_text([element], [], "editable", "none", tables=[table])
    assert "Artigo | Autores" in with_table
    assert "A01 | Brauckmann" in with_table
