"""Splitting a line and joining two lines of the words on the sheet (spec 028 B), in the page: Shift+Enter or
"Split at the cursor" breaks a line, "Join with the next line" makes two lines one; the library places them in
the line's window, the band sees them, Undo and "Back to the placement" take back the whole split or join."""

from __future__ import annotations

import json
import re
from typing import Any

from playwright.sync_api import Browser, Page, expect

from tests.page.test_edit_a_line import chordpro, device, edit, line, open_line, served, until  # noqa: F401
from woodshed import app, exports, lyrics

FIRST = "Morning comes in on the harbour road,"


def seeks_of(page: Page, i: int) -> list[str]:
    found: list[str] = page.evaluate(
        f"[...document.querySelectorAll('#sheet .lline[data-index=\"{i}\"] [data-seek]')]"
        ".map((e) => e.getAttribute('data-seek'))"
    )
    return found


def caret_before(page: Page, word: str) -> None:
    """The cursor put in the field just before `word`, as a finger or the arrows would."""
    page.get_by_test_id("line-field").evaluate(
        "(f, w) => { const at = f.value.indexOf(w); f.focus(); f.setSelectionRange(at, at); }", word
    )


def words(row: Any) -> str:
    """A row's words as sung, without the chords drawn among them."""
    found: str = row.evaluate("(el) => [...el.querySelectorAll('.lw .wt')].map((w) => w.textContent).join(' ')")
    return found


def field_value(page: Page) -> str:
    value: str = page.get_by_test_id("line-field").input_value()
    return value


def stored_lines(srv: app.AppServer) -> dict[str, Any]:
    folder = srv.library.root / "Pop.woodshed"
    data = json.loads((folder / lyrics.LYRICS).read_text(encoding="utf-8"))
    words = srv.library.corrections("Pop.woodshed", "a1b2c3", None, lyrics.words_key(data))["words"]
    got: dict[str, Any] = words["lines"]
    return got


# A20: split at a word, join with the next line, Undo of the whole.


def test_a_line_split_at_a_word_shows_as_two_rows_and_undo_makes_it_one(
    browser: Browser,
    served: app.AppServer,  # noqa: F811
) -> None:
    problems: list[str] = []
    page = device(browser, served, problems)
    posts: list[str] = []
    page.on(
        "request", lambda r: posts.append(r.post_data or "") if r.method == "POST" and "/api/words" in r.url else None
    )
    edit(page)
    after = seeks_of(page, 1)
    open_line(page, 0, "harbour")
    caret_before(page, "the harbour")
    page.get_by_test_id("line-split").click()
    assert field_value(page) == "Morning comes in on\nthe harbour road,"
    expect(page.get_by_test_id("line-field")).to_be_focused()  # typed on at once
    page.get_by_test_id("line-save").click()
    expect(page.get_by_test_id("line-editor")).to_be_hidden(timeout=20000)
    rows = line(page, 0)
    expect(rows).to_have_count(2)  # one line of the placement, two rows of the sheet
    assert words(rows.nth(0)) == "Morning comes in on" and words(rows.nth(1)) == "the harbour road,"
    assert seeks_of(page, 1) == after  # the next line did not move
    assert len(posts) == 1 and json.loads(posts[0])["lines"] == {
        "0": {"text": "Morning comes in on\nthe harbour road,"}
    }
    assert [p["text"] for p in stored_lines(served)["0"]["lines"]] == ["Morning comes in on", "the harbour road,"]
    page.get_by_test_id("toast-action").click()  # Undo: one line again
    expect(line(page, 0)).to_have_count(1)
    assert words(line(page, 0)) == FIRST + " yes"  # as placed
    assert stored_lines(served) == {}
    assert problems == []


