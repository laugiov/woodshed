"""The words on the chart and on the stand: chords above the words, bar lines, stage mode."""

from __future__ import annotations

import json
import re
from typing import Any

import pytest
from playwright.sync_api import expect

from tests.page.test_page import state, until
from woodshed import lyrics


def test_the_chart_shows_the_words_with_their_chords(open_page: Any) -> None:
    o = open_page("pop", variant="lyrics")
    expect(o.page.get_by_test_id("sheet-lyrics")).to_have_attribute("aria-pressed", "true")  # guitar: the words
    lines = o.page.get_by_test_id("lyric-line")
    expect(lines).to_have_count(2)  # the line not sung in this recording is not shown
    first_chord = o.js("Woodshed.current.chordName(Woodshed.current.bars[0].chords[0], 0)")
    word = lines.first.locator(".lw.has").first
    expect(word.locator(".lc")).to_have_text(first_chord)
    assert "Morning" in word.inner_text()
    expect(lines.first.locator(".bl")).to_have_count(4)  # a bar line, numbered, at each bar
    expect(lines.first.locator(".nb")).to_have_count(4)  # each bar kept whole
    # A screen reader reads the words, not the chord names between them.
    assert lines.first.locator(".lc").first.get_attribute("aria-hidden") == "true"
    expect(lines.nth(1)).to_have_class("lline check")  # placed by order: to check
    expect(lines.nth(1)).to_contain_text("(hums)")  # backing vocals apart


def test_bars_no_line_holds_stay_a_grid_and_every_bar_shows_once(open_page: Any) -> None:
    o = open_page("pop", variant="lyrics")
    n = o.js("Woodshed.current.bars.length")
    numbers = [int(x) for x in o.page.locator(".lline .bl i, #sheet .bar[data-free] .num").all_inner_texts()]
    assert numbers == list(range(1, n + 1))  # in order, none twice, none lost
    # The chords after the last line are bars of the grid, not gaps hanging on the last line.
    expect(o.page.get_by_test_id("lyric-line").nth(1).locator(".lw.gap")).to_have_count(0)
    free = o.page.locator("#sheet .bar[data-free]")
    expect(free).to_have_count(1)  # the last line holds the bar after it (a held word): bar 8 is free
    free.first.click()
    assert o.js("Woodshed.app.store.get().beat") == 7 * o.js("Woodshed.current.per")


def test_lines_outside_every_section_are_shown(open_page: Any) -> None:
    o = open_page("pop", variant="lyrics-nosections")
    expect(o.page.get_by_test_id("lyric-line")).to_have_count(2)
    expect(o.page.get_by_test_id("section")).to_have_count(0)


def test_the_time_of_a_line_is_a_button(open_page: Any) -> None:
    o = open_page("pop", variant="lyrics")
    o.page.get_by_test_id("lyric-line").nth(1).locator("button.t").focus()
    o.page.keyboard.press("Enter")
    assert state(o)["audioTime"] == pytest.approx(o.js("Woodshed.app.words.lines[1].start"), abs=0.02)


def test_a_word_takes_you_to_its_time_and_the_line_follows(open_page: Any) -> None:
    o = open_page("pop", variant="lyrics")
    o.page.get_by_test_id("lyric-line").nth(1).locator(".lw").first.click()
    start = o.js("Woodshed.app.words.lines[1].start")
    assert state(o)["audioTime"] == pytest.approx(start, abs=0.02)
    expect(o.page.get_by_test_id("lyric-line").nth(1)).to_have_class("lline check cur")


def test_bass_and_drums_start_on_the_grid(open_page: Any) -> None:
    o = open_page("pop", variant="lyrics")
    o.page.locator("#instruments button", has_text="Bass").click()
    expect(o.page.get_by_test_id("sheet-grid")).to_have_attribute("aria-pressed", "true")
    expect(o.page.get_by_test_id("lyric-line")).to_have_count(0)
    o.page.get_by_test_id("sheet-lyrics").click()
    expect(o.page.get_by_test_id("lyric-line")).to_have_count(2)


