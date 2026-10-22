"""The pages in French: from the browser's language or the EN/FR switch, every text of the page's
own is said in French, the song's own (title, chords, words) never is."""

from __future__ import annotations

import json
import shutil
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Page, expect

from tests.page.conftest import built
from tests.page.test_page import state, until
from woodshed import app
from woodshed.run import Options

# The visible texts and labels (outside the song's own, translate="no") still in the other
# language: an English text of W.FR on a French page, or a French one on an English page. A text of
# the dictionary the page's code wrote without W.t shows up here.
LEFT_OVER = """lang => {
  const norm = (t) => t.replace(/\\s+/g, " ").trim();
  const other = new Set();
  for (const [en, fr] of Object.entries(Woodshed.FR)) {
    if (norm(en) !== norm(fr)) other.add(norm(lang === "fr" ? en : fr));
  }
  const seen = (el) =>
    el.checkVisibility ? el.checkVisibility({ visibilityProperty: true }) : el.getClientRects().length > 0;
  const out = [];
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT);
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    const el = n.nodeType === 1 ? n : n.parentElement;
    if (!el || el.closest('[translate="no"], script, style') || !seen(el)) continue;
    if (n.nodeType === 3) {
      if (other.has(norm(n.nodeValue))) out.push(norm(n.nodeValue));
    } else {
      for (const a of ["title", "aria-label", "placeholder"]) {
        const v = n.getAttribute(a);
        if (v && other.has(norm(v))) out.push(a + ": " + v);
      }
    }
  }
  return out;
}"""

SONG_OWN = "() => [...document.querySelectorAll('[translate=\"no\"]')].map((el) => el.textContent)"


def left_over(page: Page, lang: str) -> list[str]:
    found: list[str] = page.evaluate(LEFT_OVER, lang)
    return found


def french(locale: str = "fr-FR") -> pytest.MarkDecorator:
    return pytest.mark.browser_context_args(locale=locale)


@french()
def test_a_browser_in_french_gets_the_page_in_french_and_the_song_as_it_is(open_page: Any) -> None:
    o = open_page("pop", title="Next")  # a title that is also a word of the page
    page = o.page
    expect(page.locator("html")).to_have_attribute("lang", "fr")
    expect(page.get_by_test_id("lang-fr")).to_have_attribute("aria-pressed", "true")
    expect(page.get_by_test_id("step-1")).to_contain_text("Écouter")
    expect(page.get_by_test_id("step-3")).to_contain_text("Boucler lentement")
    expect(page.get_by_test_id("play")).to_have_attribute("aria-label", "Lecture")
    expect(page.get_by_test_id("loop-info")).to_have_text("Pas de boucle")
    expect(page.get_by_test_id("inst-guitar")).to_have_text("Guitare")
    expect(page.get_by_test_id("title")).to_have_text("Next")  # the song's own: never translated
    expect(page.get_by_test_id("title")).to_have_attribute("translate", "no")
    first = o.js("Woodshed.current.song.bars[0].chords[0]")
    expect(page.get_by_test_id("now-chord")).to_have_text(o.js("c => Woodshed.current.chordName(c, 0)", first))
    assert left_over(page, "fr") == []
    song_own = page.evaluate(SONG_OWN)
    page.get_by_test_id("lang-en").click()
    expect(page.get_by_test_id("step-1")).to_contain_text("Listen")
    assert page.evaluate(SONG_OWN) == song_own  # the same chords, numerals and title in English
    assert left_over(page, "en") == []


def test_switching_language_while_playing_says_everything_again_and_the_music_goes_on(open_page: Any) -> None:
    o = open_page("pop")
    page = o.page
    o.js("() => { window.notReloaded = true; }")
    page.get_by_test_id("play").click()
    until(o, "Woodshed.debug().audioTime > 0.5")
    page.get_by_test_id("lang-fr").click()
    expect(page.locator("html")).to_have_attribute("lang", "fr")
    expect(page.get_by_test_id("step-1")).to_contain_text("Écouter")
    expect(page.get_by_test_id("loop-info")).to_have_text("Pas de boucle")
    expect(page.get_by_test_id("desk")).to_contain_text("Clique sur une position pour l'entendre.")
    assert left_over(page, "fr") == []
    at = state(o)["audioTime"]
    assert state(o)["playing"] and state(o)["track"] == "mix"
    until(o, f"Woodshed.debug().audioTime > {at + 0.3}")  # still playing, from where it was
    page.get_by_test_id("lang-en").click()
    expect(page.get_by_test_id("step-1")).to_contain_text("Listen")
    expect(page.get_by_test_id("loop-info")).to_have_text("No loop")
    assert left_over(page, "en") == []
    assert state(o)["playing"] and o.js("window.notReloaded === true")
    page.get_by_test_id("play").click()


