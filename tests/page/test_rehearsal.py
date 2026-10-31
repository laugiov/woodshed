"""The rehearsal sheet (spec 031): the band's old chord sheets inside woodshed. One song, one screen if it can,
simple chords over the words, nothing else; it follows the band from song to song."""

from __future__ import annotations

from typing import Any

import pytest
from playwright.sync_api import Browser, Page, expect

from tests.page.conftest import VARIANTS, built, rewritten
from tests.page.test_band import library, server, until  # noqa: F401  (the fixtures: pop and waltz, in a set)
from woodshed import app

QUALITIES = ["", "m", "5", "6", "m6", "7", "m7", "maj7", "9", "m9", "maj9", "add9", "madd9", "sus2", "sus4",
             "7sus4", "dim", "dim7", "m7b5", "aug"]  # fmt: skip
USUAL = {"9": "7", "m9": "m7", "maj9": "maj7", "add9": "", "madd9": "m"}
TRIADS = {"": "", "m": "m", "5": "5", "6": "", "m6": "m", "7": "", "m7": "m", "maj7": "", "9": "", "m9": "m",
          "maj9": "", "add9": "", "madd9": "m", "sus2": "sus2", "sus4": "sus4", "7sus4": "sus4", "dim": "dim",
          "dim7": "dim", "m7b5": "dim", "aug": "aug"}  # fmt: skip


def page_of(browser: Browser, folder: Any, hash_: str = "", **context: Any) -> Page:
    page = browser.new_context(locale="en-US", **context).new_page()
    page.goto((folder / "index.html").as_uri() + hash_)
    page.wait_for_function("window.Woodshed && window.Woodshed.ready === true")
    return page


def words_page(browser: Browser, root: str, hash_: str = "", **context: Any) -> Page:
    return page_of(browser, rewritten("pop", root, "lyrics", VARIANTS["lyrics"]), hash_, **context)


def test_the_chords_simplify_by_level(browser: Browser, pages_root: str) -> None:
    page = page_of(browser, built("pop", True, pages_root))
    got = page.evaluate(
        """qs => ['heard', 'usual', 'triads'].map(level => qs.map(q => {
            const c = W.chords.simplify({ pc: 0, quality: q, bass: 4 }, level);
            return [c.quality, c.bass === undefined ? null : c.bass]; }))""".replace("W.", "Woodshed."),
        QUALITIES,
    )
    heard, usual, triads = got
    assert heard == [[q, 4] for q in QUALITIES]
    assert usual == [[USUAL.get(q, q), 4] for q in QUALITIES]  # slash basses kept: a bassist's cue
    assert triads == [[TRIADS[q], None] for q in QUALITIES]


def test_the_sheet_opens_over_the_page_and_keeps_its_place(browser: Browser, pages_root: str) -> None:
    page = words_page(browser, pages_root, viewport={"width": 1440, "height": 900})
    page.get_by_test_id("rehearsal-open").click()
    sheet = page.get_by_test_id("rehearsal")
    expect(sheet).to_be_visible()
    assert page.evaluate("location.hash") == "#rehearsal"
    expect(page.locator("html")).to_have_attribute("data-stage", "")  # no decor
    expect(sheet.get_by_test_id("rh-title")).to_contain_text("pop")
    expect(sheet.locator(".rh-line").first).to_be_visible()  # the words, chords above
    assert sheet.locator(".rh-line .rh-c").filter(has_text="C").count() > 0
    hidden = sheet.evaluate("s => s.querySelectorAll('.bar, .doubt, [data-testid=position], .num').length")
    assert hidden == 0  # no bar numbers, times or doubt marks
    page.reload()
    page.wait_for_function("window.Woodshed && window.Woodshed.ready === true")
    expect(page.get_by_test_id("rehearsal")).to_be_visible()  # opened from the address
    page.keyboard.press("Escape")
    expect(page.get_by_test_id("rehearsal")).to_be_hidden()
    assert page.evaluate("location.hash") == ""


def test_a_song_without_words_reads_as_bar_lines(browser: Browser, pages_root: str) -> None:
    page = page_of(browser, built("pop", True, pages_root), "#rehearsal", viewport={"width": 1440, "height": 900})
    bars = page.get_by_test_id("rehearsal").locator(".rh-bars").first
    expect(bars).to_have_text(__import__("re").compile(r"^\| \S.*\|$"))