@pytest.mark.parametrize(("inst", "layout"), [("Guitar", "st-lyrics"), ("Voice", "st-voice"), ("Drums", None)])
def test_stage_mode_with_the_words(open_page: Any, inst: str, layout: str | None) -> None:
    o = open_page("pop", variant="lyrics")
    o.page.locator("#instruments button", has_text=inst).click()
    o.page.get_by_test_id("stage-open").click()
    o.js("Woodshed.app.seekBar(1)")
    stage = o.page.get_by_test_id("stage")
    if layout is None:
        expect(o.page.get_by_test_id("stage-lyrics")).to_be_hidden()
        return
    expect(stage).to_have_class(f"stage {layout}")
    lines = o.page.get_by_test_id("stage-line")
    expect(lines.first).to_contain_text("Morning")
    expect(lines.nth(1)).to_contain_text("radio")  # the next line already in view
    expect(lines.first).to_have_class("st-line now")
    # A word on the stand is not a control: a touch does not move the song.
    expect(o.page.locator("#stLyrics [data-seek]")).to_have_count(0)
    # After the last line (the bars of the ending), no line is lit.
    o.js("Woodshed.app.seekBar(Woodshed.current.bars.length - 1)")
    expect(o.page.locator("#stLyrics .st-line.now")).to_have_count(0)


PAGE_PLACES = """(() => {
  const w = Woodshed.app.words;
  return w.place(w.changes()).map((p) => ({
    bar: p.bar, index: p.index, line: p.li === null ? null : w.lines[p.li].index, word: p.wi, push: p.push,
  }));
})()"""


def _placed_like_python(o: Any, data: dict[str, Any]) -> None:
    nan = float("nan")
    song = o.js("Woodshed.current.song")
    words = {
        li: [(nan if w["start"] is None else w["start"], nan if w["end"] is None else w["end"]) for w in ln["words"]]
        for li, ln in enumerate(data["lines"])
        if ln["sung"]
    }
    python = lyrics.place_chords(lyrics.chord_changes(song), words, song["bpm"], song["beats_per_bar"])
    assert o.js(PAGE_PLACES) == [{k: p[k] for k in ("bar", "index", "line", "word", "push")} for p in python]


def test_the_page_places_chords_on_words_like_python(open_page: Any) -> None:
    o = open_page("pop", variant="lyrics")
    _placed_like_python(o, json.loads((o.folder / "lyrics.json").read_text()))


def test_a_word_with_no_time_keeps_its_place_and_parity_holds(open_page: Any) -> None:
    o = open_page("pop", variant="lyrics")
    data = json.loads((o.folder / "lyrics.json").read_text())
    data["lines"][0]["words"][2].update(start=None, end=None)  # "in": the voice gave it no time
    o.js(f"Woodshed.app.words = Woodshed.lyrics(Woodshed.current, {json.dumps(data)})")
    first = o.js("Woodshed.app.words.rows().rows[0].bars.flatMap((b) => b.items.map((i) => i.text))")
    assert first[:4] == ["Morning", "comes", "in", "on"]
    _placed_like_python(o, data)


def test_without_words_there_is_no_lyrics_view(open_page: Any) -> None:
    o = open_page("pop")
    expect(o.page.get_by_test_id("sheet-lyrics")).to_have_count(0)
    until(o, "Woodshed.app.words === null")


def test_a_drag_over_sung_bars_loops_them_and_shows_it(open_page: Any) -> None:
    o = open_page("pop", variant="lyrics")
    bars = o.page.get_by_test_id("lyric-line").first.locator(".nb[data-bar]")
    bars.first.evaluate("(el) => el.scrollIntoView({ block: 'center' })")  # clear of the dock
    a, b = bars.nth(0).bounding_box(), bars.nth(2).bounding_box()
    assert a and b
    o.page.mouse.move(a["x"] + 4, a["y"] + a["height"] - 6)
    o.page.mouse.down()
    o.page.mouse.move(b["x"] + 8, b["y"] + b["height"] - 6, steps=6)
    o.page.mouse.up()
    assert o.js("Woodshed.app.store.get().loop") == [0, 2]
    expect(o.page.locator(".lline .nb.inloop")).to_have_count(3)


