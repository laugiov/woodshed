"""The words typed by hand (spec 029-1), in the page: a line typed in 028's line editor with `|` bar lines, on an
empty bar, on a page with no words, on a part the model left empty; a word moved without dragging (tap a word then a
slot, ◀ ▶ half a beat, M from the keyboard); a typed line covering a placed one; the stage and the ChordPro reading
typed lines; the keyboard, a phone with its keyboard up, French. The reading is woodshed.typed's, on one case file."""

from __future__ import annotations

import json
import re
import shutil
import threading
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Browser, Page, expect

from tests.page.conftest import VARIANTS, rewritten
from tests.page.test_edit_a_line import chordpro, line, open_line, save, until
from tests.test_lyrics import voice
from woodshed import app, lyrics, typed
from woodshed.run import Options

CASES = json.loads((Path(__file__).parents[1] / "words_typed_cases.json").read_text(encoding="utf-8"))


# The same reading as the library (shared case file).


def test_the_page_reads_a_typed_line_as_the_library(open_page: Any) -> None:
    o = open_page("pop", variant="lyrics")
    song = CASES["song"]
    for case in CASES["lines"]:
        until_t = typed.beat_time(song, case["until_at"]) if "until_at" in case else None
        try:
            want: Any = typed.typed_line(case["text"], case["at"], song, case.get("old"), until_t)
        except typed.TypedError as err:
            want = {"error": err.code} if err.bar is None else {"error": err.code, "bar": err.bar}
        got = o.js(
            "([t, at, s, old, u]) => Woodshed.typedWords.line(t, at, s, old, u)",
            [case["text"], case["at"], song, case.get("old"), until_t],
        )
        assert got == want, case["name"]
    for at, t in CASES["beats"]:
        assert o.js("([s, at]) => Woodshed.typedWords.beatTime(s, at)", [song, at]) == typed.beat_time(song, at) == t
    for word, n in CASES["syllables"]:
        assert o.js("(w) => Woodshed.typedWords.syllables(w)", word) == typed.syllables(word) == n, word


def test_the_page_puts_typed_lines_over_placed_ones_as_the_library(open_page: Any) -> None:
    o = open_page("pop", variant="lyrics")
    data = json.loads((o.folder / lyrics.LYRICS).read_text(encoding="utf-8"))
    song = o.js("() => Woodshed.current.song")
    first = song["first_beat"] + 4 * song["beats_per_bar"]  # bar 5: over the second placed line
    line_ = typed.typed_line("the radio | sings _", first, song)
    entries = {
        "t0000000a": {"typed": True, "src": None, "notation": line_["notation"],
                      "lines": [{**line_, "tag": "", "check": None}]},
        "0": {"was": data["lines"][0]["text"], "gone": "not-sung"},
        "tzzzzzzzz": {"typed": True, "lines": []},  # not a typed key: left out
    }  # fmt: skip
    got = o.js("([d, e]) => Woodshed.wordEdits.apply(d, e)", [data, entries])
    assert got == lyrics.apply_edits(data, entries)
    assert got["lines"][1]["covered"] is True and got["lines"][-1]["key"] == "t0000000a"


# The library serving pop: with its words placed (lyrics), without (sections), the chorus left empty.


