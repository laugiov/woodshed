"""The bar editor: Edit mode, typing a bar as on a chord sheet, the repeats, taking it back."""

from __future__ import annotations

import re
from typing import Any

from playwright.sync_api import expect

from tests.page.conftest import built
from tests.page.test_band import until

BAR = "(u) => Woodshed.current.bars[u].chords.map((c) => Woodshed.chords.key(c) + 'x' + c.beats).join()"


def editing(o: Any) -> Any:
    o.page.get_by_test_id("edit-chart").click()
    expect(o.page.get_by_test_id("edit-strip")).to_be_visible()
    return o.page


def open_bar(page: Any, u: int) -> Any:
    page.locator(f'.bar[data-bar="{u}"]').first.click()
    editor = page.get_by_test_id("bar-editor")
    expect(editor).to_be_visible()
    return editor


def test_a_bar_is_typed_as_on_a_chord_sheet_and_the_next_one_follows(open_page: Any) -> None:
    o = open_page("pop")
    page = editing(o)
    editor = open_bar(page, 1)
    field = page.get_by_test_id("bar-field")
    expect(field).to_be_focused()
    field.fill("D/F# . G .")
    expect(page.get_by_test_id("bar-reading")).to_have_text("D/F♯ for 2 beats, F♯ in the bass, then G for 2")
    field.press("Enter")  # save, then the next bar
    assert o.js(f"({BAR})(1)") == "2||6x2,7||x2"
    expect(editor).to_contain_text("Bar 3")
    page.get_by_test_id("bar-field").fill("%")  # the bar before
    page.get_by_test_id("bar-save").click()
    assert o.js(f"({BAR})(2)") == "2||6x2,7||x2"
    expect(editor).to_be_hidden()
    expect(page.locator('.bar[data-bar="1"]').first).to_have_class("bar edited")
    expect(page.locator('.bar[data-bar="1"]').first).to_have_attribute(
        "aria-label", "Bar 2: D/F♯, G, typed by the band"
    )


def test_a_chord_that_cannot_be_drawn_says_why_and_saves_nothing(open_page: Any) -> None:
    o = open_page("pop")
    page = editing(o)
    before = o.js(f"({BAR})(1)")
    open_bar(page, 1)
    page.get_by_test_id("bar-field").fill("Cmaj . . .")
    expect(page.get_by_test_id("bar-reading")).to_have_text("Cmaj: Cmaj7 or C?")
    expect(page.get_by_test_id("bar-field")).to_have_attribute("aria-invalid", "true")
    page.get_by_test_id("bar-save").click()
    assert o.js(f"({BAR})(1)") == before  # nothing saved, the editor stays
    expect(page.get_by_test_id("bar-editor")).to_be_visible()


def test_space_and_escape_belong_to_the_editor(open_page: Any) -> None:
    o = open_page("pop")
    page = editing(o)
    open_bar(page, 1)
    page.get_by_test_id("bar-field").press("End")
    page.keyboard.type(" Am")  # a space typed in the field does not play the song
    assert o.js("Woodshed.debug().playing") is False
    page.keyboard.press("Escape")
    expect(page.get_by_test_id("bar-editor")).to_be_hidden()
    expect(page.locator('.bar[data-bar="1"]').first).to_be_focused()  # the keyboard back on the bar


def test_the_same_bar_where_the_line_comes_back_is_typed_too(open_page: Any) -> None:
    o = open_page("pop")
    page = editing(o)
    repeats = o.js(
        "(() => { const s = Woodshed.current.song; const b = s.bars[0]; const g = s.groups[b.group];"
        " const firsts = s.groups.filter((x) => x.label === g.label).flatMap((x) => x.occurrences.map((l) => l[0]));"
        " return firsts.filter((u) => u !== 0); })()"
    )
    assert repeats, "pop plays its first line again"
    open_bar(page, 0)
    expect(page.get_by_test_id("bar-also")).to_be_checked()
    page.get_by_test_id("bar-field").fill("Asus4")
    page.get_by_test_id("bar-save").click()
    for u in [0, *repeats]:
        assert o.js(f"({BAR})({u})") == "9|sus4|x4", u


