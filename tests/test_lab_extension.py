import json
from pathlib import Path

from cpmh_backend.services import lab_extension
from cpmh_backend.services.lab_extension import (
    BUNDLED_EXTENSION,
    lab_enabled_for,
    prepare_runtime_extension,
)


def _ext(tmp_path: Path) -> Path:
    (tmp_path / "manifest.json").write_text("{}", encoding="utf-8")
    return tmp_path


def test_desligado_por_padrao(monkeypatch):
    monkeypatch.delenv("CPMH_LAB_MODE", raising=False)
    assert lab_enabled_for("http://localhost:8000/lab.html") is None


def test_ativo_so_em_loopback(monkeypatch, tmp_path):
    monkeypatch.setenv("CPMH_LAB_MODE", "1")
    monkeypatch.setenv("CPMH_LAB_EXTENSION_DIR", str(_ext(tmp_path)))
    assert lab_enabled_for("http://localhost:8000/lab.html") == tmp_path
    assert lab_enabled_for("http://127.0.0.1:8000/") == tmp_path
    assert lab_enabled_for("https://exemplo.com.br/doc") is None
    assert lab_enabled_for("https://localhost.evil.com/") is None


def test_exige_manifest(monkeypatch, tmp_path):
    monkeypatch.setenv("CPMH_LAB_MODE", "1")
    monkeypatch.setenv("CPMH_LAB_EXTENSION_DIR", str(tmp_path))
    assert lab_enabled_for("http://localhost/") is None


def test_pacote_embutido_e_o_padrao(monkeypatch):
    monkeypatch.setenv("CPMH_LAB_MODE", "1")
    monkeypatch.delenv("CPMH_LAB_EXTENSION_DIR", raising=False)
    assert (BUNDLED_EXTENSION / "manifest.json").is_file()
    assert lab_enabled_for("http://localhost:8000/lab.html") == BUNDLED_EXTENSION
    assert lab_enabled_for("https://exemplo.com.br/") is None


def test_pacote_embutido_tem_todos_os_arquivos_do_manifest():
    manifest = json.loads((BUNDLED_EXTENSION / "manifest.json").read_text(encoding="utf-8"))
    refs = [f for cs in manifest.get("content_scripts", []) for f in cs.get("js", [])]
    bg = manifest.get("background", {})
    refs += [bg["service_worker"]] if bg.get("service_worker") else []
    refs += list(manifest.get("icons", {}).values())
    assert refs
    for rel in refs:
        assert (BUNDLED_EXTENSION / rel.lstrip("/")).is_file(), rel


def test_chave_vai_so_para_a_copia(monkeypatch, tmp_path):
    monkeypatch.setenv("NOPECHA_KEY", "chave-de-teste")
    before = (BUNDLED_EXTENSION / "manifest.json").read_text(encoding="utf-8")
    runtime = prepare_runtime_extension(BUNDLED_EXTENSION, tmp_path)
    copied = json.loads((runtime / "manifest.json").read_text(encoding="utf-8"))
    assert copied["nopecha"]["key"] == "chave-de-teste"
    assert (BUNDLED_EXTENSION / "manifest.json").read_text(encoding="utf-8") == before
    assert "chave-de-teste" not in before


def test_sem_chave_copia_identica(monkeypatch, tmp_path):
    monkeypatch.delenv("NOPECHA_KEY", raising=False)
    runtime = prepare_runtime_extension(BUNDLED_EXTENSION, tmp_path)
    assert json.loads((runtime / "manifest.json").read_text(encoding="utf-8"))["nopecha"]["key"] == ""


