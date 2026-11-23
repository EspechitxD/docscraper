"""Diagnóstico de documentos em visualizadores web. Fixtures locais: nenhum site externo é acessado.

Estes testes provam a lógica de interpretação. Eles NÃO provam funcionamento em sites reais.
"""

from __future__ import annotations

import json
from pathlib import Path

from cpmh_backend.services.browser_inspector import INSPECT_JS, observe_page
from cpmh_backend.services.document_recovery import diagnose_observation, diagnose_url
from cpmh_backend.services.document_source_analyzer import analyze_source, reported_pages_from_text, split_interface_text
from cpmh_backend.services.document_statistics import count_words, page_statistics
from cpmh_backend.services.document_validator import validate_extraction

from test_pipeline import _project, _run_file
from scan_fixtures import build_two_column_scan

PROSE = "\n".join(
    f"Este parágrafo número {i} descreve com calma como o processo de limpeza deve ser validado antes do uso."
    for i in range(10)
)
PAGE = {"w": 800, "h": 1100}


def obs(**kw):
    base = {"url": "https://exemplo.test/doc", "final_url": "https://exemplo.test/doc", "status": 200, "visible_text": "", "responses": []}
    base.update(kw)
    return base


def test_html_with_document_text():
    report = analyze_source(obs(visible_text=PROSE))
    assert report["primary_state"] == "html_document" and report["strategy"]["code"] == "A"
    assert report["text"]["document_chars"] > 400


def test_direct_pdf_by_network_response():
    report = analyze_source(obs(responses=[{"url": "https://cdn.test/a.pdf", "status": 200, "content_type": "application/pdf"}]))
    assert report["primary_state"] == "pdf_document" and report["strategy"]["code"] == "B"
    assert report["resources"]["pdf_accessible"] == ["https://cdn.test/a.pdf"]


def test_pdf_in_iframe_is_linked_but_not_called_accessible_until_it_loads():
    report = analyze_source(obs(iframes=[{"src": "https://cdn.test/a.pdf", **PAGE}], visible_text="x"))
    assert report["resources"]["pdf_accessible"] == []
    assert report["resources"]["pdf_linked_not_verified"] == ["https://cdn.test/a.pdf"]
    assert report["primary_state"] != "pdf_document"


def test_pdfjs_viewer_with_and_without_text_layer():
    with_layer = analyze_source(obs(scripts=["https://x.test/pdf.worker.js"], text_layer_chars=900))
    assert with_layer["primary_state"] == "pdf_viewer_detected" and "camada de texto" in with_layer["strategy"]["name"]
    bare = analyze_source(obs(has_pdfjs_global=True))
    assert bare["primary_state"] == "pdf_viewer_detected" and "autorizada" in bare["strategy"]["action"]


def test_page_images_need_ocr_and_canvas_needs_a_legitimate_export():
    images = [{"src": f"https://cdn.test/p{i}.png", "w": 800, "h": 1100, "nw": 1600, "nh": 2200, "top": i * 1200} for i in range(3)]
    report = analyze_source(obs(images=images))
    assert report["primary_state"] == "image_document" and "ocr_required" in report["states"]
    assert report["pages"]["accessible"] == 3 and report["pages"]["processed"] == 0

    canvases = [dict(PAGE), dict(PAGE)]
    no_export = analyze_source(obs(canvases=canvases, controls=["Zoom", "Próxima"]))
    assert no_export["primary_state"] == "canvas_document" and "sem exportação" in no_export["strategy"]["name"]
    with_export = analyze_source(obs(canvases=canvases, controls=["Imprimir"]))
    assert with_export["resources"]["export_control_seen"] and "sua autorização" in with_export["strategy"]["action"]


def test_lazy_images_with_zero_natural_size_are_not_counted_as_pages():
    images = [{"src": "x", "w": 800, "h": 1100, "nw": 0, "nh": 0, "top": i * 1200} for i in range(3)]
    assert analyze_source(obs(images=images))["primary_state"] == "interface_only"