@pytest.fixture
def library(
    tmp_path: Path, pages_root: str, monkeypatch: pytest.MonkeyPatch
) -> Iterator[Callable[[str], app.AppServer]]:
    servers: list[app.AppServer] = []

    def serve(variant: str) -> app.AppServer:
        lib = app.Library(tmp_path / f"library-{variant}", Options(use_stems=False, open_page=False))
        page = lib.root / "Pop.woodshed"
        shutil.copytree(rewritten("pop", pages_root, variant, VARIANTS[variant]), page)
        summary = {"title": "Pop", "key": "C", "bpm": 120, "meter": "4/4", "duration": 18, "doubts": 0, "stems": True}
        (page / "woodshed.json").write_text(json.dumps({"settings": {}, "summary": summary, "complete": True}))
        if (page / lyrics.LYRICS).exists():
            data = json.loads((page / lyrics.LYRICS).read_text(encoding="utf-8"))
            sung = [(w["text"], w["start"], w["end"]) for ln in data["lines"] if ln["sung"] for w in ln["words"]]
            heard = voice(sung, 19)
            monkeypatch.setattr(app.Library, "_voice", lambda self, folder: heard)
        else:
            (page / lyrics.LYRICS_JS).write_text("window.WOODSHED_LYRICS = null;\n")
        srv = app.AppServer(lib)
        threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
        servers.append(srv)
        return srv

    yield serve
    for srv in servers:
        srv.shutdown()
        srv.server_close()


def device(
    browser: Browser,
    srv: app.AppServer,
    problems: list[str],
    size: tuple[int, int] = (1280, 800),
    locale: str = "en-US",
    **extra: Any,
) -> Page:
    page = browser.new_context(viewport={"width": size[0], "height": size[1]}, locale=locale, **extra).new_page()
    page.on(
        "console",
        lambda m: (
            problems.append(m.text)
            if m.type in ("error", "warning")
            and "juggler" not in m.text
            and "400" not in m.text
            and "409" not in m.text
            else None
        ),
    )
    page.on("pageerror", lambda e: problems.append(str(e)))
    page.goto(srv.url + "Pop.woodshed/index.html")
    until(page, "window.Woodshed && Woodshed.ready === true && Woodshed.app.canFixWords()")
    return page


def edit(page: Page) -> None:
    page.get_by_test_id("edit-chart").click()
    expect(page.get_by_test_id("edit-strip")).to_be_visible()


def meta(page: Page) -> dict[str, Any]:
    got: dict[str, Any] = page.evaluate("Woodshed.current.song")
    return got


def typed_entries(srv: app.AppServer) -> dict[str, Any]:
    folder = srv.library.root / "Pop.woodshed"
    path = folder / lyrics.LYRICS
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"lines": []}
    got = srv.library.corrections("Pop.woodshed", "a1b2c3", None, lyrics.words_key(data))["words"]["lines"]
    return {k: v for k, v in got.items() if k.startswith("t")}


def typed_row(page: Page) -> Any:
    return page.locator("#sheet .lline[data-key]")


def words_of(row: Any) -> str:
    """A sung line's words as the sheet draws them, without its chords."""
    return " ".join(row.locator(".wt").all_text_contents())


def type_line(page: Page, text: str) -> None:
    """A line typed from the bar editor open on its first bar."""
    page.get_by_test_id("bar-editor").get_by_test_id("type-line-here").click()
    field = page.get_by_test_id("typed-field")
    expect(field).to_be_focused()
    field.fill(text)
    field.press("Enter")
    expect(page.get_by_test_id("line-editor")).to_be_hidden(timeout=20000)


def put(page: Page, srv: app.AppServer, key: str, text: str, at: int) -> None:
    """A typed line written by another device of the band, told on the stream as /api/words does; once this page
    shows it (a click while the sheet is drawn again would be lost)."""
    seen = typed_row(page).count()
    folder = srv.library.root / "Pop.woodshed"
    path = folder / lyrics.LYRICS
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"lines": []}
    saved = srv.library.set_words(
        {"page": "Pop.woodshed", "key": lyrics.words_key(data), "lines": {key: {"typed": {"text": text, "at": at}}}}
    )
    srv.live.corrected("Pop.woodshed", saved["rev"])
    expect(typed_row(page)).to_have_count(seen + 1)


# Typing a line.


