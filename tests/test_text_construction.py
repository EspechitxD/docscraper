"""Como o texto é construído: parágrafos, colunas, títulos, tabelas falsas e exportação."""

from __future__ import annotations

import re
import zipfile

import pytest
from docx import Document as WordDocument

from cpmh_backend.intelligence import (
    Block,
    FlowPiece,
    WordBox,
    classify_blocks,
    clean_heading_text,
    heading_depth,
    is_noise_block,
    link_page_continuity,
    looks_like_fragment,
    reading_order,
)
from cpmh_backend.layout import find_gutters, join_lines, lines_to_paragraphs, order_by_zones
from cpmh_backend.services.ocr import dehyphenate_text
from cpmh_backend.services.ocr_repair import identifier_counts, repair_identifiers

from test_pipeline import _project, _run_file
from scan_fixtures import build_two_column_scan


def _line(text, x, y, w=0.38, h=0.011, source="pdf_text"):
    words = [WordBox(piece, (x, y, 0.02, h)) for piece in text.split()]
    return Block(text=text, bbox=(x, y, w, h), font_size=h, source=source, words=words)


def test_numbered_clauses_and_headings_are_not_glued_together():
    lines = [
        _line("1. Scope", 0.1, 0.20, w=0.08),
        _line("1.1 This guide provides considerations for", 0.12, 0.22),
        _line("validating inspection processes.", 0.1, 0.235),
        _line("1.2 Exclusions", 0.12, 0.26, w=0.12),
        _line("1.2.1 This guide does not describe reuse.", 0.12, 0.28),
    ]
    texts = [b.text for b in lines_to_paragraphs(lines)]
    assert texts == [
        "1. Scope",
        "1.1 This guide provides considerations for validating inspection processes.",
        "1.2 Exclusions",
        "1.2.1 This guide does not describe reuse.",
    ]


def test_wrapped_line_with_a_number_inside_the_sentence_is_not_split():
    lines = [
        _line("The residue shall be measured according to", 0.1, 0.20),
        _line("7.3.5 of the referenced method and reported.", 0.1, 0.215),
    ]
    assert len(lines_to_paragraphs(lines)) == 1


def test_two_columns_are_read_column_by_column_with_a_full_width_title():
    title = Block("TITULO LARGO", (0.1, 0.08, 0.8, 0.03), font_size=0.03)
    left = [Block(f"E{i}", (0.09, 0.2 + i * 0.05, 0.38, 0.04)) for i in range(3)]
    right = [Block(f"D{i}", (0.53, 0.2 + i * 0.05, 0.38, 0.04)) for i in range(3)]
    ordered = [b.text for b in order_by_zones([*right, title, *left], lambda b: b.bbox)]
    assert ordered == ["TITULO LARGO", "E0", "E1", "E2", "D0", "D1", "D2"]
    assert find_gutters([b.bbox for b in left + right])


def test_overflowing_indented_line_does_not_make_the_column_span_the_page():
    left = [Block(f"E{i}", (0.09, 0.2 + i * 0.05, 0.40 if i == 0 else 0.38, 0.04)) for i in range(4)]
    right = [Block(f"D{i}", (0.53, 0.2 + i * 0.05, 0.38, 0.04)) for i in range(4)]
    ordered = [b.text for b in reading_order(left + right)]
    assert ordered == ["E0", "E1", "E2", "E3", "D0", "D1", "D2", "D3"]


def test_first_line_of_a_clause_cut_by_the_column_break_is_not_a_heading():
    from cpmh_backend.intelligence import demote_open_headings

    first = Block("5.1 This guide describes an approach to validate", (0.1, 0.9, 0.38, 0.01), category="subtitle")
    rest = Block("a system for a medical device.", (0.53, 0.17, 0.38, 0.01), category="paragraph")
    demote_open_headings([first, rest])
    assert first.category == "paragraph"
    real = Block("3.1 Definitions:", (0.1, 0.5, 0.2, 0.01), category="subtitle")
    demote_open_headings([real, rest])
    assert real.category == "subtitle"


def test_sentence_fragments_never_become_headings():
    fragments = [
        "ing processes for medical devices during initial fabrication and",
        "1.3.1.1 Validation of cleaning operations for reusable medi-",
        "ISO 14971 Medical Devices\u2014 Application of Risk Manage-",
        "scope of this guide, many of the principles outlined in thi",
    ]
    for text in fragments:
        assert looks_like_fragment(text), text
        block = Block(text, (0.1, 0.3, 0.4, 0.02), font_size=0.03, source="ocr", confidence=90)
        body = Block("x " * 80, (0.1, 0.5, 0.4, 0.02), font_size=0.01, source="ocr", confidence=90)
        classify_blocks([block, body])
        assert block.category == "paragraph", (text, block.category)