def test_two_lines_joined_are_one_and_back_to_the_placement_brings_both(
    browser: Browser,
    served: app.AppServer,  # noqa: F811
) -> None:
    problems: list[str] = []
    page = device(browser, served, problems)
    edit(page)
    open_line(page, 0)
    page.get_by_test_id("line-join").click()
    expect(page.get_by_test_id("line-editor")).to_be_hidden(timeout=20000)
    assert words(line(page, 0)) == FIRST + " the radio hums"
    expect(line(page, 1)).to_have_count(0)
    joined = page.get_by_test_id("line-joined-row")
    expect(joined).to_have_count(1)  # in Edit mode: the line it holds, where it was
    expect(joined).to_contain_text("joined into line 1")
    expect(page.get_by_test_id("toast")).to_contain_text("joined")
    entries = stored_lines(served)
    assert entries["1"] == {"was": "the radio hums", "gone": "joined"}
    page.get_by_test_id("edit-done").click()
    expect(page.get_by_test_id("line-joined-row")).to_have_count(0)
    expect(page.get_by_test_id("lyric-line")).to_have_count(1)
    page.get_by_test_id("edit-chart").click()
    page.get_by_test_id("line-joined-back").click()  # Back to the placement, from the row: both lines again
    expect(line(page, 1)).to_contain_text("radio")
    expect(line(page, 0)).not_to_contain_text("radio")
    assert stored_lines(served) == {}
    page.get_by_test_id("toast-action").click()  # Undo of that: joined again
    expect(page.get_by_test_id("line-joined-row")).to_have_count(1)
    assert problems == []


def test_join_is_offered_only_with_a_sung_line_of_the_same_part(
    browser: Browser,
    served: app.AppServer,  # noqa: F811
) -> None:
    problems: list[str] = []
    page = device(browser, served, problems)
    edit(page)
    open_line(page, 1, "radio")  # the last sung line: nothing after it to join
    expect(page.get_by_test_id("line-join")).to_have_count(0)
    expect(page.get_by_test_id("line-split")).to_be_visible()
    page.keyboard.press("Escape")
    open_line(page, 0)
    field = page.get_by_test_id("line-field")
    no_room = {"error": "not enough time for these words between 0:00 and 0:08", "window": [0.0, 8.0]}
    page.route("**/api/words", lambda route: route.fulfill(status=409, json=no_room))  # as the library says it
    field.fill("a line too long for its time")
    field.press("Enter")
    expect(page.get_by_test_id("line-status")).to_contain_text("join it with the next line.")
    assert problems == []


# The keyboard path: Shift+Enter splits, Enter saves, the arrows walk the rows, Ctrl+Enter goes to the next line.


def test_shift_enter_splits_at_the_cursor_and_the_keyboard_walks_the_rows(
    browser: Browser,
    served: app.AppServer,  # noqa: F811
) -> None:
    problems: list[str] = []
    page = device(browser, served, problems)
    edit(page)
    line(page, 0).focus()
    page.keyboard.press("Enter")
    field = page.get_by_test_id("line-field")
    expect(field).to_be_focused()
    expect(page.get_by_test_id("line-keys")).to_contain_text("Shift+Enter splits at the cursor.")
    caret_before(page, "the harbour")
    page.keyboard.press("Shift+Enter")
    assert field_value(page) == "Morning comes in on\nthe harbour road,"
    expect(page.get_by_test_id("line-editor")).to_be_visible()  # Shift+Enter never saves
    page.keyboard.press("Enter")
    expect(page.get_by_test_id("line-editor")).to_be_hidden(timeout=20000)
    rows = line(page, 0)
    expect(rows).to_have_count(2)
    expect(rows.nth(0)).to_be_focused()  # the keyboard on the line as drawn again
    page.keyboard.press("ArrowDown")
    expect(rows.nth(1)).to_be_focused()
    expect(rows.nth(1)).to_have_attribute("aria-label", re.compile(r"^Line 1, 0:0\d: the harbour road,, fixed$"))
    page.keyboard.press("Enter")  # the second row opens the whole line
    expect(field).to_have_value("Morning comes in on\nthe harbour road,")
    page.keyboard.press("Escape")
    expect(rows.nth(1)).to_be_focused()  # back on the row it was opened from
    page.keyboard.press("Enter")
    page.keyboard.press("Control+Enter")  # nothing changed: on to the next line, not the next row
    expect(field).to_have_value("the radio hums (hums)")
    assert problems == []


