"""The band's first feedback (spec 031): capo shapes where the guitarist looks, the song's notes on its page and on
stage, and the band's own title and artist everywhere the title shows."""

from __future__ import annotations

from typing import Any

from playwright.sync_api import Browser, Page, expect

from tests.page.conftest import built
from tests.page.test_band import until
from tests.page.test_set_name_page import library, opened, server  # noqa: F401  (the fixtures)
from woodshed import app

SONG = "pop.woodshed"


def song_page(browser: Browser, url: str, **context: Any) -> Page:
    page = browser.new_context(locale="en-US", viewport={"width": 1280, "height": 860}, **context).new_page()
    page.goto(url)
    until(page, "window.Woodshed && window.Woodshed.ready === true")
    return page


# A. Capo shapes


def test_a_guitarist_with_a_capo_reads_the_shapes_by_default(browser: Browser, pages_root: str) -> None:
    page = song_page(browser, (built("pop", True, pages_root) / "index.html").as_uri())
    page.evaluate("Woodshed.app.store.set({ capo: 0 }); Woodshed.app.store.set({ capo: 2 })")
    expect(page.get_by_test_id("toast")).to_contain_text("shapes")  # said once, the first time a capo is set
    switch = page.locator("#viewCtl .seg-ctl").first
    expect(switch.get_by_test_id("show-shapes")).to_have_attribute("aria-pressed", "true")
    assert page.evaluate(
        "document.querySelector('#viewCtl').firstElementChild.contains(document.querySelector('[data-testid=show-shapes]'))"
    )
    page.get_by_test_id("show-concert").click()
    page.reload()
    until(page, "window.Woodshed && window.Woodshed.ready === true")
    page.evaluate("Woodshed.app.store.set({ capo: 2 })")
    expect(page.get_by_test_id("show-concert")).to_have_attribute("aria-pressed", "true")  # remembered
    assert page.get_by_test_id("toast").is_hidden() or "shapes" not in page.get_by_test_id("toast").inner_text()
    page.get_by_test_id("stage-open").click()
    expect(page.get_by_test_id("stage-show-shapes")).to_be_visible()  # the same switch on stage
    page.get_by_test_id("stage-show-shapes").click()
    assert page.evaluate("Woodshed.app.store.get().view") == "shapes"


def test_the_bass_never_reads_shapes(browser: Browser, pages_root: str) -> None:
    page = song_page(browser, (built("pop", True, pages_root) / "index.html").as_uri())
    page.evaluate("Woodshed.app.store.set({ capo: 2, inst: 'bass' })")
    assert page.evaluate("Woodshed.app.showShapes(Woodshed.app.store.get())") is False
    expect(page.get_by_test_id("show-shapes")).to_have_count(0)


# B. Notes


def test_the_song_s_notes_on_its_page_on_stage_and_live(browser: Browser, server: app.AppServer) -> None:  # noqa: F811
    url = server.url + SONG + "/index.html"
    page = song_page(browser, url)
    other = song_page(browser, url)
    page.get_by_test_id("notes-add").click()
    field = page.get_by_test_id("notes-input")
    page.get_by_test_id("notes-start").click()
    field.press("End")
    field.type("drums count 4, then guitar")
    page.get_by_test_id("notes-end").click()
    field.type("stop on the 1")
    page.get_by_test_id("notes-save").click()
    note = page.get_by_test_id("band-note")
    expect(note.locator("p")).to_have_text(["Start: drums count 4, then guitar", "End: stop on the 1"])
    assert (
        server.library.corrections(SONG, "x")["band"]["note"] == "Start: drums count 4, then guitar\nEnd: stop on the 1"
    )
    expect(other.get_by_test_id("band-note")).to_contain_text("stop on the 1", timeout=5000)  # every device, live
    page.get_by_test_id("stage-open").click()
    strip = page.get_by_test_id("stage-note")
    expect(strip).to_have_text("Start: drums count 4, then guitar …")  # the first line on stage, more to come
    strip.click()
    expect(strip).to_contain_text("End: stop on the 1")  # all of it on a tap
    page.keyboard.press("Escape")
    page.get_by_test_id("notes-edit").click()
    page.get_by_test_id("notes-input").fill("changed")
    page.get_by_test_id("notes-input").press("Escape")
    expect(page.get_by_test_id("band-note")).to_contain_text("stop on the 1")  # cancelled


def test_the_set_list_edits_the_same_notes_and_shows_their_first_line(page: Page, server: app.AppServer) -> None:  # noqa: F811
    server.library.set_band({"page": SONG, "note": "Start: drums\nEnd: stop on the 1"})
    opened(page, server)
    note = page.locator(f'[data-set-song="{SONG}"]').get_by_test_id("set-note")
    expect(note).to_have_text("Note: Start: drums …")
    note.click()
    expect(page.get_by_test_id("set-note-input")).to_have_value("Start: drums\nEnd: stop on the 1")


# C. Title and artist


def test_the_band_names_the_song_and_every_place_follows(browser: Browser, server: app.AppServer) -> None:  # noqa: F811
    page = song_page(browser, server.url + SONG + "/index.html")
    page.get_by_test_id("title-edit").click()
    expect(page.get_by_test_id("title-artist")).to_have_value("")
    expect(page.get_by_test_id("title-name")).to_have_value("pop")
    page.get_by_test_id("title-artist").fill("Les Imprévus")
    page.get_by_test_id("title-name").fill("Pop song")
    page.get_by_test_id("title-name").press("Enter")
    expect(page.get_by_test_id("title")).to_have_text("Les Imprévus - Pop song")
    expect(page).to_have_title("Les Imprévus - Pop song · woodshed")
    chordpro = page.evaluate("Woodshed.exports.chordpro(Woodshed.app.song)")
    assert "{title: Les Imprévus - Pop song}" in chordpro  # the exports carry the band's title
    home = song_page(browser, server.url)
    expect(home.get_by_test_id("song-link").first).to_contain_text("Les Imprévus - Pop song")
    expect(home.locator(f'[data-set-song="{SONG}"]')).to_contain_text("Pop song")
    page.get_by_test_id("title-edit").click()
    page.get_by_test_id("title-reset").click()
    expect(page.get_by_test_id("title")).to_have_text("pop")
    assert "title" not in server.library.corrections(SONG, "x")["band"]