def test_roteamento_do_contexto(monkeypatch, tmp_path):
    """Só loopback abre o contexto persistente com a extensão; o resto usa o navegador normal."""
    import cpmh_backend.services.capture as capture

    monkeypatch.setattr(capture, "find_browser", lambda: ("/usr/bin/chrome", "Chrome"))
    monkeypatch.setenv("CPMH_LAB_MODE", "1")
    monkeypatch.setenv("CPMH_LAB_PROFILE_DIR", str(tmp_path))
    monkeypatch.delenv("NOPECHA_KEY", raising=False)
    calls: list = []

    class Ctx:
        def close(self):
            pass

    class Chromium:
        def launch_persistent_context(self, user_dir, **kw):
            calls.append(("lab", kw["headless"], any(a.startswith("--load-extension=") for a in kw["args"])))
            return Ctx()

    class Playwright:
        chromium = Chromium()

    def launch_browser(_pw):
        calls.append(("normal",))

        class Browser:
            def new_context(self, **kw):
                return Ctx()

            def close(self):
                pass

        return Browser()

    viewport = {"width": 10, "height": 10}
    lab_extension.open_capture_context(Playwright(), "http://localhost:8000/lab.html", launch_browser=launch_browser, viewport=viewport)
    for outside in ("http://192.168.0.5/x", "file:///C:/Users/a/Downloads/a.html", "https://site.com/doc"):
        lab_extension.open_capture_context(Playwright(), outside, launch_browser=launch_browser, viewport=viewport)
    assert calls == [("lab", False, True), ("normal",), ("normal",), ("normal",)]


class _FakePage:
    """Página simulada: devolve sinais em JSON, como o evaluate_page espera."""

    def __init__(self, texts):
        self.url = "http://localhost:8000/doc.html"
        self._texts = list(texts)
        self.waited_ms = 0

    def evaluate(self, _script):
        text = self._texts.pop(0) if len(self._texts) > 1 else self._texts[0]
        return json.dumps({"title": "Documento", "text": text, "markers": [], "iframes": [], "scripts": [], "ready": "complete"})

    def wait_for_timeout(self, ms):
        self.waited_ms += ms


SLIDER = "Arraste o botão para completar a verificação de segurança"
LIMPO = "Capítulo 1. Introdução ao documento de teste " * 20


def test_slider_por_texto_e_detectado_sem_widget():
    import cpmh_backend.services.capture as capture

    verdict = capture._challenge_verdict(_FakePage([SLIDER]))
    assert verdict is not None and verdict["provider"] == "slider"
    assert capture._challenge_verdict(_FakePage([LIMPO])) is None


def test_espera_segue_o_veredito_e_nao_so_widgets(monkeypatch):
    """Regressão: antes a espera olhava só seletores de widget e voltava na hora numa página de slider."""
    import cpmh_backend.services.capture as capture

    monkeypatch.setenv("CPMH_LAB_MODE", "1")
    monkeypatch.setenv("CPMH_LAB_EXTENSION_DIR", str(BUNDLED_EXTENSION))
    monkeypatch.setenv("CPMH_LAB_SOLVE_TIMEOUT", "10")
    page = _FakePage([SLIDER, SLIDER, SLIDER, LIMPO])  # desafio some na 4ª leitura
    info = capture._lab_wait(page, page.url)
    assert info["cleared"] is True and info["waited"] == 3.0
    assert page.waited_ms == 3000


def test_desafio_que_nao_resolve_gera_nota_no_relatorio(monkeypatch):
    import cpmh_backend.services.capture as capture

    monkeypatch.setenv("CPMH_LAB_MODE", "1")
    monkeypatch.setenv("CPMH_LAB_EXTENSION_DIR", str(BUNDLED_EXTENSION))
    monkeypatch.setenv("CPMH_LAB_SOLVE_TIMEOUT", "2")
    page = _FakePage([SLIDER])
    info = capture._lab_wait(page, page.url)
    assert info["cleared"] is False and info["provider"] == "slider"
    verdict = capture._with_lab_note(capture._challenge_verdict(page), info)
    assert any("modo laboratório" in item and "não resolvido" in item for item in verdict["evidence"])


def test_espera_nao_faz_nada_fora_do_laboratorio(monkeypatch):
    import cpmh_backend.services.capture as capture

    monkeypatch.delenv("CPMH_LAB_MODE", raising=False)
    page = _FakePage([SLIDER])
    assert capture._lab_wait(page, page.url) == {}
    monkeypatch.setenv("CPMH_LAB_MODE", "1")
    monkeypatch.setenv("CPMH_LAB_EXTENSION_DIR", str(BUNDLED_EXTENSION))
    assert capture._lab_wait(page, "https://site-externo.com/doc") == {}
    assert page.waited_ms == 0