def test_a_section_repeated_at_once_reads_as_times_two(browser: Browser, pages_root: str) -> None:
    page = page_of(browser, built("pop", True, pages_root))
    got = page.evaluate(
        """() => Woodshed.rehearsal.collapse([
            { name: 'Verse 1', lines: [{ words: [{ chord: 'C', text: 'a' }] }] },
            { name: 'Chorus 1', lines: [{ words: [{ chord: 'F', text: 'b' }] }] },
            { name: 'Chorus 2', lines: [{ words: [{ chord: 'F', text: 'b' }] }] },
            { name: 'Verse 2', lines: [{ words: [{ chord: 'C', text: 'c' }] }] },
          ]).map(s => [s.name, s.times])"""
    )
    assert got == [["Verse 1", 1], ["Chorus", 2], ["Verse 2", 1]]


def test_the_sheet_fits_a_laptop_and_pages_on_a_phone(browser: Browser, pages_root: str) -> None:
    page = words_page(browser, pages_root, "#rehearsal", viewport={"width": 1440, "height": 900})
    body = page.locator(".rh-body")
    size = float(body.evaluate("b => getComputedStyle(b).getPropertyValue('--rh-size')").replace("px", ""))
    assert size >= 18
    assert body.evaluate("b => b.scrollWidth <= b.clientWidth + 1 && b.scrollHeight <= b.clientHeight + 1")
    phone = words_page(browser, pages_root, "#rehearsal", viewport={"width": 390, "height": 844}, has_touch=True)
    for _ in range(12):
        phone.get_by_test_id("rh-bigger").tap()  # bigger than it fits: pages
    pager = phone.get_by_test_id("rh-pager")
    expect(pager).to_be_visible()
    before = phone.locator(".rh-body").evaluate("b => b.scrollLeft")
    phone.keyboard.press("ArrowRight")  # a pedal turns the page; the song does not move
    phone.wait_for_timeout(400)
    assert phone.locator(".rh-body").evaluate("b => b.scrollLeft") > before
    assert phone.evaluate("Woodshed.app.store.get().beat") == 0


def test_the_current_line_is_marked(browser: Browser, pages_root: str) -> None:
    page = words_page(browser, pages_root, "#rehearsal", viewport={"width": 1440, "height": 900})
    t = page.evaluate("Woodshed.app.words.lines[1].start + 0.2")
    page.evaluate(f"Woodshed.app.store.set({{ time: {t}, beat: Woodshed.app.song.beatAt({t}) }})")
    expect(page.locator(".rh-line.cur")).to_have_count(1)


def test_the_next_song_opens_on_the_sheet(browser: Browser, server: app.AppServer) -> None:  # noqa: F811
    page = browser.new_context(locale="en-US").new_page()
    page.goto(server.url + "pop.woodshed/index.html#rehearsal")
    until(page, "window.Woodshed && window.Woodshed.ready === true")
    until(page, "!!document.querySelector('#rehearsal:not([hidden])')")
    until(page, "Woodshed.app.store.get().canShare === true")  # the library answered: the set is known
    page.wait_for_timeout(500)
    page.evaluate("Woodshed.app.nextSong()")
    page.wait_for_url("**/waltz.woodshed/index.html#rehearsal", timeout=10_000)
    for _ in range(100):  # polled through the navigation: the new page's context may not be there yet
        try:
            if page.evaluate("window.Woodshed && window.Woodshed.ready === true"):
                break
        except Exception:
            pass
        page.wait_for_timeout(100)
    expect(page.get_by_test_id("rehearsal")).to_be_visible()


@pytest.mark.parametrize("level", ["triads", "usual"])
def test_the_level_and_size_are_remembered(browser: Browser, pages_root: str, level: str) -> None:
    page = words_page(browser, pages_root, "#rehearsal", viewport={"width": 1440, "height": 900})
    page.get_by_test_id(f"rh-level-{level}").click()
    page.reload()
    page.wait_for_function("window.Woodshed && window.Woodshed.ready === true")
    expect(page.get_by_test_id(f"rh-level-{level}")).to_have_attribute("aria-pressed", "true")