def test_real_numbered_headings_still_work_and_carry_their_depth():
    body = Block("texto " * 60, (0.1, 0.5, 0.4, 0.02), font_size=0.01)
    blocks = [Block("1. Scope", (0.1, 0.3, 0.1, 0.01)), Block("7.3.5.1 Process Qualification:", (0.1, 0.4, 0.3, 0.01)), body]
    classify_blocks(blocks)
    assert blocks[0].category == blocks[1].category == "subtitle"
    assert heading_depth("1. Scope") == 1 and heading_depth("7.3.5.1 Process") == 4 and heading_depth("Scope") == 0


def test_stray_exclamation_after_a_title_is_removed():
    assert clean_heading_text("Used During the Manufacture of Medical Devices!") == "Used During the Manufacture of Medical Devices"
    assert clean_heading_text("Wow! Really") == "Wow! Really"


def test_ocr_debris_is_noise_but_clean_text_is_not():
    assert is_noise_block("< \u4e00", 40, "ocr")
    assert is_noise_block("\u2018ate ronca nr e ss", 45, "ocr")
    assert not is_noise_block("The residue shall be measured.", 93, "ocr")
    assert not is_noise_block("\u2018ate ronca nr e ss", 45, "pdf_text")


def test_hyphen_rules_keep_real_compounds():
    assert join_lines("validated clean-", "ing processes") == "validated cleaning processes"
    assert join_lines("a non-", "specific method") == "a non-specific method"
    assert join_lines("see ISO-", "10993") == "see ISO-10993"
    assert dehyphenate_text("clean- ing and in- process") == "cleaning and in-process"


def test_paragraph_open_at_the_end_of_a_column_is_joined_to_the_next_column():
    pieces = [
        FlowPiece("a", "paragraph", "removal of contaminants introduced during", 1, (0.09, 0.85, 0.38, 0.03), order=4),
        FlowPiece("b", "paragraph", "intermediate steps so the process is clean.", 1, (0.53, 0.17, 0.38, 0.03), order=5),
    ]
    link_page_continuity(pieces)
    assert pieces[1].skip and "during intermediate steps" in pieces[0].text


def test_heading_between_two_paragraphs_blocks_the_join():
    pieces = [
        FlowPiece("a", "paragraph", "texto sem ponto final", 1, (0.09, 0.85, 0.38, 0.03), order=4),
        FlowPiece("b", "paragraph", "continua em minúscula.", 1, (0.53, 0.17, 0.38, 0.03), order=6),
    ]
    link_page_continuity(pieces)
    assert not pieces[1].skip


def test_identifier_repair_needs_a_clear_majority_and_never_changes_a_real_standard():
    counts = identifier_counts(["E3127 E3127 E3127", "F3127", "F2459 F2459", "F2457"])
    assert repair_identifiers("Designation: F3127", counts) == "Designation: E3127"
    assert repair_identifiers("see F2457", counts) == "see F2457"  # outra norma, não é erro de OCR
    assert repair_identifiers("practice GI22 applies", counts) == "practice G122 applies"
    tie = identifier_counts(["E3127", "F3127"])
    assert repair_identifiers("F3127", tie) == "F3127"


@pytest.fixture()
def scanned_two_columns(tmp_path):
    path = tmp_path / "norma_duas_colunas.pdf"
    build_two_column_scan(path)
    return path


def test_scanned_two_column_standard_end_to_end(client, tmp_path, scanned_two_columns):
    project_id = _project(client)
    document = _run_file(client, project_id, scanned_two_columns)
    elements = client.get(f"/api/documents/{document['id']}/elements").json()
    body = [e for e in elements if e["kind"] not in {"header", "footer", "page_number", "noise"} and not e.get("skip_export")]
    texts = [e["text"] for e in body]

    # 1. Cláusulas e seções ficam em blocos próprios.
    assert not any(re.search(r"1\.1 .*1\.2 Exclusions", t) for t in texts)
    for marker in ("1. Scope", "1.2 Exclusions", "2. Referenced Documents", "5. Significance and Use"):
        assert any(t.startswith(marker) for t in texts), (marker, texts)
    headings = [e["text"] for e in body if e["kind"] == "subtitle"]
    assert {"1. Scope", "3. Terminology", "6. General Requirements"} <= set(headings), headings

    # 2. Nenhum título falso no meio do corpo.
    assert all(e["kind"] != "title" or e["text"].startswith("Standard Guide") for e in body)

    # 3. Ordem de duas colunas: toda a coluna esquerda antes da direita.
    index = {key: next(i for i, t in enumerate(texts) if t.startswith(key)) for key in ("1.1", "4.1", "5.1", "6.1")}
    assert index["1.1"] < index["4.1"] < index["5.1"] < index["6.1"]

    # 4. Duas colunas de texto corrido não viram tabela.
    assert client.get(f"/api/documents/{document['id']}/tables").json() == []

    # 5. O parágrafo 4.1 continua no topo da coluna da direita e vira um só.
    joined = [t for t in texts if t.startswith("4.1")]
    assert joined and "intermediate process steps" in joined[0] and joined[0].rstrip().endswith("device.")

    # 6. Código de norma repetido não é "corrigido" para outra norma.
    assert sum(t.count("F2459") for t in texts) >= 1


