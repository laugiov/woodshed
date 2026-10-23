"""The keyboard does what it says (spec 021): Space presses a button reached with Tab and plays everywhere else (a
page-turner pedal sends Space), the bars of the chart are one tab stop moved with the arrows, Enter saves the bar
being typed, the focus never falls to the page after a change."""

from __future__ import annotations

from typing import Any

import pytest
from playwright.sync_api import expect

from tests.page.test_page import until

FOCUSED = "document.activeElement && document.activeElement.dataset ? document.activeElement.dataset.testid : null"
FOCUSED_BAR = "document.activeElement.classList.contains('bar') ? +document.activeElement.dataset.bar : null"
STOPS = "[...document.querySelectorAll('#sheet .bar[data-testid=bar]')].filter((b) => b.tabIndex >= 0).length"


def playing(o: Any) -> bool:
    return bool(o.js("Woodshed.app.store.get().playing"))


def bar(o: Any, u: int) -> Any:
    return o.page.locator(f'#sheet .bar[data-bar="{u}"]').first


def tab_to(o: Any, testid: str, start: str) -> None:
    """The keyboard on `testid` by Tab, from `start` (focused by the page, not by a key)."""
    o.page.get_by_test_id(start).first.focus()
    for _ in range(12):
        o.page.keyboard.press("Tab")
        if o.js(FOCUSED) == testid:
            return
    raise AssertionError(f"Tab never reached {testid}")


def editing(o: Any) -> Any:
    o.page.get_by_test_id("edit-chart").click()
    expect(o.page.get_by_test_id("edit-strip")).to_be_visible()
    return o.page


# R1: Space. Also run in WebKit (`tablet`): an iPad with a pedal is the main pedal setup.


@pytest.mark.tablet
def test_space_presses_a_button_reached_with_tab_and_does_not_play(open_page: Any) -> None:
    o = open_page("pop")
    tab_to(o, "trainer", "loop")
    o.page.keyboard.press(" ")
    until(o, "Woodshed.app.store.get().trainer === true")
    o.page.wait_for_timeout(200)
    assert not playing(o)  # the button, as everywhere else on the web


@pytest.mark.tablet
def test_space_plays_after_a_click_on_a_button(open_page: Any) -> None:
    o = open_page("pop")
    o.page.get_by_test_id("trainer").click()  # a click leaves the focus on Trainer (not in Safari)
    assert o.js("Woodshed.app.store.get().trainer") is True
    o.page.keyboard.press(" ")
    until(o, "Woodshed.debug().playing === true")
    assert o.js("Woodshed.app.store.get().trainer") is True  # Space played, it did not press Trainer again


@pytest.mark.tablet
def test_a_click_after_tab_gives_space_back_to_the_music(open_page: Any) -> None:
    o = open_page("pop")
    tab_to(o, "trainer", "loop")
    o.page.get_by_test_id("count-in").click()  # the mouse again
    count = o.js("Woodshed.app.store.get().countIn")
    o.page.keyboard.press(" ")
    until(o, "Woodshed.app.store.get().playing === true || Woodshed.debug().playing === true")
    assert o.js("Woodshed.app.store.get().countIn") == count
    assert o.js("Woodshed.app.store.get().trainer") is False


@pytest.mark.tablet
def test_space_with_nothing_focused_plays(open_page: Any) -> None:
    o = open_page("pop")
    assert o.js("document.activeElement === document.body")
    o.page.keyboard.press(" ")  # the pedal
    until(o, "Woodshed.debug().playing === true")


@pytest.mark.tablet
def test_space_on_a_bar_reached_with_tab_plays(open_page: Any) -> None:
    o = open_page("pop")
    tab_to(o, "bar", "section-loop")
    o.page.keyboard.press(" ")
    until(o, "Woodshed.debug().playing === true")


@pytest.mark.tablet
def test_a_pedal_seeks_after_a_click_on_a_bar(open_page: Any) -> None:
    o = open_page("pop")
    bar(o, 1).click()
    expect(o.page.get_by_test_id("pass-info")).to_have_text("bar 2 of 8")
    o.page.keyboard.press("ArrowRight")  # a pedal
    expect(o.page.get_by_test_id("pass-info")).to_have_text("bar 3 of 8")
    o.page.keyboard.press("PageDown")
    expect(o.page.get_by_test_id("pass-info")).to_have_text("bar 4 of 8")
    o.page.keyboard.press("PageUp")
    expect(o.page.get_by_test_id("pass-info")).to_have_text("bar 3 of 8")
    o.page.keyboard.press(" ")
    until(o, "Woodshed.debug().playing === true")


