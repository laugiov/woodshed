"""A whole text pasted and laid by tapping along (spec 029-2), in the page: the one Words dialog with its two paths
(tapping along, no model; the speech model, its licence said), the tap-along mode (Space, a pedal or the big button
on a touch screen at each line's start, Escape to leave), one Undo for the whole layout, a library started with
`--no-words-model`, French."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from playwright.sync_api import Browser, Page, expect

from tests.page.test_edit_a_line import until
from tests.page.test_words_by_hand import device, library, meta, typed_entries, typed_row
from woodshed import app, typed

__all__ = ["library"]  # the fixture, shared

TEXT = "[Verse 1]\nWhen you walk on\nhold on to the light\n\n[Chorus]\nla la la la (ooh)\n"
BEATS = [8.1, 16.4, 24.9]  # where each line is tapped, in beats (a tap falls between the beats)


def open_words(page: Page) -> None:
    page.get_by_test_id("words-header").click()
    expect(page.get_by_test_id("words-dialog")).to_be_visible()


def start_tapping(page: Page, text: str = TEXT) -> None:
    open_words(page)
    page.get_by_test_id("words-text").fill(text)
    page.get_by_test_id("words-tap").click()
    expect(page.get_by_test_id("tap-along")).to_be_visible()
    expect(page.get_by_test_id("words-dialog")).to_be_hidden()
    # The music starts with the mode; here it is stopped and moved by hand, so each tap falls where the test says.
    until(page, "Woodshed.app.store.get().playing === true")
    page.evaluate("Woodshed.app.togglePlay()")
    until(page, "Woodshed.app.store.get().playing === false")


def at_beat(page: Page, beat: float) -> float:
    """Moves the music to a beat's time; the beat index a tap there sends (snapped to a quarter beat)."""
    s = meta(page)
    t = typed.beat_time(s, beat)
    page.evaluate("(t) => Woodshed.app.seekTime(t)", t)
    until(page, f"Math.abs(Woodshed.app.transport.time - {t}) < 0.002")
    return typed.snap(typed.beat_at(s, t))


def laid_ats(srv: app.AppServer) -> list[float]:
    entries = typed_entries(srv).values()
    assert all(e["by"] == "layout" for e in entries)
    return sorted(e["lines"][0]["words"][0]["at"] for e in entries)


def test_paste_then_tap_space_at_each_line_lays_them_with_one_undo(
    browser: Browser, library: Callable[[str], app.AppServer]
) -> None:
    srv = library("sections")
    problems: list[str] = []
    page = device(browser, srv, problems)
    sent: list[Any] = []
    page.on("request", lambda r: sent.append(r.post_data_json) if r.url.endswith("/api/words") else None)
    start_tapping(page)
    expect(page.get_by_test_id("tap-line")).to_have_text("When you walk on")
    expect(page.get_by_test_id("tap-count")).to_have_text("Line 1 of 3")
    want = []
    for k, beat in enumerate(BEATS):
        want.append(at_beat(page, beat))
        page.keyboard.press("Space")
        if k < 2:
            expect(page.get_by_test_id("tap-count")).to_have_text(f"Line {k + 2} of 3")
    expect(page.get_by_test_id("tap-along")).to_be_hidden()  # the last line tapped: laid
    expect(page.get_by_test_id("toast")).to_contain_text("3 lines laid by tapping along")
    expect(typed_row(page)).to_have_count(3)
    assert laid_ats(srv) == want and want == [8.0, 16.5, 25.0]  # snapped to the nearest quarter beat
    assert [b["layout"]["taps"] for b in sent] == [want]  # snapped by the page: beat indices, never a time
    assert page.evaluate("Woodshed.app.store.get().playing") is False  # Space tapped, never played
    page.get_by_test_id("toast-action").click()  # one Undo: the whole layout
    expect(typed_row(page)).to_have_count(0)
    assert typed_entries(srv) == {}
    assert problems == []


def test_the_touch_button_taps_and_escape_leaves_with_the_lines_tapped(
    browser: Browser, library: Callable[[str], app.AppServer]
) -> None:
    srv = library("sections")
    problems: list[str] = []
    page = device(browser, srv, problems, size=(390, 844), has_touch=True, is_mobile=True)
    start_tapping(page)
    button = page.get_by_test_id("tap-button")
    expect(button).to_be_visible()
    box = button.bounding_box()
    assert box is not None and box["height"] >= 64 and box["width"] >= 300  # big, under the thumb
    want = []
    for beat in BEATS[:2]:
        want.append(at_beat(page, beat))
        button.tap()
    expect(page.get_by_test_id("tap-count")).to_have_text("Line 3 of 3")
    page.keyboard.press("Escape")
    expect(page.get_by_test_id("tap-along")).to_be_hidden()
    expect(page.get_by_test_id("toast")).to_contain_text("2 lines laid by tapping along")
    expect(page.get_by_test_id("toast")).to_contain_text("1 line not laid")
    assert laid_ats(srv) == want
    assert problems == []