def test_a_line_typed_on_an_empty_bar(browser: Browser, library: Callable[[str], app.AppServer]) -> None:
    srv = library("lyrics")
    problems: list[str] = []
    page = device(browser, srv, problems)
    edit(page)
    here = page.get_by_test_id("type-line-here")
    expect(here).to_have_count(1)  # bar 8, after the last sung line and the bar it holds
    here.click()
    ed = page.get_by_test_id("line-editor")
    expect(ed.locator("h3")).to_contain_text("New line")
    expect(ed.locator("h3 small")).to_contain_text("from bar 8")
    page.get_by_test_id("typed-field").fill("Hold me now")
    expect(page.get_by_test_id("typed-read")).to_have_text("Bar 8: “Hold” on 1, “me” on 2, “now” on 3.")
    page.get_by_test_id("typed-field").press("Enter")
    expect(ed).to_be_hidden(timeout=20000)
    row = typed_row(page)
    expect(row).to_have_count(1)
    assert words_of(row) == "Hold me now"
    expect(row.locator(".typed-mark")).to_have_text("typed")
    expect(page.get_by_test_id("toast")).to_contain_text("“Hold me now” saved.")
    ((_, entry),) = typed_entries(srv).items()
    s = meta(page)
    first = s["first_beat"] + 7 * s["beats_per_bar"]
    words = entry["lines"][0]["words"]
    assert [w["at"] for w in words] == [first, first + 1, first + 2]
    assert [w["start"] for w in words] == [typed.beat_time(s, a) for a in (first, first + 1, first + 2)]
    page.get_by_test_id("toast-action").click()  # Undo
    expect(typed_row(page)).to_have_count(0)
    assert typed_entries(srv) == {}
    assert problems == []


def test_a_page_without_words_gets_its_first_line_from_the_bar_editor(
    browser: Browser, library: Callable[[str], app.AppServer]
) -> None:
    srv = library("sections")
    problems: list[str] = []
    page = device(browser, srv, problems)
    expect(page.get_by_test_id("sheet-lyrics")).to_have_count(0)  # no words: the grid
    edit(page)
    page.locator('#sheet .bar[data-bar="0"]').click()
    expect(page.get_by_test_id("bar-editor")).to_be_visible()
    type_line(page, "Hello there | world")
    expect(page.get_by_test_id("sheet-lyrics")).to_have_attribute("aria-pressed", "true")  # the Lyrics view, at once
    assert words_of(typed_row(page)) == "Hello there world"
    ((_, entry),) = typed_entries(srv).items()
    assert entry["lines"][0]["tag"] == "Verse 1"
    assert next(s for s in srv.library.pages() if s["folder"] == "Pop.woodshed")["words"] is True
    assert problems == []


def test_a_part_the_model_left_empty_takes_a_typed_line(
    browser: Browser, library: Callable[[str], app.AppServer]
) -> None:
    srv = library("lyrics-verse-only")
    problems: list[str] = []
    page = device(browser, srv, problems)
    edit(page)
    page.get_by_test_id("type-line-here").first.click()
    expect(page.get_by_test_id("line-editor").locator("h3 small")).to_contain_text("Chorus 1")
    page.get_by_test_id("typed-field").fill("la la la | la")
    page.get_by_test_id("typed-save").click()
    expect(page.get_by_test_id("line-editor")).to_be_hidden(timeout=20000)
    expect(typed_row(page)).to_have_count(1)
    assert words_of(typed_row(page)) == "la la la la"
    ((_, entry),) = typed_entries(srv).items()
    s = meta(page)
    assert entry["lines"][0]["tag"] == "Chorus 1" and entry["lines"][0]["words"][0]["at"] == s["first_beat"] + 16
    assert problems == []