def test_the_cursor_is_on_a_free_bar_after_switching_to_the_words(open_page: Any) -> None:
    o = open_page("pop", variant="lyrics")
    o.page.get_by_test_id("sheet-grid").click()
    o.js("Woodshed.app.seekBar(7)")
    o.page.get_by_test_id("sheet-lyrics").click()
    expect(o.page.locator('#sheet .bar[data-free][data-bar="7"]')).to_have_class(re.compile(r"\bcur\b"))


def test_a_chord_to_check_that_repeats_the_one_before_keeps_its_button(open_page: Any) -> None:
    o = open_page("pop", variant="lyrics")
    # The first chord of bar 2 made the same as the last of bar 1 (no change), and a doubt.
    ref = o.js(
        """(() => {
          const bars = Woodshed.current.bars;
          const prev = bars[0].chords[bars[0].chords.length - 1];
          Object.assign(bars[1].chords[0], { pc: prev.pc, quality: prev.quality });
          bars[1].chords[0].doubt = { id: 9999, kind: "chord", why: "test", alternatives: [] };
          return "1_0";
        })()"""
    )
    assert "1_0" not in o.js("Woodshed.app.words.changes().map((c) => c.bar + '_' + c.index)")
    o.page.get_by_test_id("sheet-grid").click()
    o.page.get_by_test_id("sheet-lyrics").click()
    expect(o.page.locator(f'.lline .doubt[data-ref="{ref}"]')).to_have_count(1)


def test_the_parts_take_the_names_the_words_gave_them(open_page: Any) -> None:
    o = open_page("pop", variant="lyrics-named")
    heads = o.page.get_by_test_id("section").locator(".sec-name")
    expect(heads).to_have_text(["Verse 1", "Chorus 1"])
    expect(o.page.get_by_test_id("form-chip")).to_have_text(["Verse 1", "Chorus 1"])
    o.page.get_by_test_id("sheet-grid").click()  # the grid shows the same parts
    expect(o.page.get_by_test_id("section").locator(".sec-name")).to_have_text(["Verse 1", "Chorus 1"])
    o.page.get_by_test_id("stage-open").click()
    o.js("Woodshed.app.seekBar(5)")
    expect(o.page.get_by_test_id("stage-section")).to_have_text("Chorus 1")


def part(name: str, start: int, end: int) -> dict[str, Any]:
    return {"name": name, "role": "verse", "letter": "A", "start": start, "end": end}


@pytest.mark.parametrize(
    "bad",
    [
        [part("X", 0, 999)],  # past the last bar
        [part("X", 2, 1)],  # backwards
        [part("X", 0, 4), part("Y", 2, 8)],  # overlapping
        [{"name": 3, "start": 0, "end": 4}],  # not a part
        "Chorus",
    ],
)
def test_damaged_part_names_are_ignored(open_page: Any, bad: Any) -> None:
    o = open_page("pop", variant="lyrics")
    data = json.loads((o.folder / "lyrics.json").read_text())
    names = o.js("Woodshed.app.sections().map((s) => s.name)")
    data["sections"] = bad
    o.js(f"Woodshed.app.words = Woodshed.lyrics(Woodshed.current, {json.dumps(data)})")
    assert o.js("Woodshed.app.sections().map((s) => s.name)") == names