# The phone: the keyboard up, the split behind More, the line and Save still in sight.


def test_on_a_phone_with_the_keyboard_up_a_line_is_split_and_saved(
    browser: Browser,
    served: app.AppServer,  # noqa: F811
) -> None:
    problems: list[str] = []
    page = device(browser, served, problems, (390, 844), has_touch=True, is_mobile=True)
    edit(page)
    open_line(page, 0, "harbour")
    page.set_viewport_size({"width": 390, "height": 500})  # the keyboard up: the visual viewport shrinks
    page.wait_for_timeout(300)
    caret_before(page, "the harbour")
    expect(page.get_by_test_id("line-split")).to_be_hidden()  # behind More while typing
    page.get_by_test_id("line-more").click()
    split = page.get_by_test_id("line-split")
    box = split.bounding_box()
    assert box is not None and box["height"] >= 44  # a finger wide
    split.click()
    assert field_value(page) == "Morning comes in on\nthe harbour road,"
    expect(page.get_by_test_id("line-field")).to_be_focused()  # the keyboard comes back up, the cursor after the break
    page.wait_for_timeout(300)
    for el in (line(page, 0).locator(".lwords"), page.get_by_test_id("line-field"), page.get_by_test_id("line-save")):
        b = el.bounding_box()
        assert b is not None and b["y"] >= 0 and b["y"] + b["height"] <= 500, b
    page.get_by_test_id("line-save").click()
    expect(page.get_by_test_id("line-editor")).to_be_hidden(timeout=20000)
    expect(line(page, 0)).to_have_count(2)
    assert problems == []


# French.


def test_split_and_join_in_french(browser: Browser, served: app.AppServer) -> None:  # noqa: F811
    page = browser.new_context(locale="fr-FR").new_page()
    page.goto(served.url + "Pop.woodshed/index.html")
    until(page, "window.Woodshed && window.Woodshed.ready === true && Woodshed.app.canFixWords()")
    page.get_by_test_id("edit-chart").click()
    open_line(page, 0)
    expect(page.get_by_test_id("line-split")).to_have_text("Couper au curseur")
    expect(page.get_by_test_id("line-join")).to_have_text("Joindre à la ligne suivante")
    expect(page.get_by_test_id("line-keys")).to_contain_text("Maj+Entrée coupe au curseur.")
    page.get_by_test_id("line-join").click()
    expect(page.get_by_test_id("line-joined-row")).to_contain_text("jointe à la ligne 1")


# One set of words: the page applies a split and a join as Python does, and exports them so.


def test_the_page_applies_a_split_and_a_join_as_python(open_page: Any) -> None:
    o = open_page("pop", variant="lyrics")
    data = json.loads((o.folder / lyrics.LYRICS).read_text(encoding="utf-8"))
    data["markers"] = [{"before": 1, "tag": "Solo"}, {"before": 3, "tag": "Outro"}]
    piece = {
        "text": "Morning comes",
        "backing": [],
        "check": None,
        "words": [{"text": "Morning", "start": 0.0, "end": 0.8}, {"text": "comes", "start": 1.0, "end": 1.8}],
    }
    rest = {"text": "in on the harbour road,", "backing": [], "check": "placed in this line's time: listen to it",
            "words": [{"text": "in", "start": 2.0, "end": 2.8},
                      {"text": "road,", "start": None, "end": None}]}  # fmt: skip
    entries = {"0": {"was": data["lines"][0]["text"], "lines": [piece, rest]}}
    js = "([d, e]) => Woodshed.wordEdits.apply(d, e)"
    assert o.js(js, [data, entries]) == lyrics.apply_edits(data, entries)
    entries = {
        "0": {"was": data["lines"][0]["text"], "lines": [piece]},
        "1": {"was": "the radio hums", "gone": "joined"},
    }
    assert o.js(js, [data, entries]) == lyrics.apply_edits(data, entries)