def test_a_typed_line_hides_the_placed_line_it_covers(
    browser: Browser, library: Callable[[str], app.AppServer]
) -> None:
    srv = library("lyrics")
    problems: list[str] = []
    page = device(browser, srv, problems)
    edit(page)
    line(page, 1).locator('.nb[data-bar="4"] .bl').click()  # bar 5's number: its bar editor
    page.get_by_test_id("bar-editor").get_by_test_id("type-line-here").click()
    page.get_by_test_id("typed-field").fill("the radio | sings")
    expect(page.get_by_test_id("typed-read")).to_contain_text(
        "Covers the placed line “the radio hums”: hidden while this one is there."
    )
    page.get_by_test_id("typed-field").press("Enter")
    expect(page.get_by_test_id("line-editor")).to_be_hidden(timeout=20000)
    expect(line(page, 1)).to_have_count(0)
    covered = page.get_by_test_id("line-covered-row")
    expect(covered).to_contain_text("the radio hums")
    expect(covered).to_contain_text("covered by a typed line")
    expect(covered).not_to_have_class(re.compile(r"\bcur\b"))  # a quiet row is never the line sung
    page.get_by_test_id("edit-done").click()  # play mode: no quiet row
    expect(covered).to_have_count(0)
    edit(page)
    typed_row(page).locator(".wt", has_text="sings").click()
    page.get_by_test_id("typed-off").click()
    expect(line(page, 1)).to_contain_text("radio")
    expect(page.get_by_test_id("line-covered-row")).to_have_count(0)
    assert problems == []


def test_a_line_overlapping_another_typed_line_is_said_and_not_sent(
    browser: Browser, library: Callable[[str], app.AppServer]
) -> None:
    srv = library("sections")
    problems: list[str] = []
    page = device(browser, srv, problems)
    s = meta(page)
    put(page, srv, "t00000001", "one | two", s["first_beat"] + 4)  # bars 2 and 3
    expect(typed_row(page)).to_have_count(1)
    edit(page)
    page.locator('#sheet .bar[data-bar="0"]').first.click()
    page.get_by_test_id("bar-editor").get_by_test_id("type-line-here").click()
    posts: list[str] = []
    page.on("request", lambda r: posts.append(r.url) if r.method == "POST" else None)
    page.get_by_test_id("typed-field").fill("a | b c")
    expect(page.get_by_test_id("typed-read")).to_contain_text("Another typed line is sung there")
    page.get_by_test_id("typed-field").press("Enter")
    expect(page.get_by_test_id("line-editor")).to_be_visible()
    page.get_by_test_id("typed-cancel").click()
    page.locator('#sheet .nb[data-bar="2"] .bl').click()  # bar 3: inside the other line
    page.get_by_test_id("bar-editor").get_by_test_id("type-line-here").click()
    page.get_by_test_id("typed-field").fill("x")
    expect(page.get_by_test_id("typed-read")).to_contain_text("Another typed line is sung there")
    page.get_by_test_id("typed-save").click()
    expect(page.get_by_test_id("line-editor")).to_be_visible()
    assert posts == []
    assert problems == []


# Moving a word without dragging.


def test_tap_a_word_then_a_slot(browser: Browser, library: Callable[[str], app.AppServer]) -> None:
    srv = library("sections")
    problems: list[str] = []
    page = device(browser, srv, problems)
    s = meta(page)
    put(page, srv, "t00000001", "Morning comes | home", s["first_beat"])
    edit(page)
    typed_row(page).locator(".wt", has_text="comes").click()
    expect(page.get_by_test_id("move-word")).to_have_value("1")  # the word tapped
    expect(page.get_by_test_id("move-where")).to_have_text("“comes”: bar 1, beat 3")
    page.locator('[data-testid=move-slot][data-at="%s"]' % (s["first_beat"] + 3.5)).click()
    expect(page.get_by_test_id("toast")).to_contain_text("Moved “comes” to bar 1, the and of 4.")
    words = typed_entries(srv)["t00000001"]["lines"][0]["words"]
    assert words[1]["at"] == s["first_beat"] + 3.5 and words[1]["start"] == typed.beat_time(s, s["first_beat"] + 3.5)
    expect(page.get_by_test_id("move-where")).to_have_text("“comes”: bar 1, the and of 4")  # still open
    page.get_by_test_id("toast-action").click()  # Undo
    # Waited for on the page: the word back on beat 3 as the sheet draws it (the row was there before the Undo too).
    back = s["first_beat"] + 2
    until(page, f"((Woodshed.app.wordFixes().t00000001 || {{}}).lines || [{{words: []}}])[0].words[1]?.at === {back}")
    assert typed_entries(srv)["t00000001"]["lines"][0]["words"][1]["at"] == s["first_beat"] + 2
    assert problems == []