def check_everywhere(o: Any, lang: str) -> None:
    """The page, its menus, each instrument's panel and stage mode, in `lang`."""
    page = o.page
    assert left_over(page, lang) == [], "the page"
    for button, menu in (("export", "export-menu"), ("tracks", "tracks-menu"), ("help", "help-menu")):
        page.get_by_test_id(button).click()
        expect(page.get_by_test_id(menu)).to_be_visible()
        assert left_over(page, lang) == [], button
        page.keyboard.press("Escape")
        expect(page.get_by_test_id(menu)).to_be_hidden()
    page.get_by_test_id("doubt").first.click()
    expect(page.get_by_test_id("doubt-pop")).to_be_visible()
    assert left_over(page, lang) == [], "the doubt"
    page.keyboard.press("Escape")
    for inst in ("guitar", "bass", "piano", "drums", "voice"):
        page.get_by_test_id(f"inst-{inst}").click()
        if inst == "guitar":
            for pos in ("barre", "funk", "open"):
                page.get_by_test_id(f"voicing-{pos}").click()
                assert left_over(page, lang) == [], pos
        if inst == "drums":
            expect(page.locator("#drumStaff svg")).to_be_visible()  # VexFlow drew it
        if inst == "voice" and page.get_by_test_id("voice-tenor").count():  # a song with singing
            page.get_by_test_id("voice-tenor").click()
        assert left_over(page, lang) == [], inst
        page.get_by_test_id("step-2").click()  # a toast about this instrument
        assert left_over(page, lang) == [], f"{inst}, step 2"
    page.get_by_test_id("stage-open").click()
    expect(page.get_by_test_id("stage")).to_be_visible()
    assert left_over(page, lang) == [], "stage mode"
    page.get_by_test_id("stage-exit").click()
    page.get_by_test_id("words-open").click()
    expect(page.get_by_test_id("words-dialog")).to_be_visible()
    assert left_over(page, lang) == [], "the words"
    page.keyboard.press("Escape")


def test_every_text_of_the_page_switched_to_french_is_french(open_page: Any) -> None:
    o = open_page("pickup", close_calls=True)  # doubts to check: the facts, the list, the pop
    o.page.get_by_test_id("lang-fr").click()
    check_everywhere(o, "fr")


@french()
def test_every_text_of_a_page_opened_in_french_is_french_and_back_in_english(open_page: Any) -> None:
    o = open_page("pickup", close_calls=True)
    check_everywhere(o, "fr")
    o.page.get_by_test_id("lang-en").click()
    check_everywhere(o, "en")


@french()
def test_the_voice_panel_in_french(open_page: Any) -> None:
    o = open_page("ballad")  # a sung melody: a range to match
    page = o.page
    page.get_by_test_id("inst-voice").click()
    expect(page.get_by_test_id("voice-tenor")).to_have_text("Ténor")
    page.get_by_test_id("voice-tenor").click()
    expect(page.locator(".fit")).to_contain_text("ta voix (ténor)")
    assert left_over(page, "fr") == []
    page.get_by_test_id("lang-en").click()
    expect(page.locator(".fit")).to_contain_text("tenor voice")
    assert left_over(page, "en") == []


@french()
def test_the_words_view_in_french_keeps_the_words(open_page: Any) -> None:
    o = open_page("pop", variant="lyrics")
    page = o.page
    expect(page.get_by_test_id("sheet-lyrics")).to_have_text("Paroles")
    expect(page.get_by_test_id("words-open")).to_have_text("Modifier les paroles")
    expect(page.locator(".lline .wt").first).to_have_text("Morning")
    assert page.locator(".lline .wt").first.get_attribute("translate") == "no"
    assert left_over(page, "fr") == []
    page.get_by_test_id("stage-open").click()
    expect(page.get_by_test_id("stage-lyrics")).to_be_visible()
    assert left_over(page, "fr") == []


@pytest.fixture
def library(tmp_path: Path, pages_root: str) -> Iterator[app.AppServer]:
    srv = app.AppServer(app.Library(tmp_path / "library", Options(use_stems=False, open_page=False)))
    page = srv.library.root / "Pop.woodshed"
    shutil.copytree(built("pop", True, pages_root), page)
    summary = {"title": "Pop", "key": "C", "bpm": 120, "meter": "4/4", "duration": 16, "doubts": 0, "stems": True}
    (page / "woodshed.json").write_text(json.dumps({"settings": {}, "summary": summary, "complete": True}))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()
    srv.server_close()


@french()
def test_the_library_in_french(page: Page, library: app.AppServer) -> None:
    problems: list[str] = []
    page.on("console", lambda m: problems.append(m.text) if m.type in ("error", "warning") else None)
    page.goto(library.url)
    expect(page.get_by_test_id("summary")).to_have_text("1 morceau")
    expect(page.locator("h1")).to_have_text("Tes morceaux")
    expect(page).to_have_title("Bibliothèque · woodshed")
    expect(page.get_by_test_id("song-link")).to_have_text("Pop")
    expect(page.get_by_test_id("song-status")).to_contain_text("Parties")  # what the page has, in quiet tags
    expect(page.get_by_test_id("add-words")).to_have_text("ajouter les paroles")
    page.get_by_test_id("set-add").click()
    expect(page.get_by_test_id("set-item")).to_have_count(1)
    expect(page.get_by_test_id("set-remove")).to_have_attribute("aria-label", "Retirer du set")
    assert left_over(page, "fr") == []
    page.get_by_test_id("lang-en").click()
    expect(page.get_by_test_id("summary")).to_have_text("1 song")
    expect(page.locator("h1")).to_have_text("Your songs")
    expect(page.get_by_test_id("set-remove")).to_have_attribute("aria-label", "Out of the set")
    expect(page).to_have_title("Library · woodshed")
    assert left_over(page, "en") == []
    page.get_by_test_id("song-link").click()  # the song page in the language chosen
    expect(page.get_by_test_id("step-1")).to_contain_text("Listen")
    assert problems == []
