"""Stage mode by touch: a tablet on the music stand or a phone has no keyboard, so the stage carries
its own big controls: play and pause, the previous and next part. The next song of the set is a
button too (test_band.py, it needs the library server)."""

from __future__ import annotations

import time
from typing import Any

import pytest
from playwright.sync_api import Browser, Page, expect

from tests.page.conftest import built
from tests.page.test_page import until


def wait(page: Page, expression: str, timeout: float = 5.0) -> None:
    """Polled from Python: the page's content security policy forbids Playwright's wait_for_function."""
    deadline = time.monotonic() + timeout
    while not page.evaluate(expression):
        if time.monotonic() > deadline:
            raise AssertionError(f"still false after {timeout} s: {expression}")
        page.wait_for_timeout(50)


def tablet(browser: Browser, pages_root: str) -> Page:
    context = browser.new_context(
        locale="en-US", viewport={"width": 820, "height": 1180}, device_scale_factor=2, has_touch=True, is_mobile=True
    )
    page = context.new_page()
    page.goto((built("pop", True, pages_root) / "index.html").as_uri())
    wait(page, "window.Woodshed && window.Woodshed.ready === true")
    return page


def on_top(page: Page, testid: str) -> bool:
    """The control is what a finger lands on at its centre: nothing covers it."""
    result: bool = page.get_by_test_id(testid).evaluate(
        "(el) => { const r = el.getBoundingClientRect();"
        " const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);"
        " return r.width >= 44 && r.height >= 44 && r.bottom <= innerHeight && !!hit && el.contains(hit); }"
    )
    return result


@pytest.mark.tablet
def test_stage_mode_plays_and_pauses_by_touch(browser: Browser, pages_root: str) -> None:
    page = tablet(browser, pages_root)
    page.get_by_test_id("stage-open").tap()
    expect(page.get_by_test_id("stage")).to_be_visible()
    for testid in ("stage-prev", "stage-play", "stage-next-part"):
        assert on_top(page, testid), testid
    page.get_by_test_id("stage-play").tap()
    wait(page, "Woodshed.debug().playing === true")
    expect(page.get_by_test_id("stage-play")).to_have_attribute("aria-label", "Pause")
    page.get_by_test_id("stage-play").tap()
    wait(page, "Woodshed.debug().playing === false")
    expect(page.get_by_test_id("stage-play")).to_have_attribute("aria-label", "Play")


def test_stage_mode_moves_part_by_part(open_page: Any) -> None:
    o = open_page("pop", variant="sections")  # Verse 1: bars 1 to 4, Chorus 1: bars 5 to 8
    beat = "Math.floor(Woodshed.app.store.get().beat / Woodshed.current.per)"
    o.page.get_by_test_id("stage-open").click()
    o.js("Woodshed.app.seekBar(2)")
    o.page.get_by_test_id("stage-next-part").click()
    assert o.js(beat) == 4
    expect(o.page.get_by_test_id("stage-section")).to_have_text("Chorus 1")
    o.js("Woodshed.app.seekBar(6)")
    o.page.get_by_test_id("stage-prev").click()  # inside a part: back to its start
    assert o.js(beat) == 4
    o.page.get_by_test_id("stage-prev").click()  # at its start: the part before
    assert o.js(beat) == 0
    o.page.get_by_test_id("stage-prev").click()  # nothing before the first part
    assert o.js(beat) == 0


def test_without_sections_the_stage_moves_a_line_at_a_time(open_page: Any) -> None:
    o = open_page("pop", variant="nosections")
    beat = "Math.floor(Woodshed.app.store.get().beat / Woodshed.current.per)"
    o.page.get_by_test_id("stage-open").click()
    o.js("Woodshed.app.seekBar(1)")
    o.page.get_by_test_id("stage-next-part").click()
    assert o.js(beat) == 4  # the next line of the chart: four bars


