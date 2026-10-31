"""The focus follows the musician (spec 025): the page comes to the bar the keyboard moved to, the keyboard stays on
the button it pressed (an instrument, a step, Edit the chart, Stage mode and back), a segmented button says it is
pressed, and the arrows start from the bar the musician is on. Spec 021's pedal rules hold: after a click or a tap
the pedal plays and seeks, and the page never scrolls back from where the musician reads ahead. The pedal guards
are marked `tablet` and also run in WebKit (an iPad with a pedal)."""

from __future__ import annotations

from typing import Any

import pytest
from playwright.sync_api import expect

from tests.page.test_keyboard import FOCUSED, FOCUSED_BAR, bar, editing, playing, tab_to
from tests.page.test_page import until

CUR = "Math.floor(Woodshed.app.store.get().beat / Woodshed.current.per)"
# The calls of scrollIntoView on a bar of the grid, with their options.
SPY = """(() => {
  window.__siv = [];
  const real = Element.prototype.scrollIntoView;
  Element.prototype.scrollIntoView = function (opts) {
    if (this.matches && this.matches('#sheet .bar[data-group]')) window.__siv.push(opts === undefined ? null : opts);
    return real.apply(this, arguments);
  };
})()"""
# The focused element's box against the window less the player at the bottom.
BOX = """(() => {
  const r = document.activeElement.getBoundingClientRect();
  return { top: r.top, bottom: r.bottom, seen: window.innerHeight - document.getElementById('dock').offsetHeight };
})()"""
IN_SIGHT = (
    "(() => { const r = document.activeElement.getBoundingClientRect();"
    " return r.top >= 0 && r.bottom <= window.innerHeight - document.getElementById('dock').offsetHeight; })()"
)
# Every button of a segmented group whose pressed state says otherwise than its look.
MISMATCHED = """[...document.querySelectorAll('.seg-ctl[role=group] button')]
  .filter((b) => b.getAttribute('aria-pressed') !== String(b.classList.contains('on')))
  .map((b) => (b.dataset.testid || b.textContent) + ' ' + b.getAttribute('aria-pressed'))"""


def short_window(o: Any) -> None:
    o.page.set_viewport_size({"width": 1000, "height": 420})


def settled(o: Any) -> None:
    """Until a smooth scroll has stopped: the same scrollY over 150 ms."""
    y = None
    for _ in range(40):
        o.page.wait_for_timeout(150)
        now = o.js("window.scrollY")
        if now == y:
            return
        y = now


# R1: the focused bar comes into view when the keyboard moved it.


@pytest.mark.tablet
def test_a1_the_page_comes_to_the_bar_the_keyboard_moved_to(open_page: Any) -> None:
    o = open_page("bridge")  # three lines of the grid, the last one below a short window
    short_window(o)
    tab_to(o, "bar", "section-loop")
    o.page.keyboard.press("ArrowDown")
    o.page.keyboard.press("ArrowDown")
    assert o.js(FOCUSED_BAR) == 24
    until(o, IN_SIGHT)  # smooth: polled
    assert not playing(o)


def test_a2_brought_into_view_by_the_least_move_smooth_unless_reduced_or_held(open_page: Any) -> None:
    o = open_page("bridge")
    short_window(o)
    tab_to(o, "bar", "section-loop")
    o.js(SPY)
    o.page.keyboard.press("ArrowDown")
    calls = o.js("window.__siv")
    assert calls, "the bar the keyboard moved to was not brought into view"
    assert calls[-1]["block"] == "nearest" and calls[-1]["inline"] == "nearest"
    assert calls[-1]["behavior"] == "smooth"
    # A held key repeats: no smooth scroll lagging behind the focus.
    o.js(
        "document.activeElement.dispatchEvent(new KeyboardEvent('keydown', "
        "{ key: 'ArrowUp', repeat: true, bubbles: true, cancelable: true }))"
    )
    assert o.js("window.__siv")[-1]["behavior"] == "auto"


