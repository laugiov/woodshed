"""The line the singer sings, on stage (spec 016, round 5): always on screen, at the top of the words, at every
width; stopped, the line to sing next shown first with "Next:", lit only once the cursor is inside it."""

from __future__ import annotations

import json
from typing import Any

import pytest
from playwright.sync_api import expect

from tests.page.conftest import lyrics_for

VIEWPORTS = [(390, 844), (844, 390), (820, 1180), (1024, 1366)]


def long_words(song: dict[str, Any]) -> dict[str, Any]:
    """The words of `lyrics_for` with longer words: a line of some 80 letters, that wraps on a phone."""
    data = lyrics_for(song)
    for line in data["lines"]:
        line["words"] = [{**w, "text": w["text"].rstrip(",") + "-heart"} for w in line["words"]]
        line["text"] = " ".join(w["text"] for w in line["words"])
    return data


def set_words(o: Any, data: dict[str, Any]) -> None:
    o.js(f"Woodshed.app.words = Woodshed.lyrics(Woodshed.current, {json.dumps(data)})")
    o.js("Woodshed.app.store.set({corrections: Woodshed.app.store.get().corrections + 1})")  # drawn again


def on_stage(o: Any, inst: str = "Voice") -> None:
    # Stage mode asks for full screen, and headless Firefox then grows the window to the screen: the layout is
    # checked at the size each test sets (on a real phone full screen is the phone's own screen).
    o.js("Element.prototype.requestFullscreen = function () { return Promise.resolve(); }")
    o.page.locator("#instruments button", has_text=inst).click()
    o.page.get_by_test_id("stage-open").click()
    expect(o.page.get_by_test_id("stage")).to_be_visible()


def at(o: Any, t: float, playing: bool) -> None:
    """The stage at time `t` (seconds), as while playing or stopped."""
    o.js("([t, playing]) => { Woodshed.app.seekTime(t); Woodshed.app.store.set({ playing }); }", [t, playing])
    o.page.wait_for_timeout(150)


def sized(o: Any, width: int, height: int) -> None:
    """The viewport resized, and the page laid out at that size (Firefox applies it a moment later)."""
    o.page.set_viewport_size({"width": width, "height": height})
    o.page.wait_for_function("([w, h]) => innerWidth === w && innerHeight === h", arg=[width, height])


def bar_start(o: Any, u: int) -> float:
    start: float = o.js(f"Woodshed.current.bars[{u}].start")
    return start


def shifted(line: dict[str, Any], by: float) -> None:
    line["words"] = [
        w if w["start"] is None else {**w, "start": w["start"] + by, "end": w["end"] + by} for w in line["words"]
    ]


def first_line(o: Any) -> Any:
    return o.page.get_by_test_id("stage-line").first


def inside(inner: dict[str, float] | None, outer: dict[str, float] | None) -> bool:
    assert inner and outer
    return (
        inner["x"] >= outer["x"] - 1
        and inner["y"] >= outer["y"] - 1
        and inner["x"] + inner["width"] <= outer["x"] + outer["width"] + 1
        and inner["y"] + inner["height"] <= outer["y"] + outer["height"] + 1
    )


@pytest.mark.parametrize("words", ["lyrics", "long"])
@pytest.mark.parametrize("inst", ["Voice", "Guitar"])
@pytest.mark.parametrize(("width", "height"), VIEWPORTS)
def test_the_sung_line_is_on_screen_at_the_top_of_the_words(
    open_page: Any, width: int, height: int, inst: str, words: str
) -> None:
    o = open_page("pop", variant="lyrics")
    sized(o, width, height)
    if words == "long":
        set_words(o, long_words(o.js("Woodshed.current.song")))
    on_stage(o, inst)
    at(o, bar_start(o, 1) + 0.1, True)  # mid-line, playing
    sung = o.page.locator("#stLyrics .st-line.now")
    expect(sung).to_have_count(1)
    expect(sung).to_contain_text("Morning")
    box = sung.bounding_box()
    assert box and box["height"] > 0 and box["width"] > 0
    assert inside(box, {"x": 0, "y": 0, "width": width, "height": height})  # in the viewport
    assert inside(box, o.page.get_by_test_id("stage-lyrics").bounding_box())  # in the words column
    assert inside(box, o.page.locator("#stage .stage-mid").bounding_box())  # not clipped by the stage
    # At the top of the words: the first thing in the column (no key change, no part name here).
    column = o.page.get_by_test_id("stage-lyrics").bounding_box()
    assert column and box["y"] - column["y"] < 40
    if inst == "Voice" or width > 700:  # the words column from the top of the stage, not centred in it
        mid = o.page.locator("#stage .stage-mid").bounding_box()
        assert mid and abs(column["y"] - mid["y"]) < 2
        if inst == "Voice":  # and from its left edge, not centred on short lines
            assert abs(column["x"] - mid["x"]) < 2
    expect(o.page.locator("#stLyrics > *").first).to_have_class("st-line now")
    expect(o.page.locator("#stLyrics .st-progress")).to_have_count(1)  # its progress bar, under it