def test_captcha_and_login_pause_for_the_user_and_never_resolve():
    captcha = analyze_source(obs(html_head='<div class="g-recaptcha"></div><iframe src="https://www.google.com/recaptcha/api2/anchor"></iframe>', visible_text="Verifique que você é humano"))
    assert captcha["primary_state"] == "captcha_required" and captcha["strategy"]["code"] == "F"
    assert "você mesmo" in captcha["strategy"]["action"]
    login = analyze_source(obs(visible_text="请先登录后查看全文"))
    assert login["primary_state"] == "authentication_required" and login["strategy"]["code"] == "F"


def test_interface_only_page_is_still_interface_only_when_nothing_else_exists():
    report = analyze_source(obs(visible_text="\n".join(["首页", "文档", "帮助中心", "关于我们", "下载", "搜索", "设置", "全屏"])))
    assert report["primary_state"] == "interface_only" and not report["conclusive"]
    assert report["text"]["document_chars"] == 0 and report["text"]["interface_chars_discarded"] > 0


def test_partial_document_keeps_site_metadata_apart_from_processed_pages():
    images = [{"src": f"p{i}", "w": 800, "h": 1100, "nw": 1600, "nh": 2200, "top": i * 1200} for i in range(3)]
    report = analyze_source(obs(images=images, visible_text="页数:16\n下载本文需要使用 4000 积分\n全文阅读已结束"))
    assert report["pages"] == {"reported_by_site": 16, "accessible": 3, "processed": 0, "with_text": 0, "without_text": 0}
    assert "partial_document" in report["states"] and "access_restricted" in report["states"]
    assert "pagamento" not in report["strategy"]["action"] or "qualquer visitante" in report["strategy"]["action"]


def test_doc88_page_text_is_diagnosed_as_restricted_with_nothing_recovered():
    html = (Path(__file__).parent / "fixtures_doc88_interface.html").read_text(encoding="utf8")
    import re

    text = "\n".join(re.sub(r"<[^>]+>", "\n", html).split("\n"))
    report = analyze_source(obs(url="https://www.doc88.com/p-20454998901780.html", visible_text=text))
    assert report["primary_state"] == "access_restricted"
    assert report["pages"]["reported_by_site"] == 16
    assert report["pages"]["processed"] == 0 and report["text"]["document_chars"] == 0
    assert "payment" in report["restrictions"]
    assert report["strategy"]["code"] == "F"


def test_reported_pages_come_from_several_site_formats():
    assert reported_pages_from_text("格式:PDF 页数:16 上传日期") == 16
    assert reported_pages_from_text("Pages: 24") == 24
    assert reported_pages_from_text("1 / 1 ... 3 / 16") == 16
    assert reported_pages_from_text("sem número") is None


def test_split_interface_text_separates_document_from_menu():
    document, interface = split_interface_text(["下载", PROSE.splitlines()[0], "首页"])
    assert len(document) == 1 and len(interface) == 2


def test_statistics_do_not_invent_word_counts_for_chinese():
    assert count_words("The residue shall be measured twice.") == 6
    assert count_words("本文档描述了清洁过程的验证方法并说明了要求") is None
    stats = page_statistics([{"sequence": 1, "text": "本文档描述了清洁过程的验证方法并说明了要求"}, {"sequence": 2, "text": ""}])
    assert stats["words"] is None and stats["pages_without_text"] == 1 and stats["chars_with_spaces"] == 21


def test_validator_grades_the_extraction_and_never_counts_site_metadata():
    good = [{"sequence": i, "text": f"Página {i}. " + PROSE.replace("parágrafo", f"trecho{i}x"), "confidence": 92, "reported_number": str(i)} for i in range(1, 5)]
    assert validate_extraction(good, reported_pages=4)["quality"] == "Excelente"
    partial = validate_extraction(good, reported_pages=16)
    assert partial["quality"] == "Parcial" and partial["pages"]["processed"] == 4 and partial["pages"]["reported_by_site"] == 16
    empty_pages = good[:2] + [{"sequence": 3, "text": ""}, {"sequence": 4, "text": ""}]
    assert validate_extraction(empty_pages, reported_pages=4)["quality"] == "Parcial"
    assert validate_extraction([], reported_pages=16)["quality"] == "Insuficiente"
    menu = [{"sequence": 1, "text": "\n".join(["首页", "文档", "帮助中心", "关于我们", "下载", "搜索", "设置", "全屏"])}]
    verdict = validate_extraction(menu, reported_pages=16)
    assert verdict["quality"] == "Insuficiente" and not verdict["safe_to_export"]
    assert any(item["code"] == "interface_text" for item in verdict["issues"])


