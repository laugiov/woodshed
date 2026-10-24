"""Fixing a line of the words on the sheet (spec 028 A), in the page: Edit mode keeps the Lyrics view, a line
opens the line editor, only that line is placed again by the library, the band sees it, Undo brings it back."""

from __future__ import annotations

import json
import re
import shutil
import threading
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from playwright.sync_api import Browser, Page, expect

from tests.page.conftest import VARIANTS, rewritten
from tests.page.test_lyrics_view import _placed_like_python
from tests.test_lyrics import voice
from woodshed import app, exports, lyrics
from woodshed.run import Options

FIXED = "Morning comes in on the harbor road, yes"


@pytest.fixture
def served(tmp_path: Path, pages_root: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[app.AppServer]:
    """A library serving pop with its words placed, the voice heard before given by a synthetic voice."""
    lib = app.Library(tmp_path / "library", Options(use_stems=False, open_page=False))
    page = lib.root / "Pop.woodshed"
    shutil.copytree(rewritten("pop", pages_root, "lyrics", VARIANTS["lyrics"]), page)
    summary = {"title": "Pop", "key": "C", "bpm": 120, "meter": "4/4", "duration": 18, "doubts": 0, "stems": True}
    (page / "woodshed.json").write_text(json.dumps({"settings": {}, "summary": summary, "complete": True}))
    data = json.loads((page / lyrics.LYRICS).read_text(encoding="utf-8"))
    duration = float(lyrics.page_song(page)["duration"])
    sung = [(w["text"], w["start"], w["end"]) for ln in data["lines"] if ln["sung"] for w in ln["words"]]
    heard = voice(sung, duration + 1)
    monkeypatch.setattr(app.Library, "_voice", lambda self, folder: heard)
    srv = app.AppServer(lib)
    threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()  # a quick shutdown
    yield srv
    srv.shutdown()
    srv.server_close()


def until(page: Page, expression: str, timeout: float = 10) -> None:
    deadline = page.evaluate("Date.now()") + timeout * 1000
    while not page.evaluate(expression):
        if page.evaluate("Date.now()") > deadline:
            raise AssertionError(f"still false after {timeout} s: {expression}")
        page.wait_for_timeout(50)


def device(
    browser: Browser, srv: app.AppServer, problems: list[str], size: tuple[int, int] = (1280, 800), **extra: Any
) -> Page:
    page = browser.new_context(viewport={"width": size[0], "height": size[1]}, locale="en-US", **extra).new_page()
    # Firefox's automation layer warns about its own layout calls (chrome://juggler): not the page. A 409 the page
    # expects (no room for the words) is said by the browser too.
    page.on(
        "console",
        lambda m: (
            problems.append(m.text)
            if m.type in ("error", "warning") and "juggler" not in m.text and "409" not in m.text
            else None
        ),
    )
    page.on("pageerror", lambda e: problems.append(str(e)))
    page.goto(srv.url + "Pop.woodshed/index.html")
    until(
        page,
        "window.Woodshed && window.Woodshed.ready === true && !!Woodshed.app.canFixWords && Woodshed.app.canFixWords()",
    )
    return page


def edit(page: Page) -> None:
    page.get_by_test_id("edit-chart").click()
    expect(page.get_by_test_id("sheet-lyrics")).to_have_attribute("aria-pressed", "true")


def line(page: Page, i: int) -> Any:
    return page.locator(f'#sheet .lline[data-index="{i}"]')


def seeks(page: Page) -> list[str]:
    found: list[str] = page.evaluate(
        "[...document.querySelectorAll('#sheet .lline[data-index=\"1\"] [data-seek]')]"
        ".map((e) => e.getAttribute('data-seek'))"
    )
    return found


def open_line(page: Page, i: int, word: str = "comes") -> Any:
    line(page, i).locator(".wt", has_text=word).first.click()
    ed = page.get_by_test_id("line-editor")
    expect(ed).to_be_visible()
    return ed


def save(page: Page, text: str) -> None:
    field = page.get_by_test_id("line-field")
    field.fill(text)
    field.press("Enter")
    expect(page.get_by_test_id("line-editor")).to_be_hidden(timeout=20000)


# A10: Edit mode keeps the Lyrics view; a line opens the line editor.


def test_edit_mode_keeps_the_words_and_a_line_opens_its_editor(browser: Browser, served: app.AppServer) -> None:
    problems: list[str] = []
    page = device(browser, served, problems)
    expect(page.get_by_test_id("edit-chart")).to_have_text("Edit chords and words")
    line(page, 0).locator(".wt", has_text="comes").click()  # outside Edit mode: a word seeks
    expect(page.get_by_test_id("line-editor")).to_be_hidden()
    edit(page)
    expect(page.get_by_test_id("edit-strip")).to_contain_text("Click a line to fix its words, a chord to type its bar.")
    ed = open_line(page, 0)
    field = page.get_by_test_id("line-field")
    expect(field).to_have_value("Morning comes in on the harbour road,")
    expect(field).to_be_focused()
    selected = page.evaluate(
        "(() => { const f = document.activeElement; return f.value.slice(f.selectionStart, f.selectionEnd); })()"
    )
    assert selected == "comes"  # the word tapped, ready to be typed over
    expect(ed.locator("h3")).to_contain_text("Morning comes in on…")  # the line by its words, not a number
    assert problems == []


# A11: only that line is placed again, the band's way; Undo and Back to the placement.


def test_a_fixed_line_shows_and_undo_brings_it_back(browser: Browser, served: app.AppServer) -> None:
    problems: list[str] = []
    page = device(browser, served, problems)
    posts: list[str] = []
    page.on("request", lambda r: posts.append(r.url.split("/")[-1]) if r.method == "POST" else None)
    edit(page)
    before = seeks(page)
    open_line(page, 0)
    save(page, FIXED)
    expect(line(page, 0)).to_contain_text("harbor")
    expect(line(page, 0)).to_have_class(re.compile(r"\bedited\b"))
    expect(line(page, 0).locator(".fixed-mark")).to_have_text("✎ fixed")
    assert seeks(page) == before  # the other lines did not move
    assert posts.count("words") == 1 and "lyrics" not in posts  # one line, never the whole song
    expect(page.get_by_test_id("toast")).to_contain_text("\u201cMorning comes in on\u2026\u201d saved.")
    expect(line(page, 0)).to_be_focused()  # the keyboard on the line as drawn again
    page.get_by_test_id("toast-action").click()  # Undo
    expect(line(page, 0)).to_contain_text("harbour")
    expect(line(page, 0)).not_to_have_class(re.compile(r"\bedited\b"))
    open_line(page, 0)
    save(page, FIXED)
    expect(line(page, 0)).to_contain_text("harbor")
    open_line(page, 0, "harbor")
    page.get_by_test_id("line-back").click()  # Back to the placement
    expect(page.get_by_test_id("line-editor")).to_be_hidden()
    expect(line(page, 0)).to_contain_text("harbour")
    expect(line(page, 0).locator(".fixed-mark")).to_have_count(0)
    assert problems == []


def test_undo_stays_in_the_strip_and_ctrl_z_takes_it(browser: Browser, served: app.AppServer) -> None:
    problems: list[str] = []
    page = device(browser, served, problems)
    edit(page)
    open_line(page, 0)
    save(page, FIXED)
    expect(page.get_by_test_id("words-undo")).to_be_visible()
    page.evaluate("document.querySelector('#toast').hidden = true")
    line(page, 1).focus()
    page.keyboard.press("Control+z")
    expect(line(page, 0)).to_contain_text("harbour")
    expect(page.get_by_test_id("words-undo")).to_have_count(0)
    assert problems == []


def test_a_number_is_said_not_heard_and_no_room_is_said_where(browser: Browser, served: app.AppServer) -> None:
    problems: list[str] = []
    page = device(browser, served, problems)
    edit(page)
    open_line(page, 1, "radio")
    save(page, "the radio 14 hums what")
    expect(page.get_by_test_id("toast")).to_contain_text("14 is not heard: write numbers as words.")
    open_line(page, 1, "radio")
    field = page.get_by_test_id("line-field")
    field.fill(" ".join(["aaaa"] * 40))  # 160 letters, a blank between each two: more than the line's time holds
    field.press("Enter")
    expect(page.get_by_test_id("line-status")).to_contain_text("Not enough time for these words between")
    expect(field).to_have_attribute("aria-invalid", "true")
    expect(page.get_by_test_id("line-editor")).to_be_visible()  # nothing saved, the text kept
    assert problems == []


def test_offline_keeps_the_text_with_retry(browser: Browser, served: app.AppServer) -> None:
    problems: list[str] = []
    page = device(browser, served, problems)
    edit(page)
    open_line(page, 0)
    page.route("**/api/words", lambda route: route.abort())
    field = page.get_by_test_id("line-field")
    field.fill(FIXED)
    field.press("Enter")
    expect(page.get_by_test_id("line-status")).to_contain_text("The library did not answer: the line is not changed.")
    expect(field).to_have_value(FIXED)
    page.unroute("**/api/words")
    page.get_by_test_id("line-retry").click()
    expect(page.get_by_test_id("line-editor")).to_be_hidden()
    expect(line(page, 0)).to_contain_text("harbor")
    assert [p for p in problems if "net::" not in p and "NS_ERROR" not in p and "Failed to fetch" not in p] == []


# A12: not in this recording, another voice.


def test_a_line_not_in_this_recording_leaves_the_sheet_the_stage_and_the_chordpro(
    browser: Browser, served: app.AppServer
) -> None:
    problems: list[str] = []
    page = device(browser, served, problems)
    edit(page)
    open_line(page, 1, "radio")
    page.get_by_test_id("line-gone").click()
    expect(page.get_by_test_id("line-editor")).to_be_hidden()
    row = page.get_by_test_id("line-gone-row")
    expect(row).to_have_count(1)  # one quiet row, in Edit mode only
    expect(row).to_contain_text("not in this recording")
    page.get_by_test_id("edit-done").click()
    expect(page.get_by_test_id("lyric-line")).to_have_count(1)
    expect(page.get_by_test_id("line-gone-row")).to_have_count(0)
    folder = served.library.root / "Pop.woodshed"
    data = json.loads((folder / lyrics.LYRICS).read_text(encoding="utf-8"))
    entries = served.library.corrections("Pop.woodshed", "a1b2c3", None, lyrics.words_key(data))["words"]["lines"]
    applied = lyrics.apply_edits(data, entries)
    _placed_like_python(SimpleNamespace(js=lambda e, a=None: page.evaluate(e, a)), applied)
    assert "radio" not in chordpro(page)
    page.get_by_test_id("edit-chart").click()
    page.get_by_test_id("line-gone-back").click()  # Back to the placement, from the row
    expect(line(page, 1)).to_contain_text("radio")
    assert problems == []


def test_another_voice_stays_on_the_sheet_off_the_singers_stage(browser: Browser, served: app.AppServer) -> None:
    problems: list[str] = []
    page = device(browser, served, problems)
    edit(page)
    open_line(page, 0)
    other = page.get_by_test_id("line-other")
    expect(other).to_have_attribute("aria-pressed", "false")
    other.click()
    expect(line(page, 0)).to_have_class(re.compile(r"\bother\b"))
    page.get_by_test_id("edit-done").click()
    page.locator("#instruments button", has_text="Voice").click()
    page.get_by_test_id("stage-open").click()
    page.evaluate("Woodshed.app.seekBar(0)")
    expect(page.get_by_test_id("stage-line").first).to_contain_text("radio")  # the MC's line is not the singer's
    expect(page.locator("#stLyrics")).not_to_contain_text("Morning")
    assert problems == []


# A13: two devices of the band.


def test_the_band_sees_a_fix_and_a_take_back_without_a_reload(browser: Browser, served: app.AppServer) -> None:
    problems: list[str] = []
    a = device(browser, served, problems)
    b = device(browser, served, problems)
    edit(a)
    open_line(a, 0)
    save(a, FIXED)
    expect(b.locator('#sheet .lline[data-index="0"]')).to_contain_text("harbor")
    expect(b.get_by_test_id("toast")).to_contain_text(
        "\u201cMorning comes in on\u2026\u201d changed on another device."
    )
    edit(b)
    open_line(b, 0, "harbor")
    b.get_by_test_id("line-back").click()
    expect(a.locator('#sheet .lline[data-index="0"]')).to_contain_text("harbour")
    expect(a.locator('#sheet .lline[data-index="0"] .fixed-mark')).to_have_count(0)
    assert problems == []


# A14: one set of words for the sheet, the stage and the exports.


def chordpro(page: Page) -> str:
    page.get_by_test_id("export").click()
    with page.expect_download() as info:
        page.get_by_test_id("export-chordpro").click()
    path = info.value.path()
    assert path is not None
    return Path(path).read_text(encoding="utf-8")


def test_the_chordpro_and_the_stage_read_the_fixed_words(browser: Browser, served: app.AppServer) -> None:
    problems: list[str] = []
    page = device(browser, served, problems)
    edit(page)
    open_line(page, 0)
    save(page, FIXED)
    page.get_by_test_id("edit-done").click()
    folder = served.library.root / "Pop.woodshed"
    data = json.loads((folder / lyrics.LYRICS).read_text(encoding="utf-8"))
    entries = served.library.corrections("Pop.woodshed", "a1b2c3", None, lyrics.words_key(data))["words"]["lines"]
    text = chordpro(page)
    assert "harbor" in text and text == exports.chordpro(
        page.evaluate("Woodshed.current.song"), lyrics.apply_edits(data, entries)
    )
    page.get_by_test_id("stage-open").click()
    page.evaluate("Woodshed.app.seekBar(1)")
    expect(page.get_by_test_id("stage-line").first).to_contain_text("harbor")
    assert problems == []


# A7, A12: the key and the words with the fixes, the same in the page and in Python.

KEYED = [
    {
        "lines": [
            {"text": "Je ne fait pourtant de tort à personne", "words": [{"text": "Je", "start": 17.72, "end": 18}]}
        ]
    },
    {"lines": [{"text": "Le jour du 14 juillet", "words": [{"text": "14", "start": None, "end": None}]}]},
    {"lines": [{"text": "Qu\u2019je m\u2019démène", "words": [{"text": "Qu\u2019je", "start": 1.0625, "end": 2}]}]},
]


@pytest.mark.parametrize("data", KEYED)
def test_the_page_keys_a_placement_as_python(open_page: Any, data: dict[str, Any]) -> None:
    o = open_page("pop", variant="lyrics")
    assert o.js("(d) => Woodshed.wordEdits.key(d)", data) == lyrics.words_key(data)


def test_the_page_applies_the_fixes_as_python(open_page: Any) -> None:
    o = open_page("pop", variant="lyrics")
    data = json.loads((o.folder / lyrics.LYRICS).read_text(encoding="utf-8"))
    line = {"text": "the radio sings", "backing": [], "check": None,
            "words": [{"text": "the", "start": 9.0, "end": 9.5}, {"text": "radio", "start": 9.5, "end": 10.2},
                      {"text": "sings", "start": None, "end": None}]}  # fmt: skip
    entries = {
        "0": {"was": data["lines"][0]["text"], "gone": "not-sung"},
        "1": {"was": data["lines"][1]["text"], "lines": [line], "voice": "other"},
        "7": {"was": "not a line", "gone": "not-sung"},
    }
    assert o.js("([d, e]) => Woodshed.wordEdits.apply(d, e)", [data, entries]) == lyrics.apply_edits(data, entries)


# A15, A16: keyboard and names.


def test_the_lines_are_one_tab_stop_and_the_arrows_walk_them(browser: Browser, served: app.AppServer) -> None:
    problems: list[str] = []
    page = device(browser, served, problems)
    edit(page)
    stops = page.evaluate("[...document.querySelectorAll('#sheet .lline[role=button]')].map((e) => e.tabIndex)")
    assert sorted(stops) == [-1, 0]  # one Tab stop for the lines
    expect(line(page, 0)).to_have_attribute(
        "aria-label", re.compile(r"^Line 1, 0:0\d: Morning comes in on the harbour road,$")
    )
    expect(line(page, 1)).to_have_attribute("aria-label", re.compile(r"^Line 2, 0:\d\d: the radio hums, to check$"))
    line(page, 0).focus()
    page.keyboard.press("ArrowDown")
    expect(line(page, 1)).to_be_focused()
    page.keyboard.press("ArrowUp")
    expect(line(page, 0)).to_be_focused()
    page.keyboard.press("Enter")
    ed = page.get_by_test_id("line-editor")
    expect(ed).to_be_visible()
    expect(ed).to_have_attribute("role", "dialog")
    expect(ed).to_have_attribute("aria-modal", "true")
    assert page.evaluate(
        "document.getElementById(document.querySelector('#lineEd').getAttribute('aria-labelledby')).textContent"
    ).startswith("Morning comes in on")
    expect(page.get_by_test_id("line-status")).to_have_attribute("aria-live", "polite")
    expect(page.get_by_test_id("line-field")).to_be_focused()
    page.keyboard.press("Escape")
    expect(ed).to_be_hidden()
    expect(line(page, 0)).to_be_focused()  # back on the line it opened
    page.keyboard.press("Enter")
    page.get_by_test_id("line-field").fill(FIXED)
    page.keyboard.press("Control+Enter")  # saved, and the next line opened
    expect(ed.locator("h3")).to_contain_text("the radio hums", timeout=20000)
    expect(page.get_by_test_id("line-field")).to_have_value("the radio hums (hums)")
    page.keyboard.press("Escape")
    expect(line(page, 1)).to_be_focused()
    expect(line(page, 0)).to_have_attribute("aria-label", re.compile(r", fixed$"))
    assert problems == []


def space_plays_on_a_line(page: Page) -> None:
    edit(page)
    line(page, 0).focus()
    page.keyboard.press("Tab")
    page.keyboard.press("Shift+Tab")
    expect(line(page, 0)).to_be_focused()
    page.keyboard.press(" ")
    until(page, "Woodshed.debug().playing === true")
    expect(page.get_by_test_id("line-editor")).to_be_hidden()  # Space plays, a pedal: it never opens the line


def test_space_on_a_line_plays(browser: Browser, served: app.AppServer) -> None:
    problems: list[str] = []
    space_plays_on_a_line(device(browser, served, problems))
    assert problems == []


@pytest.mark.tablet
def test_space_on_a_line_plays_on_a_tablet(browser: Browser, served: app.AppServer) -> None:
    problems: list[str] = []
    space_plays_on_a_line(device(browser, served, problems, (1024, 768), has_touch=True))
    assert problems == []


# The chord of the line's bar, from the line (R10).


def test_a_chip_opens_the_bar_editor_and_the_keyboard_comes_back_to_the_line(
    browser: Browser, served: app.AppServer
) -> None:
    problems: list[str] = []
    page = device(browser, served, problems)
    edit(page)
    open_line(page, 0)
    chips = page.get_by_test_id("line-bar")
    expect(chips).to_have_count(4)  # one a bar the line holds
    expect(chips.first).to_contain_text("Bar 1")
    chips.first.click()
    expect(page.get_by_test_id("line-editor")).to_be_hidden()
    bar = page.get_by_test_id("bar-editor")
    expect(bar).to_be_visible()
    expect(bar.locator("h3")).to_contain_text("Bar 1")
    expect(page.get_by_test_id("bar-also")).to_be_visible()  # the same bar where the part is played again
    page.get_by_test_id("bar-field").fill("Dm")
    page.get_by_test_id("bar-save").click()
    expect(line(page, 0).locator(".lc").first).to_have_text("Dm")
    expect(line(page, 0)).to_be_focused()
    line(page, 0).locator(".lc", has_text="Dm").first.click()  # a chord name opens its bar too
    expect(bar).to_be_visible()
    page.keyboard.press("Escape")
    expect(line(page, 0)).to_be_focused()
    assert problems == []


# The words dialog, the strip, the stage, the phone.


def test_words_back_to_the_placement_and_the_dialog_count(browser: Browser, served: app.AppServer) -> None:
    problems: list[str] = []
    page = device(browser, served, problems)
    edit(page)
    open_line(page, 0)
    save(page, FIXED)
    page.get_by_test_id("words-header").click()
    expect(page.get_by_test_id("words-dialog")).to_contain_text(
        "1 line is fixed on the sheet: placing the words again keeps each fix whose line still reads the same here."
    )
    page.keyboard.press("Escape")
    page.on("dialog", lambda d: d.accept())
    page.get_by_test_id("words-untype-all").click()
    expect(line(page, 0)).to_contain_text("harbour")
    expect(page.get_by_test_id("toast")).to_contain_text("The words are the placement's again.")
    page.get_by_test_id("toast-action").click()
    expect(line(page, 0)).to_contain_text("harbor")
    assert problems == []


def test_the_stage_closes_the_line_editor(browser: Browser, served: app.AppServer) -> None:
    problems: list[str] = []
    page = device(browser, served, problems)
    edit(page)
    open_line(page, 0)
    page.evaluate("Woodshed.app.setStage(true, false)")
    expect(page.get_by_test_id("line-editor")).to_be_hidden()
    assert problems == []


def test_on_a_phone_the_keyboard_leaves_the_line_the_field_and_save_in_view(
    browser: Browser, served: app.AppServer
) -> None:
    problems: list[str] = []
    page = device(browser, served, problems, (390, 844), has_touch=True, is_mobile=True)
    edit(page)
    expect(page.get_by_test_id("edit-strip")).to_contain_text("Tap a line to fix its words, a chord to type its bar.")
    open_line(page, 0)
    page.get_by_test_id("line-field").focus()
    page.set_viewport_size({"width": 390, "height": 500})  # the keyboard up: the visual viewport shrinks
    page.wait_for_timeout(300)
    for el in (line(page, 0).locator(".lwords"), page.get_by_test_id("line-field"), page.get_by_test_id("line-save")):
        box = el.bounding_box()
        assert box is not None and box["y"] >= 0 and box["y"] + box["height"] <= 500, box
    expect(page.get_by_test_id("line-more")).to_be_visible()  # the chips and tools behind More
    expect(page.get_by_test_id("line-bar").first).to_be_hidden()
    page.get_by_test_id("line-more").click()
    expect(page.get_by_test_id("line-bar").first).to_be_visible()
    page.get_by_test_id("line-field").focus()
    expect(page.get_by_test_id("line-bar").first).to_be_hidden()
    page.locator("#lineEd h3").click()  # the keyboard down: the whole sheet again
    expect(page.get_by_test_id("line-bar").first).to_be_visible()
    assert problems == []


def test_a_page_without_the_library_fixes_no_line(open_page: Any) -> None:
    o = open_page("pop", variant="lyrics")
    o.page.get_by_test_id("edit-chart").click()
    expect(o.page.get_by_test_id("sheet-lyrics")).to_have_attribute("aria-pressed", "true")
    expect(o.page.get_by_test_id("words-need-library")).to_have_text(
        "Fixing a line's words needs the library (woodshed app)."
    )
    o.page.get_by_test_id("lyric-line").first.locator(".wt").first.click()
    expect(o.page.get_by_test_id("line-editor")).to_be_hidden()


def test_a_served_page_without_its_token_fixes_no_line(browser: Browser, served: app.AppServer) -> None:
    page = browser.new_context(locale="en-US").new_page()
    page.route("**/api/token", lambda route: route.fulfill(status=503, body="{}"))
    page.goto(served.url + "Pop.woodshed/index.html")
    until(page, "window.Woodshed && window.Woodshed.ready === true")
    edit(page)
    expect(page.get_by_test_id("words-need-library")).to_be_visible()
    line(page, 0).locator(".wt").first.click()
    expect(page.get_by_test_id("line-editor")).to_be_hidden()


def test_the_strip_and_the_editor_in_french(browser: Browser, served: app.AppServer) -> None:
    page = browser.new_context(locale="fr-FR").new_page()
    page.goto(served.url + "Pop.woodshed/index.html")
    until(page, "window.Woodshed && window.Woodshed.ready === true && Woodshed.app.canFixWords()")
    page.get_by_test_id("edit-chart").click()
    expect(page.get_by_test_id("edit-strip")).to_contain_text("Clique sur une ligne pour corriger ses paroles")
    open_line(page, 0)
    expect(page.get_by_test_id("line-editor").locator("h3")).to_contain_text("Morning comes in on")
    expect(page.get_by_test_id("line-editor").locator("h3 small")).to_contain_text("Ligne 1")
    expect(page.get_by_test_id("line-gone")).to_have_text("Pas dans cet enregistrement")


# The review of the first version: Undo and another device, a stale page, touch targets, long lines.


def test_undo_leaves_another_devices_fix_as_it_is(browser: Browser, served: app.AppServer) -> None:
    problems: list[str] = []
    page = device(browser, served, problems)
    edit(page)
    open_line(page, 0)
    save(page, FIXED)
    key = lyrics.words_key(
        json.loads((served.library.root / "Pop.woodshed" / lyrics.LYRICS).read_text(encoding="utf-8"))
    )
    other = "Morning comes in on the harbour roads, yes"
    saved = served.library.set_words({"page": "Pop.woodshed", "key": key, "lines": {"0": {"text": other}}})
    served.live.corrected("Pop.woodshed", saved["rev"])  # another device, told on the stream as /api/words does
    expect(line(page, 0)).to_contain_text("roads")
    page.get_by_test_id("words-undo").click()  # this device's Undo, kept in the strip
    expect(page.get_by_test_id("toast")).to_contain_text("changed on another device: Undo leaves it as it is.")
    expect(page.get_by_test_id("toast-action")).to_have_text("Reload")  # the page as the band has it, in one tap
    expect(line(page, 0)).to_contain_text("roads")
    assert problems == []


def test_a_page_whose_words_were_placed_again_says_to_reload(browser: Browser, served: app.AppServer) -> None:
    problems: list[str] = []
    page = device(browser, served, problems)
    edit(page)
    folder = served.library.root / "Pop.woodshed"
    data = json.loads((folder / lyrics.LYRICS).read_text(encoding="utf-8"))
    data["lines"][1]["words"][0]["start"] += 0.1  # placed again elsewhere: another placement
    lyrics.write(folder, data)
    open_line(page, 0)
    page.get_by_test_id("line-field").fill(FIXED)
    page.get_by_test_id("line-field").press("Enter")
    expect(page.get_by_test_id("line-status")).to_have_text("The words were placed again: reload the page.")
    expect(page.get_by_test_id("line-reload")).to_be_visible()
    assert problems == []


def test_back_to_the_placement_is_a_finger_wide_on_a_phone(browser: Browser, served: app.AppServer) -> None:
    problems: list[str] = []
    page = device(browser, served, problems, (390, 844), has_touch=True, is_mobile=True)
    edit(page)
    open_line(page, 1, "radio")
    page.get_by_test_id("line-more").click()  # the keyboard up: the tools behind More
    page.get_by_test_id("line-gone").click()
    box = page.get_by_test_id("line-gone-back").bounding_box()
    assert box is not None and box["height"] >= 44
    assert problems == []


def test_a_long_line_shows_whole_in_the_field(browser: Browser, served: app.AppServer) -> None:
    problems: list[str] = []
    page = device(browser, served, problems)
    edit(page)
    open_line(page, 0)
    field = page.get_by_test_id("line-field")
    field.fill("Morning comes in on the harbour road, yes, and the gulls are out over the water before the bells ring")
    assert page.evaluate(
        "(() => { const f = document.querySelector('#lineEdField'); return f.scrollHeight <= f.clientHeight + 2; })()"
    )
    assert problems == []