def test_copia_liga_geetest_e_o_pacote_embutido_continua_igual(monkeypatch, tmp_path):
    monkeypatch.delenv("NOPECHA_KEY", raising=False)
    before = json.loads((BUNDLED_EXTENSION / "manifest.json").read_text(encoding="utf-8"))["nopecha"]
    runtime = prepare_runtime_extension(BUNDLED_EXTENSION, tmp_path)
    cfg = json.loads((runtime / "manifest.json").read_text(encoding="utf-8"))["nopecha"]
    assert cfg["geetest_auto_solve"] is True and cfg["geetest_auto_open"] is True
    assert before["geetest_auto_solve"] is False


def test_motivo_do_modo_laboratorio(monkeypatch, tmp_path):
    monkeypatch.delenv("CPMH_LAB_MODE", raising=False)
    assert "CPMH_LAB_MODE" in lab_extension.lab_reason("http://localhost:8000/")
    monkeypatch.setenv("CPMH_LAB_MODE", "1")
    monkeypatch.setenv("CPMH_LAB_EXTENSION_DIR", str(tmp_path))
    assert "manifest.json" in lab_extension.lab_reason("http://localhost:8000/")
    monkeypatch.setenv("CPMH_LAB_EXTENSION_DIR", str(BUNDLED_EXTENSION))
    assert "loopback" in lab_extension.lab_reason("http://192.168.0.5/")
    assert lab_extension.lab_reason("http://localhost:8000/") == "ativo"


def test_manual_desligado_por_padrao(monkeypatch):
    from cpmh_backend.services import manual_captcha as M

    monkeypatch.delenv("CPMH_MANUAL_CAPTCHA", raising=False)
    assert M.manual_captcha_enabled() is False
    assert M.wait_for_manual_solve(_FakePage([SLIDER]), lambda p: {"state": "CAPTCHA_DETECTED"}) == {}


def test_manual_abre_janela_visivel(monkeypatch):
    from cpmh_backend.services import manual_captcha as M

    monkeypatch.setenv("CPMH_MANUAL_CAPTCHA", "1")
    import cpmh_backend.services.capture as _cap
    monkeypatch.setattr(_cap, "find_browser", lambda: ("/usr/bin/chrome", "Chrome"))
    calls = []

    class Ctx:
        def close(self):
            pass

    class Chromium:
        def launch(self, **kw):
            calls.append(kw["headless"])

            class Browser:
                def new_context(self, **k):
                    return Ctx()

                def close(self):
                    pass

            return Browser()

    class PW:
        chromium = Chromium()

    def lb(_pw):
        calls.append("nunca deveria chamar isso")

    M.open_browser_context(PW(), launch_browser=lb, viewport={"width": 1, "height": 1})
    assert calls == [False]


def test_manual_espera_a_pessoa_resolver(monkeypatch):
    from cpmh_backend.services import manual_captcha as M

    monkeypatch.setenv("CPMH_MANUAL_CAPTCHA", "1")
    monkeypatch.setenv("CPMH_MANUAL_CAPTCHA_TIMEOUT", "10")
    page = _FakePage([SLIDER, SLIDER, LIMPO])
    checks = iter([{"state": "CAPTCHA_DETECTED"}, {"state": "CAPTCHA_DETECTED"}, None])
    info = M.wait_for_manual_solve(page, lambda p: next(checks))
    assert info["resolved"] is True and info["waited"] == 2.0


def test_manual_nao_interfere_com_laboratorio(monkeypatch):
    """Com o modo laboratório ativo para a URL, o app usa a extensão, não a janela manual."""
    import cpmh_backend.services.capture as capture

    monkeypatch.setenv("CPMH_LAB_MODE", "1")
    monkeypatch.setenv("CPMH_LAB_EXTENSION_DIR", str(BUNDLED_EXTENSION))
    monkeypatch.delenv("CPMH_MANUAL_CAPTCHA", raising=False)
    page = _FakePage([SLIDER, LIMPO])
    info = capture._resolution_wait(page, "http://localhost:8000/x.html")
    assert info.get("lab") is True  # veio da espera de laboratório, não da manual


