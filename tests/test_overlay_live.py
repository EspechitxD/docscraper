"""Mede o overlay no Chromium.

A caixa é desenhada no sistema da página. O fator de escala do Chromium
amplia a página inteira, inclusive o SVG. A comparação usa o retângulo
CSS do alvo e o da caixa. A tolerância aceita é 3 px.
"""

from pathlib import Path

import pytest

OVERLAY = Path(__file__).resolve().parents[1] / "electron" / "overlay.js"


def test_live_overlay_stays_within_three_pixels():
    playwright = pytest.importorskip("playwright.sync_api")
    html = """
    <!doctype html>
    <html><body style="margin:0">
      <div id="target" style="position:absolute;left:120px;top:90px;width:240px;height:48px;background:#ff5000"></div>
      <div style="width:1400px;height:1800px"></div>
    </body></html>
    """
    script = OVERLAY.read_text(encoding="utf-8")
    deltas: list[tuple[str, float]] = []
    with playwright.sync_playwright() as manager:
        browser = manager.chromium.launch(channel="chrome", args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 900, "height": 700})
        page.set_content(html)
        page.evaluate(script)
        session = page.context.new_cdp_session(page)
        bbox = page.evaluate(
            """() => {
              const rect = document.getElementById("target").getBoundingClientRect();
              const width = document.documentElement.scrollWidth;
              const height = document.documentElement.scrollHeight;
              return [rect.left / width, rect.top / height, rect.width / width, rect.height / height];
            }"""
        )
        page.evaluate(
            """(box) => window.cpmhApplyOverlay({visible: true, regions: [{id: "alvo", category: "title", bbox: box}]})""",
            bbox,
        )

        def measure(label: str) -> None:
            delta = page.evaluate(
                """() => {
                  const target = document.getElementById("target").getBoundingClientRect();
                  const box = document.querySelector("#cpmh-overlay rect").getBoundingClientRect();
                  return Math.max(
                    Math.abs(target.left - box.left),
                    Math.abs(target.top - box.top),
                    Math.abs(target.width - box.width),
                    Math.abs(target.height - box.height)
                  );
                }"""
            )
            deltas.append((label, float(delta)))

        for zoom in (0.5, 0.75, 1, 1.25, 1.5, 2):
            session.send("Emulation.setPageScaleFactor", {"pageScaleFactor": zoom})
            page.evaluate(
                """(box) => window.cpmhApplyOverlay({visible: true, regions: [{id: "alvo", category: "title", bbox: box}]})""",
                bbox,
            )
            measure(f"zoom-{zoom}")
        page.evaluate("() => window.scrollTo(80, 220)")
        page.evaluate(
            """(box) => window.cpmhApplyOverlay({visible: true, regions: [{id: "alvo", category: "title", bbox: box}]})""",
            bbox,
        )
        measure("scroll")
        page.set_viewport_size({"width": 640, "height": 480})
        page.evaluate("() => window.dispatchEvent(new Event('resize'))")
        page.evaluate(
            """(box) => window.cpmhApplyOverlay({visible: true, regions: [{id: "alvo", category: "title", bbox: box}]})""",
            bbox,
        )
        measure("resize")
        browser.close()
    worst = max(item[1] for item in deltas)
    assert worst <= 3, deltas
