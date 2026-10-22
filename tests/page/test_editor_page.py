"""The bar editor: Edit mode, typing a bar as on a chord sheet, the repeats, taking it back."""

from __future__ import annotations

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
    expect(page.locator('.bar[data-bar="1"]').first).to_have_attribute("aria-label", "Bar 2: D/F♯, G, typed by the band")


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
        " return s.groups.filter((x) => x.label === g.label).flatMap((x) => x.occurrences.map((l) => l[0])).filter((u) => u !== 0); })()"
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
    context = browser.new_context(viewport={"width": 390, "height": 844}, has_touch=True, is_mobile=True, locale="en-US")
    try:
        page = context.new_page()
        page.goto((built("pop", True, pages_root) / "index.html").as_uri())
        until(page, "window.Woodshed && window.Woodshed.ready === true")
        page.get_by_test_id("edit-chart").click()
        open_bar(page, 1)
        box = page.get_by_test_id("bar-editor").bounding_box()
        assert box and abs(box["x"]) < 1 and abs(box["width"] - 390) < 2  # the full width, at the bottom
        keys = page.locator(".ed .keys button")
        expect(keys).to_have_count(6)
        keys.first.click()  # ♯ typed into the field
        assert page.get_by_test_id("bar-field").input_value().endswith("#")
        for el in page.locator(".ed button, .edit-strip button").all():
            b = el.bounding_box()
            assert b and b["height"] >= 44, el.inner_text()
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