def test_half_a_beat_earlier_and_later(browser: Browser, library: Callable[[str], app.AppServer]) -> None:
    srv = library("sections")
    problems: list[str] = []
    page = device(browser, srv, problems)
    s = meta(page)
    put(page, srv, "t00000001", "Morning comes | home", s["first_beat"])
    edit(page)
    typed_row(page).locator(".wt", has_text="home").click()
    later = page.get_by_test_id("move-later")
    expect(later).to_have_attribute("aria-label", "Half a beat later")
    later.click()
    expect(page.get_by_test_id("move-where")).to_have_text("“home”: bar 2, the and of 1")
    expect(page.get_by_test_id("move-later")).to_be_focused()  # the keyboard stays on the button
    assert typed_entries(srv)["t00000001"]["lines"][0]["words"][2]["at"] == s["first_beat"] + 4.5
    page.get_by_test_id("move-earlier").click()
    page.get_by_test_id("move-earlier").click()
    expect(page.get_by_test_id("move-where")).to_have_text("“home”: bar 1, the and of 4")
    assert problems == []


def test_a_placed_word_moves_too_and_its_line_is_fixed_by_hand(
    browser: Browser, library: Callable[[str], app.AppServer]
) -> None:
    srv = library("lyrics")
    problems: list[str] = []
    page = device(browser, srv, problems)
    edit(page)
    before = json.loads((srv.library.root / "Pop.woodshed" / lyrics.LYRICS).read_text())["lines"][0]["words"]
    open_line(page, 0, "comes")
    expect(page.get_by_test_id("move-word")).to_have_value("1")
    page.get_by_test_id("move-later").click()
    expect(line(page, 0)).to_have_class(re.compile(r"\bedited\b"))
    key = lyrics.words_key(json.loads((srv.library.root / "Pop.woodshed" / lyrics.LYRICS).read_text()))
    e = srv.library.corrections("Pop.woodshed", "a1b2c3", None, key)["words"]["lines"]["0"]
    got = e["lines"][0]["words"]
    assert got[0] == before[0] and got[2:] == before[2:]  # the other words exactly where they were
    assert got[1]["start"] > before[1]["start"]
    assert problems == []


def test_m_moves_a_word_from_the_keyboard_and_enter_still_opens_the_editor(
    browser: Browser, library: Callable[[str], app.AppServer]
) -> None:
    srv = library("sections")
    problems: list[str] = []
    page = device(browser, srv, problems)
    s = meta(page)
    put(page, srv, "t00000001", "Morning comes | home", s["first_beat"])
    edit(page)
    row = typed_row(page)
    expect(row).to_have_attribute("aria-label", re.compile(r", typed$"))
    row.focus()
    page.keyboard.press("Enter")
    expect(page.get_by_test_id("typed-field")).to_be_focused()
    expect(page.get_by_test_id("typed-field")).to_have_value("Morning comes | home")
    page.keyboard.press("Escape")
    expect(row).to_be_focused()
    page.keyboard.press("m")
    expect(page.get_by_test_id("move-word")).to_be_focused()
    page.get_by_test_id("move-word").select_option("2")
    page.keyboard.press("Tab")
    page.keyboard.press("Tab")
    expect(page.get_by_test_id("move-later")).to_be_focused()
    page.keyboard.press("Enter")
    expect(page.get_by_test_id("move-where")).to_have_text("“home”: bar 2, the and of 1")
    assert typed_entries(srv)["t00000001"]["lines"][0]["words"][2]["at"] == s["first_beat"] + 4.5
    assert page.locator("#sheet [role=button] [role=button]").count() == 0
    expect(page.get_by_test_id("move-ruler")).to_have_attribute("aria-hidden", "true")
    expect(page.get_by_test_id("typed-say")).to_have_attribute("aria-live", "polite")
    page.keyboard.press("Escape")
    page.get_by_test_id("edit-done").click()
    row.focus()
    page.keyboard.press("m")  # outside edit mode: nothing
    expect(page.get_by_test_id("line-editor")).to_be_hidden()
    assert problems == []