def test_the_chart_panel_still_gives_way_to_the_words_for_a_singer_on_a_phone(open_page: Any) -> None:
    o = open_page("pop", variant="lyrics")
    sized(o, 390, 844)
    o.page.locator("#instruments button", has_text="Voice").click()
    expect(o.page.locator(".panel > .now")).to_be_hidden()  # the big chord of the chart: the words first


def test_stopped_at_the_start_the_first_line_says_next(open_page: Any) -> None:
    o = open_page("pop", variant="lyrics")
    data = lyrics_for(o.js("Woodshed.current.song"), 1)  # sung from bar 2: an intro bar before
    set_words(o, data)
    on_stage(o)
    at(o, 0, False)
    expect(o.page.get_by_test_id("stage-next-label")).to_have_text("Next:")
    expect(first_line(o)).to_have_class("st-line ready")
    expect(first_line(o)).to_contain_text("Morning")
    expect(o.page.locator("#stLyrics .st-progress")).to_have_count(0)  # not started: no progress
    # The label comes right before the line it names.
    expect(o.page.locator("#stLyrics .st-next-label + .st-line")).to_have_count(1)


def test_stopped_inside_a_line_it_is_lit_with_its_progress(open_page: Any) -> None:
    o = open_page("pop", variant="lyrics")
    on_stage(o)
    at(o, bar_start(o, 1) + 0.1, False)
    expect(first_line(o)).to_have_class("st-line now")
    expect(o.page.locator("#stLyrics .st-progress")).to_have_count(1)
    expect(o.page.get_by_test_id("stage-next-label")).to_have_count(0)


def test_stopped_after_a_line_ended_the_next_one_says_next(open_page: Any) -> None:
    o = open_page("pop", variant="lyrics")
    on_stage(o)
    end = o.js("Woodshed.app.words.lines[0].end")
    at(o, (end + bar_start(o, 4)) / 2, False)  # after the last word of line 1, before line 2
    expect(o.page.get_by_test_id("stage-next-label")).to_have_text("Next:")
    expect(first_line(o)).to_have_class("st-line ready")
    expect(first_line(o)).to_contain_text("radio")
    expect(o.page.locator("#stLyrics .st-line.now")).to_have_count(0)


def test_while_playing_between_lines_nothing_says_next(open_page: Any) -> None:
    o = open_page("pop", variant="lyrics")
    data = lyrics_for(o.js("Woodshed.current.song"), 1)
    set_words(o, data)
    on_stage(o)
    at(o, 0.05, True)
    expect(o.page.get_by_test_id("stage-next-label")).to_have_count(0)  # as before: the lines wait
    expect(first_line(o)).to_have_class("st-line later")


def _chorus_a_bar_late(o: Any, hold: bool = False) -> None:
    """lyrics-named (Verse 1 bars 1-4, Chorus 1 from bar 5) with the chorus line a bar into the chorus; `hold`:
    the verse's last word held into the chorus."""
    data = json.loads((o.folder / "lyrics.json").read_text())
    bar = bar_start(o, 1) - bar_start(o, 0)
    shifted(data["lines"][1], bar)
    if hold:
        data["lines"][0]["words"][-1]["end"] = bar_start(o, 4) + 0.3 * bar
    set_words(o, data)


@pytest.mark.parametrize("hold", [False, True])
def test_part_next_while_stopped_shows_the_part_first_line_with_next(open_page: Any, hold: bool) -> None:
    o = open_page("pop", variant="lyrics-named")
    _chorus_a_bar_late(o, hold)
    on_stage(o)
    at(o, bar_start(o, 1), False)
    o.page.get_by_test_id("stage-next-part").click()
    expect(o.page.get_by_test_id("stage-section")).to_have_text("Chorus 1")
    expect(o.page.get_by_test_id("stage-next-label")).to_have_text("Next:")
    expect(first_line(o)).to_have_class("st-line ready")
    expect(first_line(o)).to_contain_text("radio")  # the chorus's line, not the verse's held word


def test_part_back_while_stopped_shows_the_part_first_line(open_page: Any) -> None:
    o = open_page("pop", variant="lyrics-named")
    on_stage(o)
    at(o, bar_start(o, 6), False)  # inside the chorus, stopped
    o.page.get_by_test_id("stage-prev").click()  # back to the start of this part, where its first line starts
    expect(o.page.get_by_test_id("stage-section")).to_have_text("Chorus 1")
    expect(first_line(o)).to_have_class("st-line now")  # the cursor on its first word: being sung
    expect(first_line(o)).to_contain_text("radio")


@pytest.mark.parametrize("beats", [0.5, 3])
def test_part_next_while_stopped_lights_a_pickup_line(open_page: Any, beats: float) -> None:
    o = open_page("pop", variant="lyrics-named")
    data = json.loads((o.folder / "lyrics.json").read_text())
    beat = (bar_start(o, 1) - bar_start(o, 0)) / o.js("Woodshed.current.per")
    shifted(data["lines"][1], -beat * beats)  # the chorus line starts on the and of 4, or on beat 2, before it
    set_words(o, data)
    on_stage(o)
    at(o, bar_start(o, 1), False)
    o.page.get_by_test_id("stage-next-part").click()
    expect(first_line(o)).to_have_class("st-line now")  # the cursor is inside it: being sung
    expect(first_line(o)).to_contain_text("radio")
    expect(o.page.get_by_test_id("stage-next-label")).to_have_count(0)