def test_a_pedal_after_a_tap_plays_instead_of_pressing_the_button_again(open_page: Any) -> None:
    o = open_page("pop", variant="sections")
    beat = "Math.floor(Woodshed.app.store.get().beat / Woodshed.current.per)"
    o.page.get_by_test_id("stage-open").click()
    o.page.get_by_test_id("stage-next-part").click()  # the button keeps the focus
    assert o.js(beat) == 4
    o.page.keyboard.press(" ")  # a page-turner pedal sends Space
    until(o, "Woodshed.debug().playing === true")
    assert o.js(beat) == 4  # no second jump


def test_previous_restarts_the_part_unless_it_has_just_begun(open_page: Any) -> None:
    o = open_page("pop", variant="sections")
    bar = "Math.floor(Woodshed.app.store.get().beat / Woodshed.current.per)"
    o.page.get_by_test_id("stage-open").click()
    o.js("Woodshed.app.store.set({ beat: 17 })")  # the second beat of the chorus's first bar
    o.page.get_by_test_id("stage-prev").click()
    assert o.js(bar) == 4  # back to the chorus, not to the verse


def test_a_phone_held_sideways_keeps_the_controls_on_screen(browser: Browser, pages_root: str) -> None:
    context = browser.new_context(
        locale="en-US", viewport={"width": 844, "height": 390}, device_scale_factor=3, has_touch=True, is_mobile=True
    )
    page = context.new_page()
    page.goto((built("pop", True, pages_root) / "index.html").as_uri())
    wait(page, "window.Woodshed && window.Woodshed.ready === true")
    page.get_by_test_id("stage-open").tap()
    for testid in ("stage-prev", "stage-play", "stage-next-part"):
        assert on_top(page, testid), testid
    assert page.evaluate("document.getElementById('stage').scrollHeight <= innerHeight")


def test_on_a_laptop_screen_the_stage_fits_and_has_its_own_theme_button(open_page: Any) -> None:
    o = open_page("pop")
    o.page.set_viewport_size({"width": 1366, "height": 768})
    # Without full screen: headless Firefox sometimes gives it the whole virtual desktop.
    o.js("Woodshed.app.setStage(true, false)")
    play = o.page.get_by_test_id("stage-play").bounding_box()
    assert play is not None and play["y"] + play["height"] <= 768  # the controls on screen, nothing below
    theme = o.js("document.documentElement.dataset.theme")
    o.page.get_by_test_id("stage-theme").click()  # a bright room: no need to leave the stage
    assert o.js("document.documentElement.dataset.theme") != theme
    assert " ".join(o.page.get_by_test_id("stage-exit").inner_text().split()) == "Exit stage mode (Esc)"


def test_a_touch_screen_is_not_told_about_the_escape_key(browser: Browser, pages_root: str) -> None:
    page = tablet(browser, pages_root)
    page.get_by_test_id("stage-open").click()
    assert " ".join(page.get_by_test_id("stage-exit").inner_text().split()) == "Exit stage mode"  # as shown
    page.context.close()


@pytest.mark.parametrize("words", [True, False])
@pytest.mark.parametrize("size", [(1366, 768), (1600, 900), (1280, 800)])
def test_the_guitar_shapes_on_the_stand_leave_room_for_the_next_chords(
    open_page: Any, size: tuple[int, int], words: bool
) -> None:
    o = open_page("pop", variant="lyrics") if words else open_page("pop")
    o.page.set_viewport_size({"width": size[0], "height": size[1]})
    o.page.get_by_test_id("inst-guitar").click()
    o.js("Woodshed.app.seekBar(1)")
    o.js("Woodshed.app.setStage(true, false)")  # headless full screen would take the whole desktop
    expect(o.page.get_by_test_id("stage-shapes")).to_be_visible()
    mid = o.js("document.querySelector('.stage-mid').getBoundingClientRect().bottom")
    for part in ("stNow", "stShape", "stNext", "stThen"):
        bottom = o.js(f"document.getElementById('{part}').getBoundingClientRect().bottom")
        assert bottom <= mid + 1, f"{part} cut at {size}: {bottom} > {mid}"