def test_the_help_says_what_space_does(open_page: Any) -> None:
    o = open_page("pop")
    o.page.get_by_test_id("help").click()
    help_menu = o.page.get_by_test_id("help-menu")
    expect(help_menu).to_contain_text("Play or pause (on a button reached with Tab: presses it)")
    expect(help_menu).to_contain_text("a pedal's Space presses it too")


# R2: the bars, one tab stop.


def test_in_edit_mode_the_bars_are_one_tab_stop_moved_with_the_arrows(open_page: Any) -> None:
    o = open_page("pop", variant="sections")  # two lines of four bars, a part each
    editing(o)
    assert o.js(STOPS) == 1
    tab_to(o, "bar", "section-loop")  # the first part's Loop, then its bars
    assert o.js(FOCUSED_BAR) == 0
    beat = o.js("Woodshed.app.store.get().beat")
    o.page.keyboard.press("ArrowRight")
    assert o.js(FOCUSED_BAR) == 1
    o.page.keyboard.press("ArrowDown")  # the line below, same place in it
    assert o.js(FOCUSED_BAR) == 5
    o.page.keyboard.press("End")  # the part's last bar
    assert o.js(FOCUSED_BAR) == 7
    o.page.keyboard.press("Home")
    assert o.js(FOCUSED_BAR) == 4
    o.page.keyboard.press("ArrowLeft")  # back over the line's start
    assert o.js(FOCUSED_BAR) == 3
    o.page.keyboard.press("ArrowUp")  # no line above: stays
    assert o.js(FOCUSED_BAR) == 3
    assert o.js("Woodshed.app.store.get().beat") == beat  # editing: the arrows move the keyboard, not the song
    assert o.js(STOPS) == 1
    o.js("Woodshed.app.store.set({corrections: Woodshed.app.store.get().corrections + 1})")  # drawn again
    assert o.js(FOCUSED_BAR) == 3
    assert o.js(STOPS) == 1
    o.page.keyboard.press("Tab")  # one Tab leaves the bars
    assert o.js("document.activeElement.classList.contains('bar')") is False
    o.page.keyboard.press("Shift+Tab")  # and comes back to the one in hand
    assert o.js(FOCUSED_BAR) == 3
    o.page.keyboard.press("Enter")
    expect(o.page.get_by_test_id("bar-editor")).to_contain_text("Bar 4")


def test_in_play_mode_the_arrows_seek_and_the_keyboard_follows_the_bar(open_page: Any) -> None:
    o = open_page("pop", variant="sections")
    assert o.js(STOPS) == 1
    o.js("Woodshed.app.seekBar(2)")
    assert o.js(STOPS) == 1
    assert o.js("[...document.querySelectorAll('#sheet .bar')].find((b) => b.tabIndex === 0).dataset.bar") == "2"
    tab_to(o, "bar", "section-loop")
    assert o.js(FOCUSED_BAR) == 2  # the bar playing
    o.page.keyboard.press("ArrowRight")
    expect(o.page.get_by_test_id("pass-info")).to_have_text("bar 4 of 4")
    assert o.js(FOCUSED_BAR) == 3
    o.page.keyboard.press("ArrowRight")  # into the next part
    expect(o.page.get_by_test_id("pass-info")).to_have_text("bar 1 of 4")
    assert o.js(FOCUSED_BAR) == 4
    o.page.keyboard.press("PageDown")  # a pedal, the keyboard there too
    assert o.js(FOCUSED_BAR) == 5
    o.page.keyboard.press("ArrowUp")
    assert o.js(FOCUSED_BAR) == 1
    assert o.js("Math.floor(Woodshed.app.store.get().beat / Woodshed.current.per)") == 1
    o.page.keyboard.press("ArrowLeft")
    o.page.keyboard.press("PageUp")
    assert o.js(FOCUSED_BAR) == 0
    assert o.js("Math.floor(Woodshed.app.store.get().beat / Woodshed.current.per)") == 0


def test_the_chart_is_a_named_group_saying_how_to_move(open_page: Any) -> None:
    o = open_page("pop")
    sheet = o.page.get_by_test_id("sheet")
    expect(sheet).to_have_attribute("role", "group")
    expect(sheet).to_have_attribute("aria-label", "Chart")
    expect(sheet).to_have_accessible_description("In the chart, the arrows move between bars and Enter opens one.")
    expect(o.page.locator("#sheetKeys")).to_be_hidden()  # said once, as the chart's description


# R3: the bar editor.


def test_enter_saves_the_bar_and_gives_the_keyboard_back_to_it(open_page: Any) -> None:
    o = open_page("pop")
    page = editing(o)
    bar(o, 1).click()
    page.get_by_test_id("bar-field").fill("Am")
    page.get_by_test_id("bar-field").press("Enter")
    expect(page.get_by_test_id("bar-editor")).to_be_hidden()
    assert o.js("Woodshed.app.typedBar(1)") is not None
    assert o.js(FOCUSED_BAR) == 1