def test_the_chordpro_of_the_page_has_the_split_line_as_python(
    browser: Browser,
    served: app.AppServer,  # noqa: F811
) -> None:
    problems: list[str] = []
    page = device(browser, served, problems)
    edit(page)
    open_line(page, 0, "harbour")
    caret_before(page, "the harbour")
    page.keyboard.press("Shift+Enter")
    page.keyboard.press("Enter")
    expect(line(page, 0)).to_have_count(2)
    page.get_by_test_id("edit-done").click()
    folder = served.library.root / "Pop.woodshed"
    data = json.loads((folder / lyrics.LYRICS).read_text(encoding="utf-8"))
    text = chordpro(page)
    assert text == exports.chordpro(
        page.evaluate("Woodshed.current.song"), lyrics.apply_edits(data, stored_lines(served))
    )
    assert [r for r in text.splitlines() if "Morning" in r] and not [
        r for r in text.splitlines() if "Morning" in r and "harbour" in r
    ]
    assert problems == []


# The review: the cursor said, never a split inside a word, the earlier fix back after a join, names.


def test_a_split_needs_the_cursor_between_two_words_and_says_so(
    browser: Browser,
    served: app.AppServer,  # noqa: F811
) -> None:
    problems: list[str] = []
    page = device(browser, served, problems)
    edit(page)
    open_line(page, 0)
    status = page.get_by_test_id("line-status")
    page.get_by_test_id("line-field").evaluate("(f) => f.setSelectionRange(f.value.length, f.value.length)")
    page.keyboard.press("Shift+Enter")  # at the end: nothing to put on a second line
    expect(status).to_have_text("Put the cursor between two words.")
    assert field_value(page) == FIRST
    page.get_by_test_id("line-field").evaluate(
        "(f) => { const at = f.value.indexOf('bour'); f.setSelectionRange(at, at); }"
    )
    page.keyboard.press("Shift+Enter")  # inside "harbour": the break goes to the nearest gap
    assert field_value(page) == "Morning comes in on the\nharbour road,"
    expect(status).to_have_text("Split: 2 lines. Save places them.")
    caret_before(page, "harbour")
    page.keyboard.press("Shift+Enter")  # right after a break: no empty line
    expect(status).to_have_text("Put the cursor between two words.")
    assert field_value(page) == "Morning comes in on the\nharbour road,"
    assert problems == []


def test_back_to_the_placement_on_a_joined_row_gives_the_line_its_earlier_fix(
    browser: Browser,
    served: app.AppServer,  # noqa: F811
) -> None:
    problems: list[str] = []
    page = device(browser, served, problems)
    edit(page)
    open_line(page, 0)
    page.get_by_test_id("line-field").fill("Morning comes in on the harbor road,")
    page.get_by_test_id("line-field").press("Enter")
    expect(page.get_by_test_id("line-editor")).to_be_hidden(timeout=20000)
    open_line(page, 0, "harbor")
    page.get_by_test_id("line-join").click()
    joined = page.get_by_test_id("line-joined-row")
    expect(joined).to_have_count(1)
    into = joined.locator(".gone-into")
    expect(into).to_have_text("joined into line 1")
    assert into.evaluate("(e) => getComputedStyle(e).borderTopStyle") == "none"  # said, not a button-like pill
    back = page.get_by_test_id("line-joined-back")
    expect(back).to_have_attribute("aria-label", "Back to the placement: line 2")
    back.click()
    expect(line(page, 1)).to_contain_text("radio")
    assert words(line(page, 0)) == "Morning comes in on the harbor road,"  # the fix it had before the join
    assert list(stored_lines(served)) == ["0"]
    assert problems == []