def test_a_typed_bar_goes_back_to_the_analysis_alone_or_with_everything(open_page: Any) -> None:
    o = open_page("pop")
    page = editing(o)
    before = [o.js(f"({BAR})({u})") for u in (1, 2)]
    o.js("Woodshed.app.typeBars([1], [[4, 'Dsus4']]); Woodshed.app.typeBars([2], [[4, 'Em7']])")
    open_bar(page, 1)
    page.get_by_test_id("bar-untype").click()
    assert o.js(f"({BAR})(1)") == before[0]
    page.once("dialog", lambda d: d.accept())
    page.get_by_test_id("untype-all").click()
    assert o.js(f"({BAR})(2)") == before[1]
    page.get_by_test_id("toast-action").click()  # Undo
    assert o.js(f"({BAR})(2)") == "4|m7|x4"


def test_in_edit_mode_a_chord_to_check_opens_the_editor_with_its_candidates(open_page: Any) -> None:
    o = open_page("pickup", close_calls=True)
    page = editing(o)
    page.get_by_test_id("doubt").first.click()
    expect(page.get_by_test_id("bar-editor")).to_be_visible()
    expect(page.get_by_test_id("doubt-pop")).to_be_hidden()
    candidates = page.get_by_test_id("bar-candidate")
    expect(candidates.first).to_be_visible()
    candidates.nth(1).click()  # fills the doubt's beats
    expect(page.get_by_test_id("bar-reading")).not_to_have_text("")


def test_the_capo_rule_in_the_page_is_the_library_s(open_page: Any) -> None:
    for name in ("pop", "waltz", "pickup"):
        o = open_page(name)
        assert o.js("[...Array(12).keys()].map((t) => Woodshed.current.suggestCapo(t))") == o.js(
            "Woodshed.current.view.transpositions.map((x) => x.capo)"
        ), name


def test_on_a_phone_the_editor_is_a_sheet_with_the_signs_a_phone_keyboard_lacks(browser: Any, pages_root: str) -> None:
    context = browser.new_context(
        viewport={"width": 390, "height": 844}, has_touch=True, is_mobile=True, locale="en-US"
    )
    try:
        page = context.new_page()
        page.goto((built("pop", True, pages_root) / "index.html").as_uri())
        until(page, "window.Woodshed && window.Woodshed.ready === true")
        page.get_by_test_id("edit-chart").click()
        open_bar(page, 1)
        box = page.get_by_test_id("bar-editor").bounding_box()
        assert box and abs(box["x"]) < 1 and abs(box["width"] - 390) < 2  # the full width, at the bottom
        bar = page.locator('.bar[data-bar="1"]').first.bounding_box()
        assert bar and bar["y"] >= 0 and bar["y"] + bar["height"] <= box["y"]  # the bar in sight, above the sheet
        keys = page.locator(".ed .keys button")
        expect(keys).to_have_count(6)
        keys.first.click()  # ♯ typed into the field
        assert page.get_by_test_id("bar-field").input_value().endswith("#")
        for el in page.locator(".ed button, .edit-strip button").all():
            b = el.bounding_box()
            assert b and b["height"] >= 43.5, el.inner_text()  # 44 px, give or take a rounding
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    finally:
        context.close()


def test_the_editor_speaks_french(open_page: Any) -> None:
    o = open_page("pop")
    page = o.page
    page.get_by_test_id("lang-fr").click()
    page.get_by_test_id("edit-chart").click()
    expect(page.get_by_test_id("edit-strip")).to_contain_text("Modification de la grille")
    open_bar(page, 1)
    page.get_by_test_id("bar-field").fill("D/F# . G .")
    expect(page.get_by_test_id("bar-reading")).to_have_text("D/F♯ sur 2 temps, F♯ à la basse, puis G sur 2")


def test_a_long_numeral_never_covers_the_bar_number(browser: Any, pages_root: str) -> None:
    context = browser.new_context(
        viewport={"width": 390, "height": 844}, has_touch=True, is_mobile=True, locale="en-US"
    )
    try:
        page = context.new_page()
        page.goto((built("pop", True, pages_root) / "index.html").as_uri())
        until(page, "window.Woodshed && window.Woodshed.ready === true")
        page.evaluate("Woodshed.app.typeBars([2], [[2, 'Dsus4'], [2, 'D/F#']])")
        bar = page.locator('.bar[data-bar="2"]').first
        num = bar.locator(".num").bounding_box()
        rn = bar.locator(".rn").bounding_box()
        assert num and rn and rn["x"] >= num["x"] + num["width"]  # side by side, never over it
    finally:
        context.close()