def test_a_move_into_the_next_line_is_refused_and_said(
    browser: Browser, library: Callable[[str], app.AppServer]
) -> None:
    srv = library("sections")
    problems: list[str] = []
    page = device(browser, srv, problems)
    s = meta(page)
    put(page, srv, "t00000001", "Morning comes", s["first_beat"])
    put(page, srv, "t00000002", "home", s["first_beat"] + 4)
    expect(typed_row(page)).to_have_count(2)
    edit(page)
    typed_row(page).first.locator(".wt", has_text="comes").click()
    page.locator('[data-testid=move-slot][data-at="%s"]' % (s["first_beat"] + 4)).click()
    expect(page.get_by_test_id("move-where")).to_contain_text("The next line starts here: join the lines first.")
    assert typed_entries(srv)["t00000001"]["lines"][0]["words"][1]["at"] == s["first_beat"] + 2
    assert problems == []


# The same words everywhere; the band; the keyboard and the phone; French.


def test_the_stage_and_the_chordpro_read_typed_lines(browser: Browser, library: Callable[[str], app.AppServer]) -> None:
    srv = library("sections")
    problems: list[str] = []
    page = device(browser, srv, problems)
    s = meta(page)
    put(page, srv, "t00000001", "Hello stum- ble | world", s["first_beat"])
    expect(typed_row(page)).to_have_count(1)
    spaced = page.evaluate(
        "[...document.querySelectorAll('#sheet .lline[data-key] .lw')].map((w) => [w.querySelector('.wt').textContent,"
        " !!w.nextSibling && w.nextSibling.nodeType === 3 && /\\s/.test(w.nextSibling.textContent)])"
    )
    assert spaced[:3] == [["Hello", True], ["stum-", False], ["ble", False]]  # "stum-" drawn joined to "ble"
    text = chordpro(page)
    assert re.search(r"\[[A-G][^\]]*\]Hello stum(\[[^\]]+\])?ble \[[A-G][^\]]*\]world", text), text
    page.get_by_test_id("stage-open").click()
    page.evaluate("Woodshed.app.seekBar(0)")
    expect(page.get_by_test_id("stage-line").first).to_contain_text("Hello")
    assert problems == []


def test_words_back_to_the_placement_leaves_the_typed_lines(
    browser: Browser, library: Callable[[str], app.AppServer]
) -> None:
    srv = library("lyrics")
    problems: list[str] = []
    page = device(browser, srv, problems)
    s = meta(page)
    put(page, srv, "t00000001", "la la", s["first_beat"] + 24)
    edit(page)
    open_line(page, 0)
    save(page, "Morning comes in on the harbor road, yes")
    asked: list[str] = []

    def answer(d: Any) -> None:
        asked.append(d.message)
        d.accept()

    page.on("dialog", answer)
    page.get_by_test_id("words-untype-all").click()
    expect(line(page, 0)).to_contain_text("harbour")
    assert asked == ["Take back 1 fixed line, for the whole band?"]
    expect(typed_row(page)).to_have_count(1)
    assert set(typed_entries(srv)) == {"t00000001"}
    assert problems == []


def test_the_band_sees_a_typed_line_without_reloading(
    browser: Browser, library: Callable[[str], app.AppServer]
) -> None:
    srv = library("sections")
    problems: list[str] = []
    a = device(browser, srv, problems)
    b = device(browser, srv, problems)
    edit(a)
    a.locator('#sheet .bar[data-bar="0"]').click()
    type_line(a, "Morning comes")
    expect(typed_row(b)).to_have_count(1, timeout=3000)
    assert words_of(typed_row(b)) == "Morning comes"
    assert problems == []