def test_a2_reduced_motion_brings_the_bar_without_a_smooth_scroll(open_page: Any) -> None:
    o = open_page("bridge")
    o.page.emulate_media(reduced_motion="reduce")
    short_window(o)
    tab_to(o, "bar", "section-loop")
    o.js(SPY)
    o.page.keyboard.press("ArrowDown")
    calls = o.js("window.__siv")
    assert calls and calls[-1]["behavior"] == "auto"


@pytest.mark.tablet
def test_a3_in_edit_mode_a_bar_brought_into_view_keeps_a_margin(open_page: Any) -> None:
    o = open_page("bridge")
    short_window(o)
    editing(o)
    tab_to(o, "bar", "section-loop")
    o.page.keyboard.press("ArrowDown")
    o.page.keyboard.press("ArrowDown")
    assert o.js(FOCUSED_BAR) == 24
    until(o, f"(() => {{ const b = {BOX}; return b.bottom <= b.seen; }})()")  # never under the player
    o.page.keyboard.press("ArrowUp")
    o.page.keyboard.press("ArrowUp")
    assert o.js(FOCUSED_BAR) == 0
    # 12 px from the window's top (less sub-pixel rounding), never flush with it; polled: a smooth scroll may
    # start late on a loaded machine.
    until(o, f"(() => {{ const b = {BOX}; return b.top >= 11 && b.bottom <= b.seen; }})()")
    settled(o)
    box = o.js(BOX)
    assert box["top"] >= 11, box


@pytest.mark.tablet
@pytest.mark.parametrize("how", ["click", "focus"])  # focus: the page put it there (the check, on an iPad)
def test_a4_a_pedal_after_a_click_on_a_bar_never_scrolls_back_from_reading_ahead(open_page: Any, how: str) -> None:
    o = open_page("pop", variant="sections")
    short_window(o)
    getattr(bar(o, 0), how)()
    o.js("window.scrollTo(0, document.documentElement.scrollHeight)")  # reading ahead
    y = o.js("window.scrollY")
    assert y > 0
    o.page.keyboard.press("ArrowRight")  # the pedal
    expect(o.page.get_by_test_id("pass-info")).to_have_text("bar 2 of 4")
    o.page.keyboard.press("PageDown")
    expect(o.page.get_by_test_id("pass-info")).to_have_text("bar 3 of 4")
    o.page.wait_for_timeout(400)
    assert o.js("window.scrollY") == y
    assert o.js("document.activeElement === document.body") or o.js(FOCUSED_BAR) == 2  # WebKit: a click focuses no bar


def test_a5_while_the_song_plays_the_focus_helper_leaves_the_page_to_the_song(open_page: Any) -> None:
    o = open_page("bridge")
    short_window(o)
    tab_to(o, "bar", "section-loop")
    o.page.keyboard.press(" ")
    until(o, "Woodshed.debug().playing === true")
    o.js(SPY)
    o.page.keyboard.press("ArrowRight")
    o.page.wait_for_timeout(200)
    assert o.js("window.__siv") == []


# R2: the focus survives a redraw; R3: pressed states.


@pytest.mark.parametrize(
    ("testid", "start", "done"),
    [
        ("inst-bass", "theme", "Woodshed.app.store.get().inst === 'bass'"),
        ("step-2", "step-1", "Woodshed.app.store.get().step === 2"),
        ("voicing-barre", "voicing-open", "Woodshed.app.store.get().pos === 'barre'"),
    ],
)
def test_a6_space_on_a_redrawn_button_keeps_the_keyboard_on_it(
    open_page: Any, testid: str, start: str, done: str
) -> None:
    o = open_page("pop")
    tab_to(o, testid, start)
    o.page.keyboard.press(" ")
    until(o, done)
    assert o.js(FOCUSED) == testid
    assert not playing(o)
    if testid.startswith("inst-"):
        expect(o.page.get_by_test_id(testid)).to_have_attribute("aria-pressed", "true")


