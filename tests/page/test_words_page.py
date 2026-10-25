"""Adding the words from the page: served by `woodshed app`, or the command when opened from disk."""

from __future__ import annotations

import json
import shutil
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Page, expect

from tests.page.conftest import built, lyrics_for
from woodshed import app, lyrics
from woodshed.run import Options

WORDS = "[Verse]\nMorning comes in on the harbour road,\nthe radio hums\n"


def test_from_disk_the_dialog_gives_the_command(open_page: Any) -> None:
    o = open_page("pop")
    expect(o.page.get_by_test_id("words-open")).to_have_text("Add the words")
    header = o.page.get_by_test_id("words-header")  # where it is seen, in the accent colour
    expect(header).to_have_text("+ Add the words")
    expect(header).to_have_class("btn primary")
    header.click()
    expect(o.page.get_by_test_id("words-dialog")).to_be_visible()
    expect(o.page.get_by_test_id("words-command")).to_have_text(f'woodshed lyrics "{o.folder.name}" words.txt')
    o.page.keyboard.press("Escape")
    expect(o.page.get_by_test_id("words-dialog")).to_be_hidden()


def test_a_page_without_the_singers_track_offers_tapping_along_only(open_page: Any) -> None:
    o = open_page("waltz", stems=False)
    expect(o.page.get_by_test_id("words-open")).to_be_visible()  # spec 029-2: tapping along needs no voice
    o.page.get_by_test_id("words-header").click()
    expect(o.page.get_by_test_id("words-tap-library")).to_be_visible()  # from disk: the library lays them
    expect(o.page.get_by_test_id("words-command")).to_have_count(0)  # no voice: no model


@pytest.fixture
def library(tmp_path: Path, pages_root: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[app.AppServer]:
    srv = app.AppServer(app.Library(tmp_path / "library", Options(use_stems=False, open_page=False)))
    page = srv.library.root / "Pop.woodshed"
    shutil.copytree(built("pop", True, pages_root), page)
    summary = {"title": "Pop", "key": "C", "bpm": 120, "meter": "4/4", "duration": 16, "doubts": 0, "stems": True}
    (page / "woodshed.json").write_text(json.dumps({"settings": {}, "summary": summary, "complete": True}))
    pasted: list[str] = []

    def add_to_page(
        folder: Path, text: str, offline: bool = False, say: Any = print, progress: Any = None, commit: Any = None
    ) -> dict[str, Any]:
        pasted.append(text)  # the speech model is not run here: the words of the test song are written
        say("listening to the voice")
        progress(0.5)
        time.sleep(2.5)  # long enough for the page to show where it is
        data = lyrics_for(lyrics.page_song(folder)) | {"text": text}
        lyrics.write(folder, data)
        return data

    monkeypatch.setattr(lyrics, "add_to_page", add_to_page)
    srv.pasted = pasted  # type: ignore[attr-defined]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()
    srv.server_close()


def test_words_pasted_in_the_page_are_placed_and_shown(page: Page, library: app.AppServer) -> None:
    problems: list[str] = []
    page.on("console", lambda m: problems.append(m.text) if m.type in ("error", "warning") else None)
    page.goto(library.url)
    link = page.get_by_test_id("add-words")
    expect(link).to_have_text("add the words")
    link.click()  # the song page, the dialog open
    dialog = page.get_by_test_id("words-dialog")
    expect(dialog).to_be_visible()
    page.get_by_test_id("words-text").fill(WORDS)
    page.get_by_test_id("words-place").focus()
    page.keyboard.press("s")  # the page's own keys are off while the dialog is open
    expect(page.get_by_test_id("stage")).to_be_hidden()
    page.keyboard.press("Escape")
    page.get_by_test_id("words-header").click()
    expect(page.get_by_test_id("words-text")).to_have_value(WORDS)  # closed by mistake: the paste is kept
    page.get_by_test_id("words-place").click()
    expect(page.get_by_test_id("words-percent")).to_have_text("50 %")  # half the voice heard
    expect(page.get_by_test_id("words-status")).to_have_text("Listening to the voice")
    expect(page.get_by_test_id("sheet-lyrics")).to_be_visible(timeout=15000)  # reloaded with the words
    expect(page.locator(".lline").first).to_contain_text("Morning")
    expect(page.get_by_test_id("toast")).to_contain_text("Words placed")  # said after the reload
    assert library.pasted == [WORDS]  # type: ignore[attr-defined]
    page.get_by_test_id("words-open").click()
    expect(page.get_by_test_id("words-text")).to_have_value(WORDS)  # editable again, as pasted
    page.goto(library.url)
    expect(page.get_by_test_id("song-link")).to_be_visible()
    expect(page.get_by_test_id("add-words")).to_have_count(0)  # the song has its words now
    assert problems == []


def test_a_phone_of_the_band_is_not_offered_to_add_words(
    page: Page, library: app.AppServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    page.goto(library.url + "Pop.woodshed/index.html")
    for _ in range(200):  # the page wired (polled: the CSP forbids Playwright's string evaluation)
        if page.evaluate("window.Woodshed && window.Woodshed.ready === true"):
            break
        page.wait_for_timeout(25)
    expect(page.get_by_test_id("words-header")).to_be_visible()  # this computer: words are placed here
    monkeypatch.setattr(app.Handler, "_from_this_computer", lambda self: False)  # now a phone of the band
    page.reload()
    for _ in range(200):
        if page.evaluate("window.Woodshed && window.Woodshed.ready === true"):
            break
        page.wait_for_timeout(25)
    expect(page.get_by_test_id("words-header")).to_be_hidden()  # no button that leads to a refusal
    expect(page.get_by_test_id("words-open")).to_have_count(0)