@pytest.mark.tablet
def test_on_a_phone_the_keyboard_up_keeps_the_field_its_keys_and_save(
    browser: Browser, library: Callable[[str], app.AppServer]
) -> None:
    srv = library("lyrics")
    problems: list[str] = []
    page = device(browser, srv, problems, (390, 844), has_touch=True, is_mobile=True)
    edit(page)
    page.get_by_test_id("sheet").get_by_test_id("type-line-here").click()
    field = page.get_by_test_id("typed-field")
    field.fill("Morning")
    page.get_by_test_id("typed-keys").get_by_role("button", name="Bar line").click()
    expect(field).to_have_value("Morning |")
    expect(field).to_be_focused()
    page.set_viewport_size({"width": 390, "height": 500})  # the keyboard up
    page.wait_for_timeout(300)
    for el in (field, page.get_by_test_id("typed-keys"), page.get_by_test_id("typed-save")):
        box = el.bounding_box()
        assert box is not None and box["y"] >= 0 and box["y"] + box["height"] <= 500, box
        assert box["height"] >= 40 or el is field
    assert problems == []


def test_the_typed_line_editor_in_french(browser: Browser, library: Callable[[str], app.AppServer]) -> None:
    srv = library("lyrics")
    problems: list[str] = []
    page = device(browser, srv, problems, locale="fr-FR")
    page.get_by_test_id("edit-chart").click()
    page.get_by_test_id("sheet").get_by_test_id("type-line-here").click()
    ed = page.get_by_test_id("line-editor")
    expect(ed.locator("h3")).to_contain_text("Nouvelle ligne")
    page.get_by_test_id("typed-field").fill("Hold me now")
    expect(page.get_by_test_id("typed-read")).to_have_text(
        "Mesure 8\u00a0: «\u00a0Hold\u00a0» sur 1, «\u00a0me\u00a0» sur 2, «\u00a0now\u00a0» sur 3."
    )
    expect(ed.get_by_test_id("typed-tip")).to_contain_text("barre de mesure")
    page.get_by_test_id("typed-field").press("Enter")
    expect(typed_row(page).locator(".typed-mark")).to_have_text("tapée")
    typed_row(page).locator(".wt", has_text="now").click()
    expect(page.get_by_test_id("move-later")).to_have_attribute("aria-label", "Un demi-temps plus tard")
    expect(page.get_by_test_id("move-where")).to_have_text("«\u00a0now\u00a0»\u00a0: mesure 8, temps 3")
    page.get_by_test_id("move-later").click()
    expect(page.get_by_test_id("move-where")).to_have_text(
        "«\u00a0now\u00a0»\u00a0: mesure 8, le «\u00a0et\u00a0» du 3"
    )
    assert problems == []


@pytest.mark.tablet
def test_play_mode_keeps_its_clicks_and_keys_with_typed_lines(
    browser: Browser, library: Callable[[str], app.AppServer]
) -> None:
    srv = library("sections")
    problems: list[str] = []
    page = device(browser, srv, problems)
    s = meta(page)
    put(page, srv, "t00000001", "Morning comes | home", s["first_beat"])
    expect(typed_row(page).locator(".typed-mark")).to_have_count(0)  # nothing marks a typed line in play mode
    typed_row(page).locator(".wt", has_text="home").click()  # a word seeks
    expect(page.get_by_test_id("line-editor")).to_be_hidden()
    until(page, f"Math.abs(Woodshed.app.transport.time - {typed.beat_time(s, s['first_beat'] + 4)}) < 0.3")
    assert problems == []