def test_a6_space_on_shapes_with_a_capo_keeps_the_keyboard_on_it(open_page: Any) -> None:
    o = open_page("pop")
    o.js("Woodshed.app.store.set({ capo: 2, view: 'concert' })")
    tab_to(o, "show-shapes", "show-concert")  # the switch is the chart row's first control (spec 031)
    o.page.keyboard.press(" ")
    until(o, "Woodshed.app.store.get().view === 'shapes'")
    assert o.js(FOCUSED) == "show-shapes"
    expect(o.page.get_by_test_id("show-shapes")).to_have_attribute("aria-pressed", "true")


def test_a7_after_space_on_keys_tab_goes_on_to_drums(open_page: Any) -> None:
    o = open_page("pop")
    tab_to(o, "inst-piano", "theme")
    o.page.keyboard.press(" ")
    until(o, "Woodshed.app.store.get().inst === 'piano'")
    o.page.keyboard.press("Tab")
    assert o.js(FOCUSED) == "inst-drums"


def test_a8_edit_the_chart_and_done_keep_the_keyboard_on_edit_the_chart(open_page: Any) -> None:
    o = open_page("pop")
    tab_to(o, "edit-chart", "words-open")
    edit = o.page.get_by_test_id("edit-chart")
    o.page.keyboard.press(" ")
    until(o, "Woodshed.app.store.get().editing === true")
    assert o.js(FOCUSED) == "edit-chart"
    expect(edit).to_have_attribute("aria-pressed", "true")
    o.page.keyboard.press(" ")
    until(o, "Woodshed.app.store.get().editing === false")
    assert o.js(FOCUSED) == "edit-chart"
    expect(edit).to_have_attribute("aria-pressed", "false")
    o.page.keyboard.press(" ")
    until(o, "Woodshed.app.store.get().editing === true")
    tab_to(o, "edit-done", "untype-all")
    o.page.keyboard.press(" ")
    until(o, "Woodshed.app.store.get().editing === false")
    assert o.js(FOCUSED) == "edit-chart"
    expect(edit).to_have_attribute("aria-pressed", "false")
    assert not playing(o)


@pytest.mark.tablet
def test_a9_the_stage_takes_the_keyboard_and_gives_it_back(open_page: Any) -> None:
    o = open_page("pop")
    tab_to(o, "stage-open", "export")
    o.page.keyboard.press(" ")
    expect(o.page.get_by_test_id("stage")).to_be_visible()
    assert o.js("document.activeElement.id") == "stage"
    expect(o.page.get_by_test_id("stage")).to_have_attribute("aria-label", "Stage mode")
    o.page.keyboard.press("Escape")
    expect(o.page.get_by_test_id("stage")).to_be_hidden()
    until(o, f"{FOCUSED} === 'stage-open'")  # once out of full screen
    o.js("Woodshed.app.seekBar(3)")
    bar(o, 3).focus()
    o.page.keyboard.press("s")
    expect(o.page.get_by_test_id("stage")).to_be_visible()
    assert o.js("document.activeElement.id") == "stage"
    o.page.keyboard.press("Escape")
    expect(o.page.get_by_test_id("stage")).to_be_hidden()
    until(o, f"{FOCUSED_BAR} === 3")


@pytest.mark.tablet
def test_a10_in_stage_a_pedal_seeks_and_plays_it_never_presses_exit(open_page: Any) -> None:
    o = open_page("pop")
    tab_to(o, "stage-open", "export")
    o.page.keyboard.press(" ")
    expect(o.page.get_by_test_id("stage")).to_be_visible()
    o.page.keyboard.press("ArrowRight")  # the pedal
    until(o, f"{CUR} === 1")
    o.page.keyboard.press(" ")
    until(o, "Woodshed.debug().playing === true")
    expect(o.page.get_by_test_id("stage")).to_be_visible()