def test_docx_export_keeps_reading_order_and_builds_a_real_toc(client, tmp_path, scanned_two_columns):
    project_id = _project(client)
    document = _run_file(client, project_id, scanned_two_columns)
    out = tmp_path / "saida"
    out.mkdir()
    response = client.post(
        f"/api/documents/{document['id']}/export",
        json={"formats": ["docx"], "mode": "editable", "output_name": "norma", "output_dir": str(out)},
    )
    assert response.status_code == 200, response.text
    path = next(out.glob("*.docx"))
    word = WordDocument(str(path))
    texts = [p.text for p in word.paragraphs]
    assert not any("Atualize o sumário" in t for t in texts)
    assert "Sumário" in texts
    styles = {p.text: p.style.name for p in word.paragraphs if p.text}
    assert styles["1. Scope"] == "Heading 1"
    assert styles["1.2 Exclusions"] == "Heading 2"
    first = next(i for i, t in enumerate(texts) if t.startswith("1.1 "))
    fifth = next(i for i, t in enumerate(texts) if t.startswith("5.1 "))
    fourth = next(i for i, t in enumerate(texts) if t.startswith("4.1 "))
    assert first < fourth < fifth
    with zipfile.ZipFile(path) as archive:
        xml = archive.read("word/document.xml").decode("utf8")
    assert 'TOC \\o "1-3"' in xml and "fldCharType=\"separate\"" in xml


# --- Captura de visualizador: interface do site não é o documento -------------------------------

_VIEWER_HTML = """<html><body>
<div>登录</div><div>注册</div><div>首页</div><div>下载</div><div>上传文档</div><div>搜本文档</div>
<div>帮助中心</div><div>关于我们</div><div>全屏</div><div>缩略图</div><div>1 / 1</div>
<p>道客巴巴网站 版权所有 | ©2008-2026</p>
</body></html>"""

_ARTICLE_HTML = "<html><body><h1>Guia de limpeza</h1>" + "".join(
    f"<p>Este parágrafo número {i} descreve com calma como o processo de limpeza deve ser validado antes do uso.</p>"
    for i in range(8)
) + "</body></html>"


def test_viewer_interface_text_is_not_turned_into_a_document(tmp_path):
    from cpmh_backend.services.capture import pages_from_downloaded_html

    result = pages_from_downloaded_html(_VIEWER_HTML, "https://example.com/viewer", tmp_path)
    assert result["status"] == "interface_only" and not result["pages"]


def test_a_real_article_still_goes_through_the_html_text_path(tmp_path):
    from cpmh_backend.services.capture import pages_from_downloaded_html

    result = pages_from_downloaded_html(_ARTICLE_HTML, "https://example.com/artigo", tmp_path)
    assert result["status"] == "complete" and result["pages"]


def test_search_box_counter_does_not_end_the_capture_at_page_one():
    from cpmh_backend.services.capture import pick_counter

    assert pick_counter([[1, 1], [3, 16]]) == [3, 16]
    assert pick_counter([[2, 1]]) == [None, None]  # contador impossível é ignorado
    assert pick_counter([]) == [None, None]


def test_stacked_page_images_are_recognised_but_icons_and_a_single_image_are_not():
    from cpmh_backend.services.capture import group_page_surfaces

    pages = [{"i": i, "w": 800, "h": 1100, "top": i * 1200} for i in range(4)]
    icon = {"i": 9, "w": 60, "h": 60, "top": 0}
    assert len(group_page_surfaces(pages + [icon])) == 4
    assert group_page_surfaces(pages[:1] + [icon]) == []
    banner = {"i": 8, "w": 1200, "h": 300, "top": 0}
    assert len(group_page_surfaces(pages + [banner])) == 4


def test_doc88_viewer_page_is_refused_as_interface_only(tmp_path):
    """Texto real da página https://www.doc88.com/p-20454998901780.html (só interface, 16 páginas)."""
    from pathlib import Path

    from cpmh_backend.services.capture import pages_from_downloaded_html

    html = (Path(__file__).parent / "fixtures_doc88_interface.html").read_text(encoding="utf8")
    result = pages_from_downloaded_html(html, "https://www.doc88.com/p-20454998901780.html", tmp_path)
    assert result["status"] == "interface_only" and result["pages"] == []
