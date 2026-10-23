"""The chart on paper (spec 014): no page printed blank."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from playwright.sync_api import Page

from tests.page.conftest import built
from tests.page.pdf_pages import pages_with_text
from woodshed import build

# The page data of "As I Am, last chorus lifted (Josh Woodward, edited)": "As I Am" by Josh Woodward, CC BY 4.0
# (demo/LICENSE.md), changed by us: the recording from 2:30 pitched up a semitone, to show a key change. A long
# chart, the one round 5 printed with a blank third page (Marion). No words, no audio.
LIFTED = Path(__file__).parent / "data" / "lifted-as-i-am.json"


def test_a_long_chart_prints_no_blank_page(page: Page, pages_root: str, browser_name: str) -> None:
    if browser_name != "chromium":
        pytest.skip("PDF printing is Chromium's")
    folder = Path(pages_root) / "lifted-print.woodshed"
    if not folder.exists():
        shutil.copytree(built("pop", False, pages_root), folder)
        index = folder / "index.html"
        text = index.read_text(encoding="utf-8")
        found = build.DATA_BLOCK.search(text)
        assert found is not None
        data = json.loads(LIFTED.read_text(encoding="utf-8"))
        index.write_text(text[: found.start(1)] + build.script_json(data) + text[found.end(1) :], encoding="utf-8")
    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto((folder / "index.html").as_uri())
    page.wait_for_function("window.Woodshed && Woodshed.ready === true")
    page.evaluate("Woodshed.app.setInstrument('guitar')")
    # No emulate_media: printing lays the page out for paper from the screen's state, as a browser's Print does.
    pages = pages_with_text(page.pdf(format="A4", prefer_css_page_size=True))
    assert len(pages) == 2 and all(pages), pages  # the whole chart on two pages, none blank