@pytest.mark.tablet
@pytest.mark.parametrize("testid", ["edit-chart", "show-shapes"])
def test_a11_space_after_a_click_on_a_toggle_plays(open_page: Any, testid: str) -> None:
    o = open_page("pop")
    o.js("Woodshed.app.store.set({ capo: 2 })")
    o.page.get_by_test_id(testid).click()  # the mouse: the focus kept on the redrawn button, Space to the music
    state = o.js("JSON.stringify([Woodshed.app.store.get().editing, Woodshed.app.store.get().view])")
    o.page.keyboard.press(" ")
    until(o, "Woodshed.debug().playing === true")
    o.page.wait_for_timeout(200)  # Firefox clicks a focused button when Space is released
    assert o.js("JSON.stringify([Woodshed.app.store.get().editing, Woodshed.app.store.get().view])") == state


@pytest.mark.tablet
def test_a11_space_after_tapping_in_and_out_of_stage_plays(open_page: Any) -> None:
    o = open_page("pop")
    o.page.get_by_test_id("stage-open").click()
    expect(o.page.get_by_test_id("stage")).to_be_visible()
    o.page.get_by_test_id("stage-exit").click()
    expect(o.page.get_by_test_id("stage")).to_be_hidden()
    until(o, f"{FOCUSED} === 'stage-open'")  # given back once out of full screen, still the mouse's focus
    o.page.keyboard.press(" ")
    until(o, "Woodshed.debug().playing === true")
    o.page.wait_for_timeout(200)
    expect(o.page.get_by_test_id("stage")).to_be_hidden()


def test_a12_every_segmented_button_says_whether_it_is_pressed(open_page: Any) -> None:
    o = open_page("pop")
    assert o.js(MISMATCHED) == []
    expect(o.page.locator("#instruments")).to_match_aria_snapshot(
        '- group "I play":\n  - button "Guitar" [pressed]\n  - button "Bass"\n  - button "Keys"\n'
        '  - button "Drums"\n  - button "Voice"'
    )
    o.page.get_by_test_id("voicing-funk").click()
    o.js("Woodshed.app.store.set({ chordSound: 'piano', capo: 2, pos: 'open' })")
    assert o.js(MISMATCHED) == []
    o.page.get_by_test_id("inst-bass").click()
    assert o.js(MISMATCHED) == []
    expect(o.page.get_by_test_id("inst-bass")).to_have_attribute("aria-pressed", "true")
    expect(o.page.get_by_test_id("inst-guitar")).to_have_attribute("aria-pressed", "false")


# R6: the arrows start from the bar the musician is on.


def test_a13_stopped_the_arrows_start_from_the_focused_bar(open_page: Any) -> None:
    o = open_page("pop", variant="sections")  # two lines of four bars
    bar(o, 3).focus()  # put there by the page, as the check does; the song at bar 1
    assert o.js(CUR) == 0
    o.page.keyboard.press("ArrowRight")
    until(o, f"{CUR} === 4")
    assert o.js(FOCUSED_BAR) == 4
    tab_to(o, "bar", "section-loop")  # the keyboard's focus: Up and Down move a line
    o.js("Woodshed.app.seekBar(0)")
    bar(o, 2).focus()
    o.page.keyboard.press("ArrowDown")
    until(o, f"{CUR} === 6")
    assert o.js(FOCUSED_BAR) == 6


def test_a13_after_a_chord_picked_in_the_check_the_arrows_go_on_from_that_bar(open_page: Any) -> None:
    o = open_page("pickup", close_calls=True)
    o.js("Woodshed.app.seekBar(3)")
    o.page.get_by_test_id("doubt").first.click()  # the check, on bar 1
    expect(o.page.get_by_test_id("doubt-pop")).to_be_visible()
    o.page.get_by_test_id("pick-first").focus()
    o.page.keyboard.press("Enter")  # picked with the keyboard: the keyboard back on bar 1
    expect(o.page.get_by_test_id("doubt-pop")).to_be_hidden()
    assert o.js(FOCUSED_BAR) == 0
    o.page.keyboard.press("ArrowRight")
    until(o, f"{CUR} === 1")