def test_ctrl_enter_saves_and_opens_the_next_bar(open_page: Any) -> None:
    o = open_page("pop")
    page = editing(o)
    bar(o, 1).click()
    page.get_by_test_id("bar-field").fill("Am")
    page.get_by_test_id("bar-field").press("Control+Enter")
    expect(page.get_by_test_id("bar-editor")).to_contain_text("Bar 3")
    assert o.js("Woodshed.app.typedBar(1)") is not None
    nxt = page.get_by_test_id("bar-save-next")
    expect(nxt).to_have_attribute("aria-keyshortcuts", "Control+Enter Meta+Enter")
    expect(nxt).to_have_attribute("title", "Ctrl+Enter")
    expect(page.get_by_test_id("bar-save")).to_have_attribute("title", "Enter")
    expect(page.get_by_test_id("bar-editor")).to_contain_text("Enter saves, Ctrl+Enter saves and opens the next bar.")
    page.get_by_test_id("bar-cancel").focus()
    page.keyboard.press("Control+Enter")  # anywhere in the dialog
    expect(page.get_by_test_id("bar-editor")).to_contain_text("Bar 4")


# R4: the focus after the band's chart is taken back.


def test_the_focus_stays_in_the_strip_after_the_global_reset_and_its_undo(open_page: Any) -> None:
    o = open_page("pop")
    page = editing(o)
    bar(o, 1).click()
    page.get_by_test_id("bar-field").fill("Am")
    page.get_by_test_id("bar-save").click()
    page.on("dialog", lambda d: d.accept())
    tab_to(o, "untype-all", "bar-lines")
    page.keyboard.press("Enter")
    until(o, "Woodshed.app.typedBar(1) === null || Woodshed.app.typedBar(1) === undefined")
    assert o.js(FOCUSED) == "untype-all"
    page.get_by_test_id("toast-action").click()  # Undo
    until(o, "!!Woodshed.app.typedBar(1)")
    assert o.js(FOCUSED) == "untype-all"


# R5: one control per bar.


def test_a_chord_to_check_is_not_a_button_inside_the_bar(open_page: Any) -> None:
    o = open_page("pickup", close_calls=True)
    assert o.page.locator("#sheet [role=button] button").count() == 0
    doubtful = o.page.locator("#sheet .bar", has=o.page.get_by_test_id("doubt")).first
    expect(doubtful).to_have_attribute("aria-label", "Bar 1: N.C., G, chord to check")
    o.js("Woodshed.app.seekBar(3)")
    doubtful.locator(".num").click()  # a click on the bar, beside the mark: it seeks
    assert o.js("Math.floor(Woodshed.app.store.get().beat / Woodshed.current.per)") == 0
    expect(o.page.get_by_test_id("doubt-pop")).to_be_hidden()
    o.page.get_by_test_id("doubt").first.click()  # the mark opens the check, as before
    expect(o.page.get_by_test_id("doubt-pop")).to_be_visible()
    o.page.get_by_test_id("pick").first.click()  # a correction
    expect(o.page.get_by_test_id("fixed").first).to_be_visible()
    assert o.page.locator("#sheet [role=button] button").count() == 0


def test_enter_on_a_bar_with_a_chord_to_check_seeks_and_opens_the_check(open_page: Any) -> None:
    o = open_page("pickup", close_calls=True)
    o.js("Woodshed.app.seekBar(3)")
    doubtful = o.page.locator("#sheet .bar", has=o.page.get_by_test_id("doubt")).first
    doubtful.focus()
    o.page.keyboard.press("Enter")
    expect(o.page.get_by_test_id("doubt-pop")).to_be_visible()
    assert o.js("Math.floor(Woodshed.app.store.get().beat / Woodshed.current.per)") == 0
    expect(o.page.get_by_test_id("pick-first")).to_be_focused()
    o.page.keyboard.press("Escape")
    expect(o.page.get_by_test_id("doubt-pop")).to_be_hidden()
    assert o.js(FOCUSED_BAR) == 0  # back on the bar


def test_in_edit_mode_enter_on_a_bar_to_check_opens_its_editor_with_the_candidates(open_page: Any) -> None:
    o = open_page("pickup", close_calls=True)
    editing(o)
    o.page.locator("#sheet .bar", has=o.page.get_by_test_id("doubt")).first.focus()
    o.page.keyboard.press("Enter")
    expect(o.page.get_by_test_id("bar-candidates")).to_be_visible()
    expect(o.page.get_by_test_id("doubt-pop")).to_be_hidden()