def test_validator_flags_repetition_numbering_gaps_and_broken_tables():
    pages = [{"sequence": i, "text": PROSE.splitlines()[i] + "\nCabeçalho repetido em todas as páginas do arquivo", "reported_number": str(n), "confidence": 90} for i, n in enumerate([1, 2, 5, 6])]
    codes = {item["code"] for item in validate_extraction(pages, tables=[[["a", "b"], ["c"]]])["issues"]}
    assert {"continuity", "table_integrity"} <= codes


class _FakePage:
    url = "https://exemplo.test/final"

    def __init__(self, payload):
        self.payload = payload

    def evaluate(self, script):
        assert script == INSPECT_JS
        return json.dumps(self.payload)

    def content(self):
        return "<html><title>x</title></html>"


def test_observe_page_builds_the_observation_without_a_real_browser():
    payload = {"title": "Doc", "visible_text": "页数:16", "iframes": [], "canvases": [], "images": [], "meta_pages": "16", "scripts": [], "controls": []}
    observation = observe_page(_FakePage(payload), url="https://exemplo.test", responses=[], network_errors=[], console_errors=[], status=200)
    assert observation["reported_pages"] == 16 and observation["final_url"].endswith("/final")
    assert diagnose_observation(observation)["pages"]["reported_by_site"] == 16


def test_diagnose_url_without_chrome_reports_failure_instead_of_inventing_a_result(monkeypatch):
    from cpmh_backend.services import browser_inspector

    monkeypatch.setattr(browser_inspector, "validate_url", lambda url: None)
    monkeypatch.setattr(browser_inspector, "browser_status", lambda: {"playwright": True, "chrome": False, "chrome_path": ""})
    report = diagnose_url("https://www.doc88.com/p-20454998901780.html")
    assert report["primary_state"] == "processing_failed" and "simulado" in report["error"]
    assert report.get("pages") is None


def test_diagnose_url_reports_a_rejected_address_instead_of_crashing():
    report = diagnose_url("http://127.0.0.1/doc")
    assert report["primary_state"] == "processing_failed" and report["error"]


def test_document_report_endpoint_counts_what_was_really_extracted(client, tmp_path):
    path = tmp_path / "norma.pdf"
    build_two_column_scan(path)
    project_id = _project(client)
    document = _run_file(client, project_id, path)
    report = client.get(f"/api/documents/{document['id']}/report").json()
    assert report["pages"]["processed"] == 1 and report["pages"]["with_text"] == 1
    assert report["statistics"]["chars_with_spaces"] > 500
    assert report["statistics"]["interface_chars_discarded"] == 0
    assert report["quality"] in {"Excelente", "Boa", "Parcial"}
    assert report["statistics"]["words"] and report["statistics"]["per_page"][0]["method"] == "ocr"