@pytest.mark.tablet
@pytest.mark.parametrize("how", ["click", "focus"])  # focus: a bar focused by the page, as on an iPad
def test_a15_a_pedal_after_play_and_pause_goes_on_from_where_the_music_stopped(open_page: Any, how: str) -> None:
    o = open_page("pop", variant="sections")  # two parts: bar 1 stays drawn while the second one plays
    getattr(bar(o, 1), how)()
    o.page.keyboard.press(" ")  # the pedal plays
    until(o, "Woodshed.debug().playing === true")
    o.js("Woodshed.app.seekBar(4)")  # the music moves on, into the second part
    o.page.keyboard.press(" ")  # and pauses
    until(o, "Woodshed.app.store.get().playing === false")
    stopped = o.js(CUR)
    assert 4 <= stopped < 7
    o.page.keyboard.press("ArrowRight")
    until(o, f"{CUR} === {stopped + 1}")


def test_a16_while_the_song_plays_the_focus_stays_put(open_page: Any) -> None:
    o = open_page("pop", variant="sections")
    tab_to(o, "bar", "section-loop")
    o.page.keyboard.press(" ")
    until(o, "Woodshed.debug().playing === true")
    o.js("Woodshed.app.seekBar(5)")
    until(o, f"{CUR} >= 5")
    o.page.wait_for_timeout(200)
    assert o.js(FOCUSED_BAR) == 0  # a screen reader would read every bar over the music


@pytest.mark.tablet
def test_a15_out_of_the_stage_the_pedal_goes_on_from_where_the_music_stopped(open_page: Any) -> None:
    o = open_page("pop", variant="sections")
    bar(o, 2).focus()  # the page put it there (the check); a tap on Stage mode takes no focus on an iPad
    o.page.keyboard.press("s")
    expect(o.page.get_by_test_id("stage")).to_be_visible()
    o.page.keyboard.press(" ")  # the pedal plays
    until(o, "Woodshed.debug().playing === true")
    o.js("Woodshed.app.seekBar(4)")  # the music moves on, into the second part
    o.page.keyboard.press(" ")  # and pauses
    until(o, "Woodshed.app.store.get().playing === false")
    stopped = o.js(CUR)
    assert 4 <= stopped < 7
    o.page.keyboard.press("Escape")
    expect(o.page.get_by_test_id("stage")).to_be_hidden()
    until(o, f"{FOCUSED_BAR} === {stopped}")  # the keyboard back on the bar where the music stopped, not bar 3
    o.page.keyboard.press("ArrowRight")
    until(o, f"{CUR} === {stopped + 1}")


# Review of PR #45: a view control with the focus is not drawn again, nor focused again, as the passes go by
# while the song plays (a screen reader would announce it over the music).


@pytest.mark.parametrize("song", ["pop", "lift"])
def test_the_focused_view_control_is_left_alone_while_the_song_plays(open_page: Any, song: str) -> None:
    o = open_page(song)
    tab_to(o, "edit-chart", "words-open")
    o.js(
        "(() => { window.__fi = 0; window.__mut = 0; const v = document.getElementById('viewCtl');"
        " v.addEventListener('focusin', () => window.__fi++);"
        " new MutationObserver(() => window.__mut++).observe(v, { childList: true, subtree: true });"
        " window.__btn = document.querySelector('[data-testid=edit-chart]'); })()"
    )
    o.js("Woodshed.app.togglePlay()")
    until(o, "Woodshed.debug().playing === true")
    for u in (4, 9, 17, 25):  # other passes, and past the key change on lift
        o.js(f"Woodshed.app.seekBar(Math.min({u}, Woodshed.current.bars.length - 1))")
        o.page.wait_for_timeout(150)
    assert o.js("window.__fi") == 0
    assert o.js("window.__mut") == 0
    assert o.js("document.activeElement === window.__btn")