def test_foca_e_espera_so_no_modo_manual(monkeypatch):
    from cpmh_backend.services import manual_captcha as M

    class Page:
        def __init__(self):
            self.calls = []

        def bring_to_front(self):
            self.calls.append("bring_to_front")

        def wait_for_load_state(self, state, timeout):
            self.calls.append(("load_state", state))

    monkeypatch.delenv("CPMH_MANUAL_CAPTCHA", raising=False)
    page = Page()
    M.focus_and_wait_ready(page, 5000)
    assert page.calls == []

    monkeypatch.setenv("CPMH_MANUAL_CAPTCHA", "1")
    page = Page()
    M.focus_and_wait_ready(page, 5000)
    assert page.calls == ["bring_to_front", ("load_state", "load"), ("load_state", "networkidle")]


def test_espera_apos_resolucao_so_quando_resolvido(monkeypatch):
    import cpmh_backend.services.capture as capture

    monkeypatch.setenv("CPMH_POST_SOLVE_SETTLE_MS", "0")  # isola as chamadas de load_state
    monkeypatch.setenv("CPMH_POST_SOLVE_TIMEOUT_MS", "1000")

    class Page:
        def __init__(self):
            self.calls = []

        def wait_for_load_state(self, state, timeout):
            self.calls.append(state)

        def evaluate(self, _script):
            return 1  # conteúdo constante: estabiliza na primeira checagem

        def wait_for_timeout(self, ms):
            pass

    page = Page()
    capture._wait_after_resolution(page, {}, 5000)
    assert page.calls == []

    page = Page()
    capture._wait_after_resolution(page, {"lab": True, "cleared": False}, 5000)
    assert page.calls == []

    page = Page()
    capture._wait_after_resolution(page, {"lab": True, "cleared": True}, 5000)
    assert page.calls == ["load", "networkidle"]

    page = Page()
    capture._wait_after_resolution(page, {"manual": True, "resolved": True}, 5000)
    assert page.calls == ["load", "networkidle"]


class _GrowingPage:
    """Simula um visor que ainda está carregando: o conteúdo cresce a cada rodada até parar."""

    def __init__(self, growth_rounds: int):
        self.growth_rounds = growth_rounds
        self.round = 0
        self.waited_ms = 0

    def wait_for_load_state(self, state, timeout):
        pass

    def evaluate(self, _script):
        self.round += 1
        return min(self.round, self.growth_rounds) * 100

    def wait_for_timeout(self, ms):
        self.waited_ms += ms


def test_espera_apos_resolucao_segue_so_quando_conteudo_estabiliza(monkeypatch):
    import cpmh_backend.services.capture as capture

    monkeypatch.setenv("CPMH_POST_SOLVE_TIMEOUT_MS", "20000")
    monkeypatch.setenv("CPMH_POST_SOLVE_SETTLE_MS", "0")
    page = _GrowingPage(growth_rounds=4)  # conteúdo cresce por 4 rodadas e então estabiliza
    capture._wait_after_resolution(page, {"cleared": True}, 5000)
    # 4 rodadas de crescimento + 3 rodadas estáveis (stable_rounds) até confirmar
    assert page.round == 7


def test_espera_apos_resolucao_respeita_o_tempo_maximo(monkeypatch):
    import cpmh_backend.services.capture as capture

    monkeypatch.setenv("CPMH_POST_SOLVE_TIMEOUT_MS", "3000")
    monkeypatch.setenv("CPMH_POST_SOLVE_SETTLE_MS", "0")

    clock = {"now": 0.0}
    monkeypatch.setattr(capture.time, "perf_counter", lambda: clock["now"])

    class Page(_GrowingPage):
        def wait_for_timeout(self, ms):
            super().wait_for_timeout(ms)
            clock["now"] += ms / 1000

    page = Page(growth_rounds=10_000)  # nunca estabiliza sozinho
    capture._wait_after_resolution(page, {"resolved": True}, 1000)
    assert page.waited_ms <= 3000 + 1000  # não passa muito do orçamento (interval de 1s)