@pytest.mark.parametrize("inst", ["Voice", "Guitar"])
def test_the_line_to_sing_next_has_the_sung_size_and_the_label_is_muted(open_page: Any, inst: str) -> None:
    o = open_page("pop", variant="lyrics")
    data = lyrics_for(o.js("Woodshed.current.song"), 1)
    set_words(o, data)
    on_stage(o, inst)
    size = "(sel) => getComputedStyle(document.querySelector(sel)).fontSize"
    colour = "(sel) => getComputedStyle(document.querySelector(sel)).color"
    token = """(name) => { const el = document.createElement('i'); el.style.color = `var(${name})`;
      document.getElementById('stage').append(el); const c = getComputedStyle(el).color; el.remove(); return c; }"""
    at(o, bar_start(o, 2), True)
    sung = o.js(size, "#stLyrics .st-line.now .lwords")
    at(o, 0, False)
    assert o.js(size, "#stLyrics .st-line.ready .lwords") == sung
    for theme in ("dark", "light"):
        o.js(f"document.documentElement.dataset.theme = '{theme}'")
        assert o.js(colour, "#stLyrics .st-next-label") == o.js(token, "--muted") != o.js(token, "--warn")
        assert o.js(colour, "#stLyrics .st-line.ready") == o.js(token, "--ink")
        assert o.js("getComputedStyle(document.querySelector('#stLyrics .st-line.ready')).opacity") == "1"


@pytest.mark.browser_context_args(locale="fr-FR")
def test_next_in_french(open_page: Any) -> None:
    o = open_page("pop", variant="lyrics")
    data = lyrics_for(o.js("Woodshed.current.song"), 1)
    set_words(o, data)
    on_stage(o, "Voix")
    at(o, 0, False)
    expect(o.page.get_by_test_id("stage-next-label")).to_have_text("Ensuite\u00a0:")


def stage_order(o: Any) -> list[str]:
    """What the words column shows, top down: key, part, label, now, ready, later."""
    js = """[...document.getElementById('stLyrics').children].map((el) =>
      el.matches('[data-testid=stage-key-words]') ? 'key' : el.matches('[data-testid=stage-next-label]') ? 'label'
      : el.classList.contains('st-next-part') ? 'part' : el.classList.contains('st-progress') ? 'progress'
      : ['now', 'ready', 'later'].find((c) => el.classList.contains(c)) || el.className)"""
    order: list[str] = o.js(js)
    return order


def test_stopped_before_a_key_change_the_key_line_comes_first_then_next(open_page: Any) -> None:
    o = open_page("lift", variant="lyrics-lift")
    data = json.loads((o.folder / "lyrics.json").read_text())
    bars = o.js("Woodshed.current.bars.length")
    data["sections"] = [{"name": "Verse 1", "role": "verse", "letter": "A", "start": 0, "end": bars}]  # one part
    set_words(o, data)
    on_stage(o)
    at(o, bar_start(o, 13) + 0.1, False)  # the line over bars 15-18 next, the key changing inside it
    order = stage_order(o)
    assert order[:3] == ["key", "label", "ready"], order


def test_stopped_at_a_loop_s_start_the_loop_s_first_line_comes_next(open_page: Any) -> None:
    o = open_page("pop", variant="lyrics")
    on_stage(o)
    data = lyrics_for(o.js("Woodshed.current.song"), 1)
    set_words(o, data)
    o.js("Woodshed.app.setLoop([0, 3], true)")
    at(o, bar_start(o, 0) + 0.05, False)  # at the loop's start, stopped (where a wrap lands)
    expect(first_line(o)).to_have_class("st-line ready")
    expect(o.page.get_by_test_id("stage-next-label")).to_have_count(1)


def test_a_song_with_no_parts_still_says_next(open_page: Any) -> None:
    o = open_page("pop", variant="lyrics-nosections")
    on_stage(o)
    at(o, 0.0, False)
    expect(o.page.get_by_test_id("stage-next-label")).to_have_count(1)
    expect(first_line(o)).to_have_class("st-line ready")


def test_next_reads_from_a_mic_stand_and_stands_apart_from_the_chords(open_page: Any) -> None:
    o = open_page("pop", variant="lyrics")
    sized(o, 390, 844)
    data = lyrics_for(o.js("Woodshed.current.song"), 1)
    set_words(o, data)
    on_stage(o)
    at(o, 0.0, False)
    label = o.page.get_by_test_id("stage-next-label")
    size = label.evaluate("(el) => parseFloat(getComputedStyle(el).fontSize)")
    assert size >= 15
    gap = o.js("""(() => { const l = document.querySelector('[data-testid=stage-next-label]').getBoundingClientRect();
      const chords = document.querySelector('#stLyrics .st-line .lc') || document.querySelector('#stLyrics .st-line');
      const c = chords.getBoundingClientRect();
      return c.top - l.bottom; })()""")
    assert gap >= 4