def test_browser_is_found_in_the_windows_install_folders_not_only_on_path(tmp_path, monkeypatch):
    """No Windows o Chrome é chrome.exe em Program Files e não está no PATH."""
    from cpmh_backend.services import capture

    chrome = tmp_path / "pf" / "Google" / "Chrome" / "Application" / "chrome.exe"
    chrome.parent.mkdir(parents=True)
    chrome.write_bytes(b"")
    monkeypatch.setattr(capture.shutil, "which", lambda name: None)
    monkeypatch.delenv("CPMH_CHROME_PATH", raising=False)
    for name in ("PROGRAMFILES(X86)", "LOCALAPPDATA"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("PROGRAMFILES", str(tmp_path / "pf"))
    path, label = capture.find_browser()
    assert path == str(chrome) and label == "Google Chrome"
    assert capture.browser_status()["chrome"] is True


def test_edge_is_used_when_chrome_is_missing_and_the_override_wins(tmp_path, monkeypatch):
    from cpmh_backend.services import capture

    edge = tmp_path / "pfx86" / "Microsoft" / "Edge" / "Application" / "msedge.exe"
    edge.parent.mkdir(parents=True)
    edge.write_bytes(b"")
    monkeypatch.setattr(capture.shutil, "which", lambda name: None)
    monkeypatch.delenv("CPMH_CHROME_PATH", raising=False)
    monkeypatch.delenv("PROGRAMFILES", raising=False)
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.setenv("PROGRAMFILES(X86)", str(tmp_path / "pfx86"))
    assert capture.find_browser() == (str(edge), "Microsoft Edge")
    custom = tmp_path / "meu-navegador.exe"
    custom.write_bytes(b"")
    monkeypatch.setenv("CPMH_CHROME_PATH", str(custom))
    assert capture.find_browser()[0] == str(custom)


def test_missing_browser_message_names_what_is_missing(monkeypatch):
    from cpmh_backend.services.capture import browser_unavailable_reason

    assert "pip install" in browser_unavailable_reason({"playwright": False, "chrome": True})
    assert "Edge" in browser_unavailable_reason({"playwright": True, "chrome": False})
    assert browser_unavailable_reason({"playwright": True, "chrome": True}) == ""


def test_tesseract_is_found_in_the_windows_install_folder_and_by_override(tmp_path, monkeypatch):
    from cpmh_backend.services import ocr

    exe = tmp_path / "pf" / "Tesseract-OCR" / "tesseract.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"")
    monkeypatch.setattr(ocr.shutil, "which", lambda name: None)
    for name in ("CPMH_TESSERACT_PATH", "TESSERACT_CMD", "PROGRAMFILES(X86)", "LOCALAPPDATA", "PROGRAMW6432"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("PROGRAMFILES", str(tmp_path / "pf"))
    assert ocr.find_tesseract() == str(exe)
    custom = tmp_path / "meu" / "tesseract.exe"
    custom.parent.mkdir()
    custom.write_bytes(b"")
    monkeypatch.setenv("CPMH_TESSERACT_PATH", str(custom))
    assert ocr.find_tesseract() == str(custom)


def test_missing_tesseract_raises_a_friendly_error_with_the_install_command(monkeypatch):
    import pytest
    from PIL import Image

    from cpmh_backend.errors import OcrUnavailable
    from cpmh_backend.services import ocr

    monkeypatch.setattr(ocr, "find_tesseract", lambda: "")
    with pytest.raises(OcrUnavailable) as caught:
        ocr.recognize(Image.new("RGB", (100, 100), "white"), ["eng"])
    assert "winget install" in caught.value.message and caught.value.code == "ocr_unavailable"
    status = ocr.tesseract_status()
    assert status["installed"] is False and "winget" in status["hint"]


def test_chinese_slider_verification_pauses_the_capture_and_is_never_solved():
    """A tela real do DOC88: 请完成滑动验证后阅读文档 / 请拖动滑块继续阅读."""
    from cpmh_backend.access import classify

    verdict = classify({"url": "https://www.doc88.com/p-1.html", "final_url": "https://www.doc88.com/p-1.html", "status": 200,
                        "text": "请完成滑动验证后阅读文档\n请拖动滑块继续阅读", "rendered": True})
    assert verdict["state"] == "CAPTCHA_DETECTED" and verdict["provider"] == "slider"
    assert "não resolve" in verdict["message"]
    for phrase in ("slide to verify", "Arraste o controle deslizante para continuar", "请先完成安全验证"):
        assert classify({"url": "u", "text": phrase})["state"] == "CAPTCHA_DETECTED", phrase
    report = analyze_source(obs(visible_text="请完成滑动验证后阅读文档\n请拖动滑块继续阅读"))
    assert report["primary_state"] == "captcha_required" and "você mesmo" in report["strategy"]["action"]


def test_a_long_document_that_mentions_verification_is_not_a_captcha():
    from cpmh_backend.access import classify

    long_text = ("O procedimento de verificação de segurança do equipamento deve ser registrado. " * 40)
    assert classify({"url": "u", "text": long_text})["state"] == "ACCESS_GRANTED"
