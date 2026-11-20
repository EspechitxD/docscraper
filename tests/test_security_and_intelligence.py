import pytest

from cpmh_backend.errors import UrlRejected
from cpmh_backend.hashing import clamp_bbox, dhash, hamming
from cpmh_backend.intelligence import (
    Block,
    FlowPiece,
    PageObservation,
    WordBox,
    assess_formula,
    confidence_band,
    decide_capture,
    detect_language,
    detect_text_table,
    link_page_continuity,
    reading_order,
)
from cpmh_backend.security import validate_url
from cpmh_backend.services.translate import apply_glossary
from cpmh_backend.models import GlossaryTerm
from PIL import Image


def _resolver(mapping):
    def resolve(host):
        if host not in mapping:
            raise UrlRejected(f"sem DNS para {host}")
        return mapping[host]
    return resolve


PUBLIC = {"example.com": ["93.184.216.34"]}


def test_rejects_private_and_obfuscated_targets():
    blocked = [
        "http://127.0.0.1/admin",
        "http://localhost/secret",
        "http://169.254.169.254/latest/meta-data",
        "http://10.1.2.3/a",
        "http://192.168.0.5/a",
        "http://172.16.0.1/a",
        "http://[::1]/",
        "http://2130706433/",
        "http://0177.0.0.1/",
        "file:///etc/passwd",
        "http://user:pass@example.com/a",
        "http://metadata.google.internal/",
    ]
    for url in blocked:
        with pytest.raises(UrlRejected):
            validate_url(url, allow_local=False, resolver=_resolver({"metadata.google.internal": ["169.254.169.254"], "example.com": ["93.184.216.34"]}))


def test_allows_public_url_and_strips_fragment():
    checked = validate_url("HTTPS://Example.COM/docs/manual/?b=2&a=1#secao", allow_local=False, resolver=_resolver(PUBLIC))
    assert checked.url == "https://example.com/docs/manual?b=2&a=1"
    assert checked.ips == ("93.184.216.34",)


def test_blocks_redirect_style_public_name_resolving_private():
    with pytest.raises(UrlRejected):
        validate_url("http://example.com/doc", allow_local=False, resolver=_resolver({"example.com": ["93.184.216.34", "127.0.0.1"]}))


def test_hash_and_bbox():
    image = Image.new("RGB", (32, 32), "white")
    image.putpixel((0, 0), (0, 0, 0))
    image.putpixel((10, 10), (255, 80, 0))
    first = dhash(image)
    second = dhash(image)
    assert first == second
    assert hamming(first, second) == 0
    assert clamp_bbox(-1, 0.2, 2, 0.3)[0] == 0
    assert confidence_band(90, 85, 60) == "high"
    assert confidence_band(70, 85, 60) == "medium"
    assert confidence_band(10, 85, 60) == "low"


def test_languages():
    assert detect_language("Este manual descreve a placa de ancoragem e o parafuso de fixação cirúrgica.") == "por"
    assert detect_language("This technical manual describes the surgical plate and the fixation screw in detail.") == "eng"
    assert detect_language("钛合金植入物的技术手册用于临床规划") == "chi_sim"
    assert detect_language("鈦合金植入物的技術手冊用於臨床規劃") == "chi_tra"


def test_reading_order_and_continuity():
    left = [
        Block("COLUNA_ESQUERDA_A", (0.08, 0.2, 0.3, 0.04)),
        Block("COLUNA_ESQUERDA_B", (0.08, 0.3, 0.3, 0.04)),
    ]
    right = [
        Block("COLUNA_DIREITA_A", (0.58, 0.2, 0.3, 0.04)),
        Block("COLUNA_DIREITA_B", (0.58, 0.3, 0.3, 0.04)),
    ]
    ordered = reading_order(left + right)
    texts = [item.text for item in ordered]
    assert texts.index("COLUNA_ESQUERDA_B") < texts.index("COLUNA_DIREITA_A")
    pieces = [
        FlowPiece("a", "paragraph", "O dispositivo foi", 1, (0.1, 0.8, 0.4, 0.04)),
        FlowPiece("b", "paragraph", "posicionado no leito.", 2, (0.1, 0.12, 0.4, 0.04)),
    ]
    link_page_continuity(pieces)
    assert pieces[1].skip is True
    assert "posicionado" in pieces[0].text


def test_capture_end_signals():
    first = PageObservation("h1", "0" * 64, counter_current=1, counter_total=2, next_present=True, next_disabled=False)
    assert decide_capture([first]) == "continue"
    done = PageObservation("h2", "1" * 64, counter_current=2, counter_total=2, next_present=True, next_disabled=True)
    assert decide_capture([first, done]) == "complete"
    stuck = PageObservation("h1", "0" * 64, next_present=True, next_disabled=False)
    assert decide_capture([first, stuck, stuck]) == "inconclusive"
    gap = PageObservation("h3", "1" * 64, counter_current=4, counter_total=5, next_present=True, next_disabled=False)
    assert decide_capture([first, gap]) == "inconclusive"
    single = PageObservation("only", "0" * 64, next_present=False)
    assert decide_capture([single]) == "complete"
    assert decide_capture([single], hit_max=True) == "complete"


def test_table_and_formula_and_glossary():
    words = []
    rows = [["Código", "Peça", "Medida"], ["A1", "Placa", "30"], ["B2", "Parafuso", "2,0"]]
    for row_index, row in enumerate(rows):
        for col_index, text in enumerate(row):
            words.append(WordBox(text, (0.1 + col_index * 0.25, 0.2 + row_index * 0.05, 0.12, 0.03), 99))
    table = detect_text_table(words, from_text_layer=True)
    assert table is not None
    assert table["rows"][0][0] == "Código"
    assert table["rows"][1][1] == "Placa"
    assert table["reliable"] is True
    reliable, _note = assess_formula("E = mc²")
    assert reliable is True
    complex_ok, note = assess_formula("∫ x² dx")
    assert complex_ok is False
    assert "revisão" in note
    terms = [
        GlossaryTerm(id="1", glossary_id="g", source="plate", target="placa", do_not_translate=False),
        GlossaryTerm(id="2", glossary_id="g", source="Ti6Al4V", target="", do_not_translate=True),
    ]
    translated, _holders = apply_glossary("The plate Ti6Al4V uses 2,0 mm.", terms)
    assert "placa" in translated
    assert "Ti6Al4V" in translated
    assert "2,0 mm" in translated