def test_on_a_transposed_page_the_bar_is_typed_in_the_key_on_screen(open_page: Any) -> None:
    o = open_page("pop")
    o.js("Woodshed.app.transposeTo(2)")  # the band plays it a tone up
    before = o.js(f"({BAR})(1)")
    page = editing(o)
    open_bar(page, 1)
    page.get_by_test_id("bar-field").press("Enter")  # saved as shown: the bar does not move
    assert o.js(f"({BAR})(1)") == before
    open_bar(page, 1)
    page.get_by_test_id("bar-field").fill("A")  # A on screen, a tone up: G in the recording
    page.get_by_test_id("bar-save").click()
    assert o.js(f"({BAR})(1)") == "7||x4"
    expect(page.locator('.bar[data-bar="1"]').first).to_contain_text("A")


def test_the_editor_s_buttons_keep_their_keys(open_page: Any) -> None:
    o = open_page("pop")
    page = editing(o)
    open_bar(page, 1)
    page.get_by_test_id("bar-save").focus()
    page.keyboard.press("Space")  # presses Save, does not play the song
    assert o.js("Woodshed.debug().playing") is False
    expect(page.get_by_test_id("bar-editor")).to_be_hidden()
    expect(page.locator('.bar[data-bar="1"]').first).to_be_focused()  # the keyboard back on the bar


def test_stage_mode_closes_the_editor(open_page: Any) -> None:
    o = open_page("pop")
    page = editing(o)
    open_bar(page, 1)
    o.js("Woodshed.app.setStage(true)")
    expect(page.get_by_test_id("bar-editor")).to_be_hidden()


def test_a_typed_span_over_a_bar_line_goes_back_from_either_bar(open_page: Any) -> None:
    o = open_page("pop")
    first, per = o.js("[Woodshed.current.song.first_beat, Woodshed.current.per]")
    o.js(f"Woodshed.app.typedBars.set('{first + per + 2}', {{chords: [[4, 'E']], t: 1}})")  # as after a bar-line move
    o.js("Woodshed.app.typeBars([], [])")  # draws the chart again
    assert o.js("[Woodshed.current.bars[1].edited, Woodshed.current.bars[2].edited]") == [True, True]
    o.js("Woodshed.app.untypeBar(2)")
    assert o.js("[Woodshed.current.bars[1].edited, Woodshed.current.bars[2].edited]") == [False, False]


def test_undo_puts_back_only_what_nobody_typed_again(open_page: Any) -> None:
    o = open_page("pop")
    page = editing(o)
    o.js("Woodshed.app.typeBars([1], [[4, 'Dsus4']]); Woodshed.app.typeBars([2], [[4, 'Em7']])")
    page.once("dialog", lambda d: d.accept())
    page.get_by_test_id("untype-all").click()
    o.js("Woodshed.app.typeBars([2], [[4, 'E']])")  # a newer change, as from the band
    page.get_by_test_id("toast-action").click()  # Undo
    assert o.js(f"({BAR})(1)") == "2|sus4|x4" and o.js(f"({BAR})(2)") == "4||x4"


def test_this_bar_held_down_loops_it_until_released(open_page: Any) -> None:
    o = open_page("pop")
    page = editing(o)
    open_bar(page, 1)
    box = page.get_by_test_id("bar-play").bounding_box()
    assert box
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    page.mouse.down()
    page.wait_for_timeout(700)
    assert o.js("[Woodshed.app.store.get().loop, Woodshed.app.store.get().loopOn]") == [[1, 1], True]
    page.mouse.up()
    assert o.js("[Woodshed.app.store.get().loop, Woodshed.app.store.get().loopOn, Woodshed.debug().playing]") == [
        None,
        False,
        False,
    ]


def test_the_chart_is_not_edited_while_the_full_analysis_is_coming(open_page: Any) -> None:
    o = open_page("pop")
    o.js("Woodshed.current.view.pending = true; Woodshed.app.store.set({ inst: 'bass' })")  # a mix-only page
    button = o.page.get_by_test_id("edit-chart")
    expect(button).to_be_disabled()
    expect(button).to_have_attribute("title", re.compile("the full analysis may move the beats"))