@pytest.mark.parametrize("variant", ["lyrics", "lyrics-named", "lyrics-stacked"])
def test_the_chordpro_from_the_page_has_the_words_like_python(open_page: Any, variant: str) -> None:
    from tests.page.test_page import download
    from woodshed import exports

    o = open_page("pop", variant=variant)
    data = o.js("Woodshed.current.song")
    words = json.loads((o.folder / "lyrics.json").read_text())
    text = download(o, "export-chordpro")
    assert text == exports.chordpro(data, words)
    assert ("Morning comes" in text or variant == "lyrics-stacked") and "{start_of_" in text
    if variant == "lyrics-named":
        assert '{start_of_chorus: label="Chorus 1"}' in text  # the parts as the page names them
    if variant == "lyrics-stacked":
        assert "] [" in text and "][" not in text  # chords apart, never stuck on one syllable
        assert "{comment: check by ear: " in text and "(" in text.split("check by ear: ")[1].split("}")[0]


def test_the_chordpro_carries_a_correction_on_its_word(open_page: Any) -> None:
    from tests.page.test_page import download

    o = open_page("pop", variant="lyrics")
    # The chart as a correction leaves it: the first chord replaced (app.correct applies fixes so).
    o.js("Object.assign(Woodshed.current.bars[0].chords[0], { pc: 9, quality: 'm', fixed: true })")
    assert "[Am]Morning" in download(o, "export-chordpro")


def hard_words(data: dict[str, Any]) -> dict[str, Any]:
    """Words that test every branch of the ChordPro rows: a word without a time, a chord on no word
    inside a line, chords in the bar leading into a line, chords between lines, backing vocals, a
    line that would read as a ChordPro comment or directive."""
    starts = [b["start"] for b in data["bars"]]
    beat = 60 / data["bpm"]
    base: dict[str, Any] = {"tag": None, "block": 0, "backing": [], "sung": True, "check": None}

    def w(text: str, start: float | None, length: float = 0.3) -> dict[str, Any]:
        return {"text": text, "start": start, "end": None if start is None else start + length}

    lines = [
        {
            **base,
            "text": "one two three",
            "words": [w("one", starts[0]), w("two", None), w("three", starts[1] + 2 * beat)],
        },
        {
            **base,
            "text": "#four {five}",
            "backing": ["six"],
            "words": [w("#four", starts[3] + 2 * beat), w("{five}", starts[3] + 3 * beat)],
        },
        {**base, "text": "seven", "words": [w("seven", starts[6] + 2.5 * beat)]},
    ]
    return {"version": 1, "language": "en", "text": "", "chords": [], "lines": lines}


def test_the_chordpro_rows_are_the_same_in_the_page_and_in_python_for_hard_cases(open_page: Any) -> None:
    from woodshed import exports

    o = open_page("pop", variant="lyrics")
    data = o.js("Woodshed.current.song")
    words = hard_words(data)
    page = o.js(f"Woodshed.exports.chordpro(Woodshed.current, Woodshed.lyrics(Woodshed.current, {json.dumps(words)}))")
    python = exports.chordpro(data, words)
    assert page == python
    body = python.split("{start_of_", 1)[1]
    assert "\n#" not in body and "{five}" not in body  # no line read as a comment, no brace as a directive


def test_a_jump_to_the_next_part_does_not_light_the_line_before_it(open_page: Any) -> None:
    o = open_page("pop", variant="lyrics-named")
    data = json.loads((o.folder / "lyrics.json").read_text())
    bar = o.js("Woodshed.current.bars[1].start - Woodshed.current.bars[0].start")
    for w in data["lines"][1]["words"]:  # the chorus line now starts a bar into the chorus
        if w["start"] is not None:
            w["start"], w["end"] = w["start"] + bar, w["end"] + bar
    o.js(f"Woodshed.app.words = Woodshed.lyrics(Woodshed.current, {json.dumps(data)})")
    per = o.js("Woodshed.current.per")
    chorus = o.js("Woodshed.current.bars[4].start")
    ended = o.js(f"Woodshed.app.lineNow({{time: {chorus} - 0.2, beat: {4 * per - 1}}}).now")
    jumped = o.js(f"Woodshed.app.lineNow({{time: {chorus} + 0.1, beat: {4 * per}}}).now")
    assert ended == 0  # the verse's last line still held, in the verse
    assert jumped == -1  # the chorus has started: the verse's line is over, nothing lit yet