def test_escape_before_any_tap_leaves_and_lays_nothing(
    browser: Browser, library: Callable[[str], app.AppServer]
) -> None:
    srv = library("sections")
    problems: list[str] = []
    page = device(browser, srv, problems)
    start_tapping(page)
    page.keyboard.press("Escape")
    expect(page.get_by_test_id("tap-along")).to_be_hidden()
    assert typed_entries(srv) == {}
    assert problems == []


def test_laying_again_replaces_the_last_layout(browser: Browser, library: Callable[[str], app.AppServer]) -> None:
    srv = library("sections")
    problems: list[str] = []
    page = device(browser, srv, problems)
    start_tapping(page, "one two three\nfour five six")
    for beat in (4, 12):
        at_beat(page, beat)
        page.keyboard.press("Space")
    expect(typed_row(page)).to_have_count(2)
    open_words(page)
    expect(page.get_by_test_id("words-replaces")).to_have_text("Replaces the 2 lines you laid by tapping along.")
    page.get_by_test_id("words-close").click()
    start_tapping(page, "seven eight")
    at_beat(page, 20)
    page.keyboard.press("Space")
    expect(typed_row(page)).to_have_count(1)
    assert laid_ats(srv) == [20]
    assert problems == []


def test_the_dialog_offers_both_paths_with_their_licences(
    browser: Browser, library: Callable[[str], app.AppServer]
) -> None:
    srv = library("sections")
    problems: list[str] = []
    page = device(browser, srv, problems)
    open_words(page)
    tap, place = page.get_by_test_id("words-tap"), page.get_by_test_id("words-place")
    expect(tap).to_have_text("Lay them by tapping along")
    expect(place).to_have_text("Place them on the voice")
    expect(page.get_by_test_id("words-path-tap")).to_contain_text("No model, any language, free for any use")
    expect(page.get_by_test_id("words-path-voice")).to_contain_text("for non-commercial use only (CC BY-NC 4.0)")
    assert "primary" not in (tap.get_attribute("class") or "")  # equal weight while the model may be used
    assert "primary" not in (place.get_attribute("class") or "")
    page.get_by_test_id("words-close").click()
    page.get_by_test_id("words-open").click()  # the chart's toolbar opens the same dialog
    expect(page.get_by_test_id("words-tap")).to_be_visible()
    assert problems == []


def test_a_library_without_the_model_offers_only_tapping_along(
    browser: Browser, library: Callable[[str], app.AppServer]
) -> None:
    srv = library("sections")
    srv.library.words_model = False
    problems: list[str] = []
    page = device(browser, srv, problems)
    open_words(page)
    expect(page.get_by_test_id("words-place")).to_have_count(0)
    expect(page.get_by_test_id("words-path-voice")).to_have_count(0)
    expect(page.get_by_test_id("words-nomodel")).to_have_text(
        "This library does not use the speech model: paste the words, then tap along."
    )
    assert "primary" in (page.get_by_test_id("words-tap").get_attribute("class") or "")
    assert problems == []


def test_in_french(browser: Browser, library: Callable[[str], app.AppServer]) -> None:
    srv = library("sections")
    problems: list[str] = []
    page = device(browser, srv, problems, locale="fr-FR")
    open_words(page)
    expect(page.get_by_test_id("words-tap")).to_have_text("Les poser en tapant la mesure")
    expect(page.get_by_test_id("words-place")).to_have_text("Les placer sur la voix")
    page.get_by_test_id("words-text").fill("la la la\nli li li")
    page.get_by_test_id("words-tap").click()
    expect(page.get_by_test_id("tap-count")).to_have_text("Ligne 1 sur 2")
    until(page, "Woodshed.app.store.get().playing === true")
    page.evaluate("Woodshed.app.togglePlay()")
    at_beat(page, 4)
    page.keyboard.press("Space")
    page.keyboard.press("Escape")
    toast = page.get_by_test_id("toast")
    expect(toast).to_contain_text("1 ligne posée en tapant la mesure\u00a0: déplace un mot")
    expect(toast).to_contain_text("1 ligne non posée")
    assert problems == []