def test_a_pickup_starts_a_bar_earlier(browser: Browser, library: Callable[[str], app.AppServer]) -> None:
    srv = library("lyrics")
    problems: list[str] = []
    page = device(browser, srv, problems)
    edit(page)
    page.get_by_test_id("type-line-here").click()  # bar 8
    ed = page.get_by_test_id("line-editor")
    page.get_by_test_id("typed-field").fill("Hold me | now")
    expect(page.get_by_test_id("typed-read")).to_contain_text("Past the song's last bar.")
    page.get_by_test_id("typed-earlier").click()
    expect(ed.locator("h3 small")).to_contain_text("from bar 7")
    expect(page.get_by_test_id("typed-read")).to_have_text(
        "Bar 7: \u201cHold\u201d on 1, \u201cme\u201d on 3. Bar 8: \u201cnow\u201d on 1."
    )
    expect(page.get_by_test_id("typed-field")).to_be_focused()
    page.get_by_test_id("typed-field").press("Enter")
    expect(ed).to_be_hidden(timeout=20000)
    ((_, entry),) = typed_entries(srv).items()
    s = meta(page)
    assert entry["lines"][0]["words"][0]["at"] == s["first_beat"] + 24
    assert problems == []


def test_the_read_back_is_said_once_typing_pauses_and_a_refusal_at_once(
    browser: Browser, library: Callable[[str], app.AppServer]
) -> None:
    srv = library("lyrics")
    problems: list[str] = []
    page = device(browser, srv, problems)
    edit(page)
    page.get_by_test_id("type-line-here").click()
    say = page.get_by_test_id("typed-say")
    page.get_by_test_id("typed-field").press_sequentially("Hold me")
    expect(page.get_by_test_id("typed-read")).to_contain_text("\u201cme\u201d")  # shown at once
    assert "\u201cme\u201d" not in (say.text_content() or "")  # said once typing pauses
    expect(say).to_contain_text("\u201cme\u201d", timeout=2000)
    page.get_by_test_id("typed-field").press_sequentially(" | x")
    expect(say).to_have_text("Past the song's last bar.", timeout=300)  # a refusal is said at once
    assert problems == []


@pytest.mark.tablet
def test_on_a_phone_the_ruler_offers_whole_beats_and_the_toast_stays_above_the_sheet(
    browser: Browser, library: Callable[[str], app.AppServer]
) -> None:
    srv = library("sections")
    problems: list[str] = []
    page = device(browser, srv, problems, (390, 844), has_touch=True, is_mobile=True)
    s = meta(page)
    put(page, srv, "t00000001", "Morning comes | home", s["first_beat"])
    edit(page)
    typed_row(page).locator(".wt", has_text="home").click()
    expect(page.get_by_test_id("move-word")).to_be_focused()  # a tapped word: the move group, no keyboard
    ats = page.eval_on_selector_all("[data-testid=move-slot]", "(els) => els.map((e) => +e.dataset.at)")
    assert ats and all(a == int(a) for a in ats)  # whole beats under a finger; half beats with the buttons
    for tid in ("move-word", "move-earlier", "move-later"):
        box = page.get_by_test_id(tid).bounding_box()
        assert box is not None and round(box["height"]) >= 44, tid
    page.get_by_test_id("move-later").click()
    toast = page.get_by_test_id("toast")
    expect(toast).to_contain_text("Moved")
    t, e = toast.bounding_box(), page.get_by_test_id("line-editor").bounding_box()
    assert t is not None and e is not None and t["y"] + t["height"] <= e["y"], (t, e)
    assert problems == []


def test_a_pickup_stays_in_its_part(browser: Browser, library: Callable[[str], app.AppServer]) -> None:
    srv = library("lyrics-verse-only")  # Verse 1 bars 1 to 4, Chorus 1 bars 5 to 8
    problems: list[str] = []
    page = device(browser, srv, problems)
    edit(page)
    page.get_by_test_id("sheet").get_by_test_id("type-line-here").first.click()  # the chorus, from bar 5
    expect(page.get_by_test_id("line-editor").locator("h3 small")).to_contain_text("Chorus 1")
    expect(page.get_by_test_id("typed-earlier")).to_be_disabled()  # bar 4 is the verse's
    assert problems == []
