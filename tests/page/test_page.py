"""The practice page in a real browser: what it shows, how it plays, how it reacts."""

from __future__ import annotations

import json
import re
import shutil
import time
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import expect

from woodshed import theory

HOSTILE = '<img src=x onerror="window.pwned=1"></script><script>window.pwned=2</script>'


def until(o: Any, expression: str, timeout: float = 5.0) -> None:
    """Wait for a page expression to be true. Polled from Python: the page's content security
    policy forbids the string evaluation Playwright's own wait_for_function relies on."""
    deadline = time.monotonic() + timeout
    while not o.js(expression):
        if time.monotonic() > deadline:
            raise AssertionError(f"still false after {timeout} s: {expression}")
        o.page.wait_for_timeout(50)


def state(o: Any) -> dict[str, Any]:
    result: dict[str, Any] = o.js("Woodshed.debug()")
    return result


def test_overlays_are_hidden_until_asked_for(open_page: Any) -> None:
    o = open_page("pop")
    for testid in ("stage", "tracks-menu", "help-menu", "doubt-pop", "toast"):
        expect(o.page.get_by_test_id(testid)).to_be_hidden()


def test_a_hostile_title_is_shown_as_text_and_never_runs(open_page: Any) -> None:
    o = open_page("pop", title=HOSTILE)
    expect(o.page.get_by_test_id("title")).to_have_text(HOSTILE)
    assert o.js("window.pwned === undefined")
    assert o.page.title() == HOSTILE + " · woodshed"


def test_the_chart_shows_the_sections_and_repeats_of_the_song(open_page: Any) -> None:
    o = open_page("pop")
    groups = o.js("Woodshed.current.song.groups")
    sections = o.js("Woodshed.current.song.sections")
    heads = o.page.locator("[data-testid=section] .sec-name").all_inner_texts()
    assert heads == [sec["name"] for sec in sections] == o.page.get_by_test_id("form-chip").all_inner_texts()
    repeats = o.page.get_by_test_id("repeat").all_inner_texts()
    assert repeats == ["×" + str(len(g["occurrences"])) for g in groups if len(g["occurrences"]) > 1]
    first = o.js("Woodshed.current.song.bars[0].chords[0]")
    expect(o.page.get_by_test_id("now-chord")).to_have_text(o.js("c => Woodshed.current.chordName(c, 0)", first))


def test_play_pause_and_the_position_follows_the_recording(open_page: Any) -> None:
    o = open_page("pop")
    o.page.get_by_test_id("play").click()
    until(o, "Woodshed.debug().audioTime > 0.8", 5.0)
    s = state(o)
    assert s["playing"] and s["track"] == "mix"
    assert s["beat"] == o.js("t => Woodshed.current.beatAt(t)", s["time"])
    o.page.get_by_test_id("play").click()
    paused = state(o)["audioTime"]
    o.page.wait_for_timeout(300)
    assert not state(o)["playing"] and state(o)["audioTime"] == pytest.approx(paused)


def test_clicking_a_bar_jumps_to_it(open_page: Any) -> None:
    o = open_page("pop")
    o.page.locator('[data-testid=bar][data-bar="2"]').click()
    start = o.js("Woodshed.current.bars[2].start")
    assert state(o)["audioTime"] == pytest.approx(start, abs=0.01)
    expect(o.page.get_by_test_id("pass-info")).to_have_text("bar 3 of 8")  # in the song's only section


def test_switching_tracks_keeps_the_position(open_page: Any) -> None:
    o = open_page("pop")
    o.page.get_by_test_id("play").click()
    until(o, "Woodshed.debug().audioTime > 1.0", 5.0)
    before = state(o)["audioTime"]
    o.page.get_by_test_id("tracks").click()
    o.page.get_by_test_id("track-minus-drums").click()
    playing_tracks = "[...document.querySelectorAll('audio')].filter(a => !a.paused).map(a => a.dataset.track)"
    until(o, f"JSON.stringify({playing_tracks}) === JSON.stringify(['minus-drums'])", 3.0)
    s = state(o)
    assert s["track"] == "minus-drums" and s["audioTime"] >= before - 0.05
    playing = o.js("[...document.querySelectorAll('audio')].filter(a => !a.paused).map(a => a.dataset.track)")
    assert playing == ["minus-drums"]  # one track at a time: nothing to drift


def test_slowing_down_keeps_the_pitch(open_page: Any) -> None:
    o = open_page("pop")
    song_bpm = state(o)["bpm"]
    for _ in range(10):
        o.page.get_by_test_id("slower").click()
    s = state(o)
    assert s["bpm"] == song_bpm - 10
    rate, keep = o.js(
        "(() => { const a = document.querySelector('audio[data-track=mix]');"
        " return [a.playbackRate, a.preservesPitch]; })()"
    )
    assert rate == pytest.approx((song_bpm - 10) / song_bpm) and keep is True
    o.page.get_by_test_id("bpm-reset").click()
    assert state(o)["bpm"] == song_bpm


def test_a_loop_wraps_back_to_its_first_bar(open_page: Any) -> None:
    o = open_page("pop")
    o.page.locator('[data-testid=bar][data-bar="0"]').click()
    o.page.keyboard.press("l")
    s = state(o)
    assert s["loopOn"] and s["loop"] == [0, 7]  # the section holding bar 1
    end = o.js("Woodshed.current.bars[7].end")  # the last section: its end is the end of the file
    o.js(f"Woodshed.app.transport.seek({end} - 1.0)")
    o.page.get_by_test_id("play").click()
    o.page.wait_for_timeout(1600)
    assert state(o)["playing"] and state(o)["audioTime"] < 3.0  # wrapped to bar 1


@pytest.mark.parametrize("steps", [2, 5, -1])
def test_transposing_respells_the_chart_like_python(open_page: Any, steps: int) -> None:
    o = open_page("pop")
    button = "transpose-up" if steps > 0 else "transpose-down"
    for _ in range(abs(steps)):
        o.page.get_by_test_id(button).click()
    key = o.js("Woodshed.current.song.key")
    first = o.js("Woodshed.current.song.bars[0].chords[0]")
    target = theory.Key((key["pc"] + steps) % 12, key["mode"])
    expected = theory.chord_name((first["pc"] + steps) % 12, first["quality"], target)
    expect(o.page.get_by_test_id("now-chord")).to_have_text(expected.replace("b", "♭").replace("#", "♯"))
    assert state(o)["capo"] == o.js(f"Woodshed.current.capoFor({steps})")


def test_step_four_plays_the_recording_without_your_instrument(open_page: Any) -> None:
    o = open_page("pop")
    o.page.get_by_test_id("inst-bass").click()
    o.page.get_by_test_id("step-4").click()
    until(o, "Woodshed.debug().track === 'minus-bass'")
    s = state(o)
    assert s["countIn"] and not s["loopOn"]
    o.page.get_by_test_id("step-2").click()
    until(o, "Woodshed.debug().track === 'solo-bass'")
    o.page.get_by_test_id("inst-drums").click()  # changing instrument follows the step
    until(o, "Woodshed.debug().track === 'solo-drums'")
    o.page.get_by_test_id("step-1").click()
    until(o, "Woodshed.debug().track === 'mix'")


def test_step_three_loops_slower_with_the_trainer(open_page: Any) -> None:
    o = open_page("pop")
    song_bpm = state(o)["bpm"]
    o.page.get_by_test_id("step-3").click()
    s = state(o)
    assert s["loopOn"] and s["trainer"] and s["countIn"] and s["bpm"] == round(song_bpm * 0.7)


def test_keyboard_and_pedal_keys(open_page: Any) -> None:
    o = open_page("pop")
    o.page.keyboard.press("ArrowRight")
    o.page.keyboard.press("PageDown")
    expect(o.page.get_by_test_id("pass-info")).to_have_text("bar 3 of 8")
    o.page.keyboard.press("ArrowLeft")
    expect(o.page.get_by_test_id("pass-info")).to_have_text("bar 2 of 8")
    o.page.keyboard.press("]")
    assert state(o)["bpm"] > o.js("Woodshed.app.songBpm")
    o.page.keyboard.press(" ")
    until(o, "Woodshed.debug().playing === true", 3.0)
    o.page.keyboard.press(" ")
    until(o, "Woodshed.debug().playing === false", 3.0)


def test_stage_mode_shows_the_chord_and_closes_with_escape(open_page: Any) -> None:
    o = open_page("pop")
    o.page.keyboard.press("s")
    expect(o.page.get_by_test_id("stage")).to_be_visible()
    expect(o.page.get_by_test_id("stage-chord")).to_have_text(o.page.get_by_test_id("now-chord").inner_text())
    o.page.keyboard.press("Escape")
    expect(o.page.get_by_test_id("stage")).to_be_hidden()


def test_a_clear_chord_off_the_beat_is_not_counted_but_can_still_be_checked(open_page: Any) -> None:
    o = open_page("pickup")  # its pickup chord is clear: a timing doubt
    expect(o.page.get_by_test_id("facts")).to_contain_text("Nothing to check by ear")
    timing = o.page.get_by_test_id("doubt").first
    assert timing.get_attribute("data-kind") == "timing" and "?" not in timing.inner_text()
    timing.click()
    expect(o.page.get_by_test_id("doubt-pop")).to_be_visible()
    expect(o.page.get_by_test_id("checks")).to_contain_text("Nothing left to check by ear")


def test_a_doubt_offers_alternatives_and_a_correction_is_remembered(open_page: Any) -> None:
    o = open_page("pickup", close_calls=True)
    expect(o.page.get_by_test_id("spots")).to_have_text("1 spot to check by ear")
    o.page.get_by_test_id("doubt").first.click()
    pop = o.page.get_by_test_id("doubt-pop")
    expect(pop).to_be_visible()
    alternatives = o.page.get_by_test_id("alternative")
    expect(alternatives).to_have_count(3)
    alternatives.nth(1).get_by_role("button", name="Use").click()  # pick the second guess, Gm
    expect(pop).to_be_hidden()
    expect(o.page.get_by_test_id("facts")).to_contain_text("Nothing to check by ear")
    o.page.reload()
    until(o, "window.Woodshed && window.Woodshed.ready === true")
    chord = o.js("Woodshed.current.bars[0].chords.find(c => c.fixed)")
    assert chord is not None and chord["quality"] == "m"  # kept by this browser


def test_the_guitar_panel_draws_one_shape_per_chord(open_page: Any) -> None:
    o = open_page("pop")
    distinct = o.js("Woodshed.current.distinctChords().length")
    expect(o.page.get_by_test_id("shape")).to_have_count(distinct)
    o.page.get_by_test_id("voicing-funk").click()
    expect(o.page.get_by_test_id("shape")).to_have_count(distinct)


def test_the_shapes_wrap_onto_more_lines_instead_of_scrolling_sideways(open_page: Any) -> None:
    o = open_page("pop")
    o.page.set_viewport_size({"width": 360, "height": 740})
    shapes = o.page.get_by_test_id("shape")
    tops = {round(shapes.nth(i).bounding_box()["y"]) for i in range(shapes.count())}
    assert o.js("[...document.querySelectorAll('.shapes')].every(e => e.scrollWidth <= e.clientWidth + 1)")
    assert len(tops) > 1  # the pop song has more shapes than a phone's line holds


def test_the_bass_tab_fits_a_phone_two_beats_a_line(open_page: Any) -> None:
    o = open_page("pop")
    o.page.set_viewport_size({"width": 360, "height": 740})
    o.page.get_by_test_id("inst-bass").click()
    tab = o.page.get_by_test_id("bass-tab")
    expect(tab).to_contain_text("1 e & a 2 e & a")
    assert o.js("(e => e.scrollWidth <= e.clientWidth + 1)(document.querySelector('[data-testid=bass-tab]'))")
    text = tab.inner_text()
    assert text.count("G|") == 2 and text.rstrip().endswith("|")  # a bar of 4/4 in two lines, closed once


def test_every_instrument_panel_renders(open_page: Any) -> None:
    o = open_page("pop")
    for inst in ("bass", "piano", "drums", "voice", "guitar"):
        o.page.get_by_test_id("inst-" + inst).click()
        expect(o.page.get_by_test_id("desk")).not_to_be_empty()
    o.page.get_by_test_id("inst-drums").click()
    o.page.wait_for_selector("[data-testid=drum-staff] svg", timeout=5000)  # VexFlow, from the folder


def test_a_page_without_stems_says_what_is_missing(open_page: Any) -> None:
    o = open_page("waltz", stems=False)
    assert o.js("Woodshed.current.tracks.map(t => t.id)") == ["mix"]
    o.page.get_by_test_id("inst-bass").click()
    expect(o.page.get_by_test_id("desk")).to_contain_text("No bass track was separated")
    expect(o.page.get_by_test_id("facts")).to_contain_text("3/4")
    expect(o.page.get_by_test_id("credits")).to_contain_text("no stems")
    o.page.get_by_test_id("step-4").click()
    until(o, "Woodshed.debug().track === 'mix'")


def test_a_phone_screen_has_no_sideways_scroll(open_page: Any) -> None:
    o = open_page("pop")
    o.page.set_viewport_size({"width": 360, "height": 740})
    o.page.wait_for_timeout(200)
    assert o.js("document.documentElement.scrollWidth <= window.innerWidth + 1")


def test_hearing_a_shape_loads_the_guitar_samples_from_the_folder(open_page: Any) -> None:
    o = open_page("pop")
    o.page.get_by_test_id("shape").first.click()
    until(
        o, "!!(window.WOODSHED_SAMPLES && window.WOODSHED_SAMPLES.guitar) && Woodshed.app.sounds.loaded('guitar')", 10.0
    )


def test_the_count_in_plays_one_bar_before_the_recording(open_page: Any) -> None:
    o = open_page("pop")
    o.page.get_by_test_id("count-in").click()
    o.page.get_by_test_id("play").click()
    o.page.wait_for_timeout(300)
    assert state(o)["audioTime"] == 0  # still counting in
    bar = 60 / state(o)["bpm"] * 4
    until(o, "Woodshed.debug().audioTime > 0.2", bar + 5.0)


def test_the_click_follows_the_beats_of_the_recording(open_page: Any) -> None:
    o = open_page("pop")
    o.page.get_by_test_id("click").click()
    until(o, "Woodshed.app.sounds.loaded('drums')", 10.0)
    o.js("(() => { window.ticks = []; const tick = Woodshed.app.sounds.tick;"
         " Woodshed.app.sounds.tick = (d, a) => { window.ticks.push([d, a]); tick(d, a); }; })()")  # fmt: skip
    o.page.get_by_test_id("play").click()
    until(o, "window.ticks.length >= 3", 5.0)
    ticks = o.js("window.ticks")
    assert all(0 <= delay <= 1.2 for delay, _ in ticks)  # each scheduled ahead of its beat (or of beat one)
    # Each tick lands on a tracked beat: audio time at scheduling plus the delay is a beat time.
    o.js("(() => { window.landed = []; const tick = Woodshed.app.sounds.tick; const tr = Woodshed.app.transport;"
         " Woodshed.app.sounds.tick = (d, a) => { window.landed.push(tr.time + d); tick(d, a); }; })()")  # fmt: skip
    until(o, "window.landed.length >= 2", 5.0)
    beats = o.js("Woodshed.current.song.beats")
    for t in o.js("window.landed"):
        assert min(abs(t - b) for b in beats) < 0.05


def test_the_rhythm_grid_lights_the_sixteenth_being_played(open_page: Any) -> None:
    o = open_page("pop")
    o.page.get_by_test_id("inst-drums").click()
    o.page.get_by_test_id("play").click()
    lit = "[...document.querySelectorAll('#grooveGrid .cell.now')].map(c => c.dataset.six)"
    until(o, f"{lit}.length === 3", 5.0)  # one cell per row (hi-hat, snare, kick)
    assert len(set(o.js(lit))) == 1  # the same sixteenth in every row


def test_the_preview_sound_can_be_chosen(open_page: Any) -> None:
    o = open_page("pop")
    o.page.get_by_test_id("tracks").click()
    o.page.get_by_test_id("sound-rhodes").click()
    assert state(o)["chordSound"] == "rhodes"
    o.page.keyboard.press("Escape")
    o.page.get_by_test_id("inst-piano").click()
    o.page.get_by_test_id("hear-keys").click()
    until(o, "Woodshed.app.sounds.loaded('rhodes')", 10.0)


def test_keys_play_the_notes_heard_on_the_record(open_page: Any) -> None:
    o = open_page("pop")
    o.page.get_by_test_id("inst-piano").click()
    o.page.get_by_test_id("hear-voicing").click()
    until(o, "Woodshed.app.sounds.loaded('piano')", 10.0)


def test_the_groove_with_the_band_plays_two_bars_of_the_recording(open_page: Any) -> None:
    o = open_page("pop")
    o.page.get_by_test_id("inst-drums").click()
    o.page.get_by_test_id("groove-with-band").click()
    until(o, "Woodshed.debug().playing === true", 3.0)
    start, end = o.js("[Woodshed.current.bars[0].start, Woodshed.current.bars[2].start]")
    until(o, "Woodshed.debug().playing === false", end - start + 3.0)
    assert state(o)["audioTime"] == pytest.approx(end, abs=0.4)  # stopped after two bars


def test_a_page_opened_without_its_files_says_how_to_fix_it(open_page: Any, tmp_path: Path) -> None:
    o = open_page("pop")
    expect(o.page.locator(".missing-files")).to_be_hidden()  # with its files: no message
    # Opened from inside a ZIP on Windows, index.html is extracted alone to a temporary folder.
    alone = tmp_path / "index.html"
    shutil.copy(o.folder / "index.html", alone)
    other = o.page.context.new_page()
    other.goto(alone.as_uri())
    expect(other.locator(".missing-files")).to_be_visible()
    expect(other.locator(".missing-files")).to_contain_text("Extract")
    other.close()


@pytest.mark.parametrize(
    "stored", ["{}", "[]", '"x"', "not json", '{"0": [99, "m"]}', '{"0": [7, "dim"]}', '{"0": "G"}']
)
def test_corrupted_saved_corrections_never_break_the_page(open_page: Any, stored: str) -> None:
    o = open_page("pickup", close_calls=True)
    o.page.get_by_test_id("doubt").first.click()
    o.page.get_by_test_id("pick").first.click()  # creates the key for this song
    key = o.js("Object.keys(localStorage).find(k => /^woodshed:corrections:[^:]+$/.test(k))")
    o.js("([k, v]) => { localStorage.setItem(k, v); localStorage.setItem(k + ':removed', v); }", [key, stored])
    o.page.reload()
    until(o, "window.Woodshed && window.Woodshed.ready === true")
    assert o.js("Woodshed.current.bars[0].chords.some(c => c.fixed)") is False  # ignored, not applied
    expect(o.page.get_by_test_id("spots")).to_be_visible()


def test_a_doubt_opens_from_the_keyboard(open_page: Any) -> None:
    o = open_page("pickup")
    o.page.locator(".bar", has=o.page.get_by_test_id("doubt")).first.focus()  # the bar is the control (spec 021)
    o.page.keyboard.press("Enter")
    expect(o.page.get_by_test_id("doubt-pop")).to_be_visible()
    o.page.keyboard.press("Escape")
    expect(o.page.get_by_test_id("doubt-pop")).to_be_hidden()
    assert o.js("document.activeElement.dataset.testid") == "bar"  # focus back where it was


def test_pressing_play_during_the_count_in_cancels_it(open_page: Any) -> None:
    o = open_page("pop")
    o.page.get_by_test_id("count-in").click()
    o.page.get_by_test_id("play").click()
    o.page.wait_for_timeout(300)
    assert state(o)["playing"]  # counting in
    o.page.get_by_test_id("play").click()
    assert not state(o)["playing"]
    o.page.wait_for_timeout(int(60 / state(o)["bpm"] * 4 * 1000) + 800)
    assert state(o)["audioTime"] == 0 and not state(o)["playing"]  # the recording never started


def test_the_trainer_speeds_up_after_each_pass(open_page: Any) -> None:
    o = open_page("pop")
    o.page.get_by_test_id("step-3").click()
    o.page.get_by_test_id("count-in").click()  # off, to keep the test short
    start = state(o)["bpm"]
    end = o.js("Woodshed.current.bars[7].end")  # the end of the looped section
    o.js(f"Woodshed.app.transport.seek({end} - 0.3)")
    o.page.get_by_test_id("play").click()
    until(o, f"Woodshed.debug().bpm === {start + 5}", 5.0)


def test_a_missing_track_file_is_named_and_the_mix_comes_back(page: Any, pages_root: str, tmp_path: Path) -> None:
    from tests.page.conftest import built

    copy = tmp_path / "page"
    shutil.copytree(built("pop", True, pages_root), copy)
    (copy / "audio" / "solo-bass.flac").unlink()
    page.goto((copy / "index.html").as_uri())
    for _ in range(100):
        if page.evaluate("window.Woodshed && window.Woodshed.ready === true"):
            break
        page.wait_for_timeout(25)
    page.get_by_test_id("play").click()
    page.get_by_test_id("tracks").click()
    page.get_by_test_id("track-solo-bass").click()
    expect(page.get_by_test_id("toast")).to_contain_text("solo-bass.flac")
    expect(page.get_by_test_id("toast")).to_contain_text("Still playing: Full mix", timeout=6000)
    # Both the menu and the audio stay on the mix, and the mix is still playing.
    assert page.evaluate("[Woodshed.app.store.get().track, Woodshed.debug().track]") == ["mix", "mix"]
    assert page.evaluate("Woodshed.debug().playing") is True


def test_a_held_key_toggles_only_once(open_page: Any) -> None:
    o = open_page("pop")
    o.page.keyboard.down("s")
    o.page.keyboard.down("s")  # auto-repeat while held
    o.page.keyboard.down("s")
    o.page.keyboard.up("s")
    expect(o.page.get_by_test_id("stage")).to_be_visible()


def test_a_seek_while_paused_does_not_step_the_trainer(open_page: Any) -> None:
    o = open_page("pop")
    o.page.get_by_test_id("step-3").click()
    bpm = state(o)["bpm"]
    o.js("Woodshed.app.seekBar(6)")  # outside the looped line (the second pass), paused
    o.page.wait_for_timeout(500)
    assert state(o)["bpm"] == bpm


def test_back_to_the_analysis_gives_back_the_doubt_its_count_and_its_export(open_page: Any) -> None:
    o = open_page("pickup", close_calls=True)
    chart = "JSON.stringify(Woodshed.current.bars.map(b => b.chords.map(c => [c.pc, c.quality, c.beats, !!c.fixed])))"
    before, spots, cho = o.js(chart), o.page.get_by_test_id("spots").inner_text(), download(o, "export-chordpro")
    o.page.get_by_test_id("doubt").first.click()
    o.page.get_by_test_id("alternative").nth(1).get_by_role("button", name=re.compile("^Use")).click()
    assert o.js(chart) != before
    o.page.get_by_test_id("fixed").first.click()
    reset = o.page.get_by_test_id("doubt-reset")
    expect(reset).to_have_accessible_name(re.compile("^Back to the analysis"))
    reset.click()
    assert o.js(chart) == before
    expect(o.page.get_by_test_id("spots")).to_have_text(spots)
    assert download(o, "export-chordpro") == cho  # "check by ear" lists it again
    o.page.reload()
    until(o, "window.Woodshed && window.Woodshed.ready === true")
    assert o.js(chart) == before  # this browser forgot the correction


def test_correcting_a_doubt_twice_gives_the_same_chart_after_a_reload(open_page: Any) -> None:
    o = open_page("pickup")
    o.page.get_by_test_id("doubt").first.click()
    o.page.get_by_test_id("pick-first").click()  # the top guess
    o.js("Woodshed.app.correct(0, 1, {pc: 7, quality: 'm'})")  # then a change of mind
    chords = "JSON.stringify(Woodshed.current.bars[0].chords.map(c => [c.pc, c.quality, c.beats]))"
    live = o.js(chords)
    assert live == '[[-1,"N",3],[7,"m",1]]'
    o.page.reload()
    until(o, "window.Woodshed && window.Woodshed.ready === true")
    assert o.js(chords) == live


def test_the_waveform_layer_is_not_rebuilt_while_playing_at_fractional_zoom(browser: Any, pages_root: str) -> None:
    from tests.page.conftest import built

    context = browser.new_context(device_scale_factor=1.5, locale="en-US")
    page = context.new_page()
    page.goto((built("pop", True, pages_root) / "index.html").as_uri())
    for _ in range(100):
        if page.evaluate("window.Woodshed && window.Woodshed.ready === true"):
            break
        page.wait_for_timeout(25)
    page.get_by_test_id("play").click()
    page.wait_for_timeout(500)  # fonts and layout settle: one rebuild for a real size change is fine
    page.evaluate(
        "(() => { window.canvases = 0; const make = document.createElement.bind(document);"
        " document.createElement = (t, ...a) => { if (t === 'canvas') window.canvases++; return make(t, ...a); }; })()"
    )
    page.wait_for_timeout(1000)
    assert page.evaluate("window.canvases") == 0  # about 60 frames, no rebuild
    context.close()


def test_a_page_built_before_its_stems_says_when_to_reload(page: Any, pages_root: str, tmp_path: Path) -> None:
    from tests import synth
    from woodshed import analysis, build

    wav = synth.write("pop", tmp_path).wav
    folder = build.build(analysis.analyze(wav, use_stems=False), wav, tmp_path / "out", None, pending_seconds=120)
    page.goto((folder / "index.html").as_uri())
    for _ in range(100):
        if page.evaluate("window.Woodshed && window.Woodshed.ready === true"):
            break
        page.wait_for_timeout(25)
    expect(page.get_by_test_id("pending")).to_be_visible()
    expect(page.get_by_test_id("pending")).to_contain_text("Reload this page in about 2 min")


def test_a_finished_page_has_no_pending_banner(open_page: Any) -> None:
    o = open_page("pop")
    expect(o.page.get_by_test_id("pending")).to_be_hidden()


def download(o: Any, testid: str) -> str:
    o.page.get_by_test_id("export").click()
    with o.page.expect_download() as info:
        o.page.get_by_test_id(testid).click()
    path = info.value.path()
    assert path is not None
    return Path(path).read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("name", "close_calls"),
    [("pop", False), ("pickup", False), ("waltz", False), ("ballad", False), ("funk", False), ("pickup", True)],
)  # ballad, funk: .lab clipped; pickup with close calls: the "?" of a doubtful chord
def test_text_exports_from_the_page_equal_the_python_ones(open_page: Any, name: str, close_calls: bool) -> None:
    from woodshed import exports

    o = open_page(name, stems=name != "waltz", close_calls=close_calls)
    data = o.js("Woodshed.current.song")
    assert download(o, "export-chordpro") == exports.chordpro(data)
    assert download(o, "export-lab") == exports.lab(data)
    assert ("{comment: check by ear:" in download(o, "export-chordpro")) is close_calls


def test_exports_from_the_page_carry_the_corrections(open_page: Any) -> None:
    import jsonschema

    from woodshed import song

    o = open_page("pickup")
    o.page.get_by_test_id("doubt").first.click()
    o.page.get_by_test_id("pick").first.click()  # G becomes Gm
    chordpro = download(o, "export-chordpro")
    assert "Gm" in chordpro and "?" not in chordpro  # settled: no longer listed to check
    data = json.loads(download(o, "export-json"))
    jsonschema.validate(data, song.schema())
    assert data["bars"][0]["chords"][1] == {"pc": 7, "quality": "m", "beats": 1, "doubt": None}


def download_bytes(o: Any, testid: str) -> bytes:
    o.page.get_by_test_id("export").click()
    with o.page.expect_download() as info:
        o.page.get_by_test_id(testid).click()
    path = info.value.path()
    assert path is not None
    return Path(path).read_bytes()


@pytest.mark.parametrize(("name", "stems"), [("pop", True), ("waltz", False), ("funk", True)])
def test_midi_and_musicxml_from_the_page_equal_the_python_ones(open_page: Any, name: str, stems: bool) -> None:
    from woodshed import exports

    o = open_page(name, stems=stems)
    data = o.js("Woodshed.current.song")
    assert download_bytes(o, "export-midi") == exports.midi(data)
    assert download(o, "export-musicxml") == exports.musicxml(data)


def test_a_groove_with_nothing_steady_gives_no_drums_in_the_midi_like_python(open_page: Any) -> None:
    from woodshed import exports

    o = open_page("pop", variant="groove-diffuse")
    data = o.js("Woodshed.current.song")
    hits = exports.groove_hits(data["parts"]["groove"])
    assert not any(hits["kick"]) and not any(hits["snare"])  # the panel's "no clear groove"
    assert download_bytes(o, "export-midi") == exports.midi(data)


def test_midi_and_musicxml_carry_the_corrections(open_page: Any) -> None:
    from woodshed import exports

    o = open_page("pickup")
    o.page.get_by_test_id("doubt").first.click()
    o.page.get_by_test_id("pick").first.click()  # G becomes Gm
    corrected = json.loads(download(o, "export-json"))
    assert download_bytes(o, "export-midi") == exports.midi(corrected)
    assert download(o, "export-musicxml") == exports.musicxml(corrected)
    assert "<kind>minor</kind>" in download(o, "export-musicxml")


def test_print_opens_the_print_dialog(open_page: Any) -> None:
    o = open_page("pop")
    o.js("window.print = () => { window.printed = true; }")
    o.page.get_by_test_id("export").click()
    o.page.get_by_test_id("export-print").click()
    assert o.js("window.printed === true")


def test_exports_match_python_for_a_half_bpm_and_a_hostile_title(open_page: Any) -> None:
    from woodshed import exports

    o = open_page("pop")
    o.js("Woodshed.current.song.bpm = 118.5; Woodshed.current.song.title = 'Live }{x}\\n at <Club> & \\u{1d11e}'")
    data = o.js("Woodshed.current.song")
    assert download(o, "export-chordpro") == exports.chordpro(data)
    assert download(o, "export-lab") == exports.lab(data)
    assert download_bytes(o, "export-midi") == exports.midi(data)
    assert download(o, "export-musicxml") == exports.musicxml(data)
    o.js("Woodshed.current.song.bpm = 96")  # 60,000,000 / 96 = 625,000 exactly; and halves round to even
    assert download_bytes(o, "export-midi") == exports.midi(o.js("Woodshed.current.song"))


def test_the_form_follows_the_song_and_a_part_loops_from_its_name(open_page: Any) -> None:
    o = open_page("pop", variant="sections")
    chips = o.page.get_by_test_id("form-chip")
    expect(chips).to_have_text(["Verse 1", "Chorus 1"])
    expect(chips.first).to_have_class(re.compile(r"\bon\b"))
    o.js("Woodshed.app.seekBar(5)")
    expect(chips.nth(1)).to_have_class(re.compile(r"\bon\b"))
    expect(o.page.get_by_test_id("bar-info")).to_have_text("Chorus 1")
    expect(o.page.get_by_test_id("pass-info")).to_have_text("bar 2 of 4")
    chips.first.click()  # a part's name goes there
    until(o, "Woodshed.debug().beat === 0")
    o.page.get_by_test_id("section-loop").nth(1).click()
    s = state(o)
    assert s["loopOn"] and s["loop"] == [4, 7]
    expect(o.page.get_by_test_id("loop-info")).to_have_text("Looping Chorus 1")


def test_stage_mode_names_the_part_and_announces_the_next_one(open_page: Any) -> None:
    o = open_page("pop", variant="sections")
    o.page.get_by_test_id("stage-open").click()
    o.js("Woodshed.app.seekBar(2)")
    expect(o.page.get_by_test_id("stage-section")).to_have_text("Verse 1")
    expect(o.page.get_by_test_id("stage-coming")).to_have_text("Chorus 1 in 2 bars")
    o.js("Woodshed.app.seekBar(7)")
    expect(o.page.get_by_test_id("stage-section")).to_have_text("Chorus 1")
    expect(o.page.get_by_test_id("stage-coming")).to_have_text("End next bar")


def test_a_song_without_sections_still_plays_and_loops_by_line(open_page: Any) -> None:
    o = open_page("pop", variant="nosections")
    expect(o.page.get_by_test_id("form-chip")).to_have_count(0)
    expect(o.page.get_by_test_id("section")).to_have_count(0)
    o.js("Woodshed.app.seekBar(2)")
    expect(o.page.get_by_test_id("bar-info")).to_have_text("Bar 3")
    o.page.keyboard.press("l")
    assert state(o)["loop"] == [0, 3]


IN_BAND = (
    "u => { const el = document.querySelector('.bar.cur'); const r = el.getBoundingClientRect();"
    " const seen = innerHeight - document.getElementById('dock').offsetHeight;"
    " return r.top >= 0 && r.bottom <= seen; }"
)
OUT_OF_FOLLOW_BAND = (
    "() => { const r = document.querySelector('.bar.cur').getBoundingClientRect();"
    " const seen = innerHeight - document.getElementById('dock').offsetHeight;"
    " return r.top < seen * 0.12 || r.bottom > seen * 0.75; }"
)
SHEET_HIDDEN = (
    "() => document.getElementById('sheet').getBoundingClientRect().top"
    " >= innerHeight - document.getElementById('dock').offsetHeight"
)
PEEK = (
    "() => { const seen = innerHeight - document.getElementById('dock').offsetHeight;"
    " scrollTo(0, scrollY + document.getElementById('sheet').getBoundingClientRect().top - seen + 40); }"
)


def test_the_page_scrolls_with_the_song_and_the_pedal_does_not_stop_it(open_page: Any) -> None:
    o = open_page("pop")
    o.page.set_viewport_size({"width": 1000, "height": 420})
    o.js(PEEK)  # only the top of the chart shows above the dock
    assert not o.js(IN_BAND)
    o.page.get_by_test_id("play").click()
    until(o, "Woodshed.debug().playing === true")
    until(o, IN_BAND)
    o.page.wait_for_timeout(700)  # the page's smooth scroll ends
    o.js(PEEK)  # a scroll by the page itself, not by hand
    assert not o.js(IN_BAND)
    o.page.keyboard.press("PageDown")  # a page-turner pedal seeks a bar: not a scroll by hand
    until(o, IN_BAND)
    o.page.wait_for_timeout(600)
    o.js(PEEK)
    until(o, IN_BAND, 3.0)  # the next bar (2 s at 120 BPM) is followed, before a hand's 4 s pause ends


def test_a_scroll_by_hand_wins_and_a_chart_off_screen_is_left_alone(open_page: Any) -> None:
    o = open_page("pop")
    o.page.set_viewport_size({"width": 1000, "height": 420})
    o.js(PEEK)
    o.page.mouse.move(40, 100)
    o.page.mouse.wheel(0, 60)  # by hand, a little more of the chart showing
    o.page.wait_for_timeout(300)
    assert o.js(OUT_OF_FOLLOW_BAND)  # the page would follow, but for the hand
    at = o.js("scrollY")
    o.page.get_by_test_id("play").click()
    until(o, "Woodshed.debug().playing === true")
    o.page.wait_for_timeout(800)
    assert o.js("scrollY") == at
    o.page.get_by_test_id("play").click()
    o.js("scrollTo(0, 0)")  # the chart below the dock: the musician reads the top of the page
    assert o.js(SHEET_HIDDEN)
    o.page.wait_for_timeout(4200)  # the hand's pause is over
    o.page.get_by_test_id("play").click()
    o.page.wait_for_timeout(800)
    assert o.js("scrollY") == 0


def test_printing_is_black_on_white_whatever_the_theme(open_page: Any) -> None:
    o = open_page("pop")
    assert o.js("document.documentElement.dataset.theme") == "dark"
    o.page.emulate_media(media="print")
    assert o.js("getComputedStyle(document.body).backgroundColor") == "rgb(255, 255, 255)"
    assert o.js("getComputedStyle(document.querySelector('.bar')).color") == "rgb(0, 0, 0)"
    expect(o.page.get_by_test_id("theme")).to_be_hidden()
    for screen_only in (".now", ".harm", ".back", ".dock", "#wordsBtn"):  # the stand gets the chart only
        assert o.js(
            f"[...document.querySelectorAll('{screen_only}')].every(e => getComputedStyle(e).display === 'none')"
        )


def test_a_doubt_says_why_the_chart_keeps_a_chord_the_bar_alone_ranks_lower(open_page: Any) -> None:
    o = open_page("pickup", close_calls=True)
    ref = o.page.get_by_test_id("doubt").first.get_attribute("data-ref")
    assert ref is not None
    u, k = (int(x) for x in ref.split("_"))
    # As the analysis can give: the bar heard alone sounds like another chord, the song around it
    # points to the chart's.
    o.js(
        "([u, k]) => { const c = Woodshed.current.bars[u].chords[k];"
        " c.doubt.alternatives = [{pc: (c.pc + 5) % 12, quality: '', share: 61},"
        " {pc: c.pc, quality: c.quality, share: 39}]; }",
        [u, k],
    )
    o.page.get_by_test_id("doubt").first.click()
    pop = o.page.get_by_test_id("doubt-pop")
    expect(pop.locator("h3")).to_have_text(f"Bar {u + 1}: which one do you hear?")
    expect(o.page.get_by_test_id("doubt-note")).to_contain_text("The chart keeps")
    analysis = o.page.get_by_test_id("alternative").nth(1)
    expect(analysis).to_contain_text("analysis")
    expect(analysis.get_by_role("button", name=re.compile("^Keep"))).to_be_enabled()  # confirmed by ear


def test_a_correction_can_be_changed_or_taken_back_to_the_analysis(open_page: Any) -> None:
    o = open_page("pickup", close_calls=True)
    analysed = o.js(
        "(() => { const c = Woodshed.current.bars[0].chords.find(c => c.doubt); return [c.pc, c.quality]; })()"
    )
    o.page.get_by_test_id("doubt").first.click()
    o.page.get_by_test_id("alternative").nth(1).get_by_role("button", name=re.compile("^Use")).click()
    fixed = (
        "(() => { const c = Woodshed.current.bars[0].chords.find(c => c.fixed);"
        " return c ? [c.pc, c.quality] : null; })()"
    )
    assert o.js(fixed) not in (None, analysed)
    o.page.get_by_test_id("fixed").first.click()  # a correction is still a button
    expect(o.page.get_by_test_id("doubt-note")).to_contain_text("Your correction")
    o.page.get_by_test_id("alternative").filter(has_text="analysis").get_by_role(
        "button", name=re.compile("^Use")
    ).click()
    assert o.js(fixed) == analysed  # back to the analysis's chord, as checked by ear
    expect(o.page.get_by_test_id("fixed").first).to_be_visible()


def test_a_chord_confirmed_as_the_one_before_stays_on_the_words(open_page: Any) -> None:
    o = open_page("pop", variant="lyrics-same-check")
    words = o.page.locator(".lline")
    expect(words.get_by_test_id("doubt").first).to_be_visible()  # to check, on the words
    words.get_by_test_id("doubt").first.click()
    o.page.get_by_test_id("alternative").filter(has_text="analysis").get_by_role(
        "button", name=re.compile("^Keep")
    ).click()
    expect(words.get_by_test_id("fixed").first).to_be_visible()  # checked: still there, with its mark


def test_a_correction_to_the_chord_before_it_in_the_bar_can_still_be_changed(open_page: Any) -> None:
    o = open_page("pickup", close_calls=True)
    # The bar's doubt corrected to the chord before it in the same bar: the two merge into one.
    target = o.js(
        "(() => { const bars = Woodshed.current.bars;"
        " for (let u = 0; u < bars.length; u++) for (let k = 1; k < bars[u].chords.length; k++)"
        "   if (bars[u].chords[k].doubt) { const p = bars[u].chords[k - 1]; return [u, k, p.pc, p.quality]; }"
        " return null; })()"
    )
    assert target is not None
    u, k, pc, quality = target
    o.js(f"Woodshed.app.correct({u}, {k}, {{pc: {pc}, quality: '{quality}'}})")
    o.page.get_by_test_id("fixed").first.click()  # no error, the popover opens
    expect(o.page.get_by_test_id("doubt-note")).to_be_visible()


def test_the_library_finds_the_page_corrections_by_the_page_own_key(open_page: Any) -> None:
    from woodshed import app as library
    from woodshed import build

    o = open_page("pickup", close_calls=True)
    found = build.DATA_BLOCK.search((o.folder / "index.html").read_text(encoding="utf-8"))
    assert found is not None
    assert library.analysis_key(json.loads(found.group(1))["song"]) == o.js("Woodshed.app.fixesKey")


def test_the_open_shapes_say_which_chords_are_barres_and_the_capo_tip_agrees(open_page: Any) -> None:
    o = open_page("pop")
    o.page.get_by_test_id("inst-guitar").click()
    o.js("Woodshed.app.transposeTo(1)")  # C# G# A#m F#: no open shape for these
    o.js("Woodshed.app.store.set({capo: 0})")
    no_open = o.js(
        "Woodshed.current.distinctChords().filter(c =>"
        " !Woodshed.instruments.tableShape(Woodshed.current.view.shapes, c.pc + 1, c.quality)).length"
    )
    assert no_open > 0
    expect(o.page.locator(".shape-card .barre-tag")).to_have_count(no_open)
    tip = o.page.locator("#desk").inner_text()
    assert f"barre chords: {no_open}" in tip.lower() or "Tip: capo" in tip
    assert "capo 0" not in tip  # "no capo", never "capo 0"


def test_the_drum_text_names_the_hits_the_notation_draws(open_page: Any) -> None:
    o = open_page("pop", variant="groove-edge")
    o.page.get_by_test_id("inst-drums").click()
    text = o.page.locator("#desk").inner_text()
    assert "Kick on 1, the & of 1 and 3." in text  # the & of 1 in 55 % of the bars: drawn, so named
    assert " on ." not in text


def test_a_drum_read_with_no_steady_hit_says_so_instead_of_inventing_one(open_page: Any) -> None:
    o = open_page("pop", variant="groove-loose")
    o.page.get_by_test_id("inst-drums").click()
    text = o.page.locator("#desk").inner_text()
    assert "No kick or snare groove" in text and "Trust your ears" in text  # its hi-hat is steady
    assert "kick on" not in text.lower() and "snare on" not in text.lower()


def test_the_bass_tab_draws_doubtful_notes_faint_and_says_when_a_bar_has_no_bass(open_page: Any) -> None:
    o = open_page("pop", variant="bass-doubts")
    o.page.get_by_test_id("inst-bass").click()
    tab = o.page.get_by_test_id("bass-tab")
    expect(tab.locator(".lo").first).to_be_visible()  # bar 1: every note less certain
    expect(o.page.get_by_test_id("bass-silent")).to_have_count(0)
    o.js("Woodshed.app.seekBar(1)")
    expect(o.page.get_by_test_id("bass-silent")).to_have_text("No bass heard in this bar.")
    expect(tab.locator(".lo")).to_have_count(0)


def test_space_plays_whatever_button_was_clicked_last(open_page: Any) -> None:
    o = open_page("pop")
    o.page.get_by_test_id("trainer").click()  # a click leaves the focus on Trainer
    trainer = o.js("Woodshed.app.store.get().trainer")
    o.page.keyboard.press(" ")
    until(o, "Woodshed.debug().playing === true")
    assert o.js("Woodshed.app.store.get().trainer") == trainer  # Space played, it did not press Trainer again


def test_the_time_of_a_sung_line_plays_from_there(open_page: Any) -> None:
    o = open_page("pop", variant="lyrics")
    line = o.page.locator(".lline button.t").nth(1)
    line.click()
    until(o, "Woodshed.debug().playing === true")
    start = float(line.get_attribute("data-seek") or 0)
    assert o.js("Woodshed.debug().time") >= start - 0.05


def test_space_still_presses_a_button_in_a_menu(open_page: Any) -> None:
    o = open_page("pop")
    o.page.get_by_test_id("tracks").click()
    track = o.page.get_by_test_id("track-minus-drums")
    track.focus()
    o.page.keyboard.press(" ")  # a keyboard user picks a track in the menu
    until(o, "Woodshed.app.store.get().track === 'minus-drums'")
    assert o.js("Woodshed.debug().playing") is False


def test_reading_ahead_pauses_following_with_a_way_back_to_the_song(open_page: Any) -> None:
    o = open_page("pop")
    o.page.set_viewport_size({"width": 1000, "height": 420})
    o.js(PEEK)
    o.page.get_by_test_id("play").click()
    until(o, IN_BAND)
    o.page.mouse.move(40, 100)
    for _ in range(6):  # the musician scrolls on, reading ahead
        o.page.mouse.wheel(0, 400)
        o.page.wait_for_timeout(50)
    back = o.page.get_by_test_id("back-to-song")
    expect(back).to_be_visible(timeout=4000)  # following waits, and says how to come back
    at = o.js("scrollY")
    o.page.wait_for_timeout(2500)  # a bar or more: the page does not pull the reader back
    assert o.js("scrollY") == at
    back.click()
    until(o, IN_BAND, 3.0)
    expect(back).to_be_hidden()


def test_following_comes_back_when_the_bar_playing_is_where_the_page_would_put_it(open_page: Any) -> None:
    o = open_page("pop")
    o.page.set_viewport_size({"width": 1000, "height": 420})
    o.js("Woodshed.app.setBpm(Woodshed.app.minBpm)")  # slow: the bar playing stays while the test scrolls
    o.js(PEEK)
    o.page.get_by_test_id("play").click()
    until(o, IN_BAND)
    # The page's smooth scroll ends (on a loaded machine it takes longer than a fixed wait): still for 300 ms.
    last = None
    for _ in range(50):
        now = o.js("scrollY")
        if now == last:
            break
        last = now
        o.page.wait_for_timeout(300)
    o.page.mouse.move(40, 100)
    o.page.mouse.wheel(0, -120)  # reading the bars before: the bar playing drops low on the screen
    back = o.page.get_by_test_id("back-to-song")
    expect(back).to_be_visible(timeout=4000)
    # Back where the page keeps the bar playing, wherever it is now (a loaded machine plays on).
    o.js(
        "(() => { const b = document.querySelector('.bar.cur');"
        " scrollBy(0, b.getBoundingClientRect().top - innerHeight * 0.35); })()"
    )
    expect(back).to_be_hidden(timeout=4000)  # following again, by itself


@pytest.mark.parametrize("inst", ["guitar", "voice"])
def test_on_a_phone_the_chart_starts_on_the_first_screen(open_page: Any, inst: str) -> None:
    o = open_page("pop", variant="lyrics")
    o.page.set_viewport_size({"width": 390, "height": 844})
    o.page.get_by_test_id("inst-" + inst).click()
    assert o.js("document.getElementById('sheet').getBoundingClientRect().top") < 844 - 120  # above the dock
    hidden = o.js("getComputedStyle(document.querySelector('.now')).display === 'none'")
    assert hidden is (inst == "voice")  # the singer reads the words, not a big chord
    assert o.js("document.documentElement.scrollWidth <= innerWidth + 1")
    if inst == "voice":
        o.page.get_by_test_id("sheet-grid").click()  # no words on screen: the chord card is back
        expect(o.page.locator(".now")).to_be_visible()


def test_stage_mode_shows_the_guitar_shapes_of_the_chord_now_and_next(open_page: Any) -> None:
    o = open_page("pop")
    o.page.get_by_test_id("inst-guitar").click()
    o.js("Woodshed.app.seekBar(1)")
    o.js("Woodshed.app.setStage(true, false)")  # full screen is not the point here, and its exit is async
    shapes = o.page.get_by_test_id("stage-shapes")
    expect(shapes.locator("svg")).to_have_count(2)
    before = shapes.inner_html()
    o.js("Woodshed.app.store.set({pos: 'barre'})")  # another voicing, chosen with the stand open
    assert shapes.inner_html() != before
    o.page.get_by_test_id("stage-exit").click()
    o.page.set_viewport_size({"width": 844, "height": 390})  # a phone held sideways: no room for them
    o.js("Woodshed.app.setStage(true, false)")
    expect(shapes).to_have_count(1)
    expect(shapes).to_be_hidden()
    o.page.get_by_test_id("stage-exit").click()
    o.page.get_by_test_id("inst-bass").click()
    o.js("Woodshed.app.setStage(true, false)")
    expect(o.page.get_by_test_id("stage-shapes")).to_have_count(0)  # guitar shapes for the guitar only


@pytest.mark.parametrize("sheet", ["grid", "lyrics"])
def test_on_a_phone_a_bar_of_four_chords_stays_in_its_bar(open_page: Any, sheet: str) -> None:
    o = open_page("pop", variant="lyrics")
    o.page.set_viewport_size({"width": 390, "height": 844})
    # Every bar split into four one-beat chords, the last a doubt: the densest bar a chart has.
    o.js(
        "(() => { Woodshed.current.bars.forEach((b, u) => { const c = b.chords[0];"
        " b.chords = [0, 1, 2, 3].map((k) => ({ ...c, pc: (c.pc + 2 * k) % 12, beats: 1,"
        " doubt: k === 3 ? c.doubt || { id: 'dense' + u, kind: 'chord', alternatives: [] } : null })); });"
        " Woodshed.app.store.set({ corrections: Woodshed.app.store.get().corrections + 1 }); })()"
    )
    o.page.get_by_test_id("sheet-" + sheet).click()
    spill = o.js(
        "[...document.querySelectorAll('.bar[data-bar]')].filter((b) => { const r = b.getBoundingClientRect();"
        " return [...b.children].some((e) => e.getBoundingClientRect().right > r.right + 1); })"
        ".map((b) => b.dataset.bar)"
    )
    assert o.js("document.querySelectorAll('.bar[data-bar]').length") > 0  # bars of the grid on screen
    assert spill == []


@pytest.mark.parametrize("sheet", ["grid", "lyrics"])
def test_on_paper_a_part_stays_on_one_page_when_it_fits(open_page: Any, sheet: str) -> None:
    o = open_page("pop", variant="lyrics")
    o.page.get_by_test_id("sheet-" + sheet).click()
    o.page.emulate_media(media="print")
    blocks = o.page.locator("#sheet > .sec-block")
    heads = o.page.locator("#sheet .sec-head")
    expect(heads.first).to_be_visible()
    assert blocks.count() == heads.count() > 0  # each part with its lines in one block
    blocks_js = "[...document.querySelectorAll('#sheet > .sec-block')]"
    kept = blocks_js + ".every(b => getComputedStyle(b).breakInside === 'avoid')"
    assert o.js(kept)
    assert o.js("getComputedStyle(document.querySelector('.sec-head')).breakAfter") == "avoid"


def test_on_paper_a_guitarist_gets_the_shapes_of_the_song(open_page: Any) -> None:
    o = open_page("pop")
    o.page.get_by_test_id("inst-guitar").click()
    strip = o.page.get_by_test_id("print-shapes")
    expect(strip).to_be_hidden()  # paper only
    o.page.emulate_media(media="print")
    expect(strip).to_be_visible()
    assert strip.locator("svg").count() == o.js("Woodshed.current.distinctChords().filter(c => c.pc >= 0).length")
    o.page.emulate_media(media="screen")
    o.page.get_by_test_id("inst-bass").click()
    o.page.emulate_media(media="print")
    expect(strip).to_be_hidden()  # a bassist reads the chart


def test_print_the_chart_opens_the_print_dialog_once(open_page: Any) -> None:
    o = open_page("pop")
    o.js("(() => { window.printed = 0; window.print = () => { window.printed++; }; })()")
    o.page.get_by_test_id("export").click()
    o.page.get_by_test_id("export-print").click()
    o.page.wait_for_timeout(300)
    assert o.js("window.printed") == 1


BEYOND_THE_SKY = {  # a read with nothing steady: every slot of the kick between 0.18 and 0.51
    "kick": [0.51, 0.42, 0.25, 0.39, 0.33, 0.21, 0.28, 0.18, 0.25, 0.23, 0.21, 0.21, 0.37, 0.18, 0.26, 0.26],
    "snare": [0.05, 0.05, 0.07, 0.02, 0.02, 0.0, 0.05, 0.02, 0.0, 0.02, 0.0, 0.0, 0.05, 0.0, 0.04, 0.02],
    "hat": [0.28, 0.23, 0.14, 0.14, 0.32, 0.18, 0.19, 0.18, 0.32, 0.14, 0.16, 0.16, 0.39, 0.19, 0.25, 0.26],
    "agreement": {"kick": 0.72, "snare": 0.97, "hat": 0.78}, "bars": 57,
}  # fmt: skip
AS_I_AM = {  # a clear rock groove: kick on 1 and the & of 3, snare on 2 and 4, hi-hat on the beats
    "kick": [0.56, 0.0, 0.25, 0.0, 0.1, 0.0, 0.04, 0.0, 0.48, 0.0, 0.63, 0.03, 0.01, 0.0, 0.27, 0.0],
    "snare": [0.18, 0.02, 0.02, 0.04, 0.61, 0.01, 0.03, 0.01, 0.18, 0.0, 0.01, 0.0, 0.56, 0.0, 0.09, 0.0],
    "hat": [0.53, 0.13, 0.25, 0.09, 0.9, 0.03, 0.22, 0.09, 0.59, 0.05, 0.26, 0.01, 0.84, 0.04, 0.17, 0.03],
    "agreement": {"kick": 0.88, "snare": 0.91, "hat": 0.84}, "bars": 105,
}  # fmt: skip


@pytest.mark.parametrize("groove", ["clear", "diffuse"])
def test_the_drum_text_notation_and_grid_tell_one_story(open_page: Any, groove: str) -> None:
    o = open_page("pop")
    data = AS_I_AM if groove == "clear" else BEYOND_THE_SKY
    o.js(f"Woodshed.current.parts.groove = {json.dumps(data)}")
    o.page.get_by_test_id("inst-drums").click()
    text = o.page.get_by_test_id("desk").inner_text()
    played = o.page.locator("#grooveGrid .dot.on")
    if groove == "diffuse":
        assert "No clear groove" in text and "Kick on" not in text
        expect(played).to_have_count(0)  # nothing drawn as played
        expect(o.page.locator("#grooveGrid .dot")).to_have_count(0)  # nor faintly: no groove to see
        expect(o.page.get_by_test_id("drum-staff")).to_have_count(0)  # no notation of a groove not there
    else:
        assert "Kick on 1 and the & of 3" in text and "Snare on 2 and 4" in text
        assert "Hi-hat on 1, 2, 3 and 4" in text
        expect(played).to_have_count(8)  # what the text names, and nothing else


def test_on_a_tablet_the_guitar_shapes_stay_in_sight_above_the_player(open_page: Any) -> None:
    o = open_page("pop", variant="lyrics")
    o.page.set_viewport_size({"width": 820, "height": 1180})  # an iPad held upright: the panel is under the chart
    strip = o.page.get_by_test_id("dock-shapes")
    o.page.reload()
    until(o, "window.Woodshed && window.Woodshed.ready === true")
    expect(strip.locator("svg").first).to_be_visible()  # the guitar is the first instrument: at once
    o.page.get_by_test_id("inst-guitar").click()
    o.js("Woodshed.app.seekBar(2)")
    expect(strip.locator("svg")).to_have_count(2)  # the chord now and the next one
    box = strip.bounding_box()
    assert box is not None and box["y"] + box["height"] <= 1180  # in sight, whatever the scroll
    o.js("window.scrollTo(0, document.body.scrollHeight)")
    expect(strip).to_be_in_viewport()
    o.page.set_viewport_size({"width": 1280, "height": 900})  # the panel beside the chart: no need
    expect(strip).to_be_hidden()
    o.page.set_viewport_size({"width": 820, "height": 1180})
    o.page.get_by_test_id("inst-bass").click()
    expect(strip).to_be_hidden()  # shapes for the guitar


def test_the_doubt_pop_is_a_named_dialog_that_keeps_the_keyboard(open_page: Any) -> None:
    o = open_page("pickup", close_calls=True)
    o.page.locator(".bar", has=o.page.get_by_test_id("doubt")).first.focus()
    o.page.keyboard.press("Enter")
    pop = o.page.get_by_role("dialog", name=re.compile(r"^Bar \d+: which one do you hear\?"))
    expect(pop).to_be_visible()
    expect(o.page.get_by_test_id("pick-first")).to_be_focused()  # straight on the first choice
    buttons = pop.locator("button:not([disabled])")
    buttons.last.focus()
    o.page.keyboard.press("Tab")  # the keyboard stays in the dialog
    expect(buttons.first).to_be_focused()
    o.page.keyboard.press("Shift+Tab")
    expect(buttons.last).to_be_focused()
    # The "analysis" tag sits under its chord, never over the share bar.
    tag = pop.locator(".alt .tag").first
    meter = tag.locator("xpath=ancestor::*[contains(@class,'alt')][1]").locator(".meter")
    t, m = tag.bounding_box(), meter.bounding_box()
    assert t is not None and m is not None and (t["x"] + t["width"] <= m["x"] or t["y"] >= m["y"] + m["height"])


def test_a_doubt_opened_from_the_keyboard_off_screen_sits_by_its_bar(open_page: Any) -> None:
    o = open_page("pickup", close_calls=True)
    o.page.set_viewport_size({"width": 1280, "height": 500})
    doubt = o.page.get_by_test_id("doubt").first
    # The chord just under the bottom edge, as after the page followed the song.
    o.js("(() => { const r = document.querySelector('[data-testid=doubt]').getBoundingClientRect();"
         " window.scrollBy(0, r.top - innerHeight + 4); })()")  # fmt: skip
    # The bar holding it, focused: focus alone does not bring it into sight.
    doubt.evaluate("(d) => d.closest('.bar').focus({ preventScroll: true })")
    o.page.keyboard.press("Enter")
    expect(o.page.get_by_test_id("doubt-pop")).to_be_visible()
    d, p = doubt.bounding_box(), o.page.get_by_test_id("doubt-pop").bounding_box()
    assert d is not None and p is not None
    assert d["y"] >= 0 and d["y"] + d["height"] <= 501  # the chord brought into sight
    assert abs(p["y"] - (d["y"] + d["height"])) < 40 or abs(p["y"] + p["height"] - d["y"]) < 40  # beside it


def test_the_part_chips_are_one_tab_stop_moved_with_the_arrows(open_page: Any) -> None:
    o = open_page("pop", variant="lyrics-named")
    chips = o.page.get_by_test_id("form-chip")
    assert chips.count() > 1
    assert o.js("[...document.querySelectorAll('[data-testid=form-chip]')].filter(c => c.tabIndex >= 0).length") == 1
    chips.first.focus()
    beat = o.js("Woodshed.app.store.get().beat")
    o.page.keyboard.press("ArrowRight")
    expect(chips.nth(1)).to_be_focused()
    assert o.js("Woodshed.app.store.get().beat") == beat  # the arrows move between parts, not bars
    o.js("Woodshed.app.store.set({corrections: Woodshed.app.store.get().corrections + 1})")  # drawn again
    expect(chips.nth(1)).to_be_focused()
    assert o.js("[...document.querySelectorAll('[data-testid=form-chip]')].filter(c => c.tabIndex >= 0).length") == 1
    o.page.keyboard.press("End")
    expect(chips.last).to_be_focused()


def test_the_keyboard_never_lands_on_hidden_text(open_page: Any) -> None:
    o = open_page("pop")
    for _ in range(60):
        o.page.keyboard.press("Tab")
        assert o.js("!!document.activeElement.closest('.missing-files, [hidden]')") is False


def test_a_looped_passage_shows_the_bass_tab_of_every_looped_bar(open_page: Any) -> None:
    o = open_page("waltz")  # twelve bars
    o.page.get_by_test_id("inst-bass").click()
    tabs = o.page.get_by_test_id("bass-tab")
    expect(tabs).to_have_count(1)  # the bar playing
    o.js("Woodshed.app.store.set({loop: [1, 3], loopOn: true})")
    expect(tabs).to_have_count(3)  # the whole loop on one screen
    expect(o.page.get_by_test_id("desk")).to_contain_text("Bars 2\u20134, looped")
    expect(o.page.get_by_test_id("desk")).to_contain_text("onsets only")  # lengths are not invented
    last = o.js("Woodshed.current.bars.length - 1")
    assert last >= 8
    o.js(f"Woodshed.app.store.set({{loop: [0, {last}], loopOn: true}})")
    expect(tabs).to_have_count(12)  # a whole loop of twelve bars, up to sixteen (a chorus)
    o.js("Woodshed.app.store.set({loopOn: false})")
    expect(tabs).to_have_count(1)


def _row(on: dict[int, float], rest: float = 0.0) -> list[float]:
    return [on.get(i, rest) for i in range(16)]


@pytest.mark.parametrize(
    ("groove", "said"),
    [
        # A hi-hat on every sixteenth is said so, not as sixteen counts.
        ({"kick": _row({0: 0.9, 8: 0.9}), "snare": _row({4: 0.9, 12: 0.9}), "hat": _row({}, 0.9)},
         "Hi-hat on every sixteenth."),
        ({"kick": _row({0: 0.9, 8: 0.9}), "snare": _row({4: 0.9, 12: 0.9}),
          "hat": _row({i: 0.8 for i in range(0, 16, 2)})},
         "Hi-hat on every eighth."),
        # The Rival Within: kick and snare under half the bars, a steady hi-hat on the beats.
        ({"kick": _row({0: 0.4, 4: 0.49, 8: 0.4, 12: 0.42}), "snare": _row({0: 0.39, 4: 0.29, 8: 0.35, 12: 0.34}),
          "hat": _row({0: 0.82, 4: 0.65, 8: 0.72, 12: 0.64}, 0.1)},
         "No kick or snare groove: neither comes back in most bars. Hi-hat on 1, 2, 3 and 4."),
    ],
)  # fmt: skip
def test_the_drum_text_says_a_pattern_as_a_drummer_does(open_page: Any, groove: dict[str, Any], said: str) -> None:
    o = open_page("pop")
    data = {**groove, "agreement": {"kick": 0.9, "snare": 0.9, "hat": 0.9}, "bars": 16}
    o.js(f"Woodshed.current.parts.groove = {json.dumps(data)}")
    o.page.get_by_test_id("inst-drums").click()
    assert said in o.page.get_by_test_id("desk").inner_text()


def test_the_guitar_panel_names_the_capo_the_page_chooses_and_puts_it_on(open_page: Any) -> None:
    o = open_page("pop")  # C G Am F: the F is a barre, and no capo makes the song clearly easier
    o.page.get_by_test_id("inst-guitar").click()
    desk = o.page.get_by_test_id("desk")
    expect(desk).to_contain_text("One barre chord, and no capo makes the song clearly easier.")
    expect(o.page.get_by_test_id("use-best-capo")).to_have_count(0)
    o.js("Woodshed.app.store.set({capo: 3})")  # a capo put on by hand
    o.page.get_by_test_id("use-best-capo").click()  # "Take the capo off"
    assert o.js("Woodshed.app.store.get().capo") == 0
    for t in (2, -3, 5):  # whatever key: the panel agrees with the capo the transposition chose
        o.js(f"Woodshed.app.transposeTo({t})")
        expect(o.page.get_by_test_id("use-best-capo")).to_have_count(0)


def test_on_a_tablet_a_singer_opens_on_the_words_not_a_big_chord(open_page: Any) -> None:
    o = open_page("pop", variant="lyrics")
    o.page.set_viewport_size({"width": 1024, "height": 1366})  # an iPad held upright
    o.page.get_by_test_id("inst-voice").click()
    expect(o.page.locator(".now")).to_be_hidden()
    o.page.set_viewport_size({"width": 1440, "height": 900})  # a laptop has the room for it
    expect(o.page.locator(".now")).to_be_visible()


def test_the_song_length_is_rounded_as_the_library_rounds_it(open_page: Any) -> None:
    o = open_page("pop")
    o.js("Woodshed.current.song.duration = 222.6")  # 3:43 in the library (rounded), not 3:42
    o.js("Woodshed.app.store.set({corrections: Woodshed.app.store.get().corrections + 1})")
    expect(o.page.get_by_test_id("facts")).to_contain_text("3:43")


def test_stage_mode_says_what_comes_and_what_the_buttons_do(open_page: Any) -> None:
    o = open_page("pop", variant="lyrics-named")
    o.js("Woodshed.app.setStage(true, false)")
    expect(o.page.get_by_test_id("stage-prev")).to_have_attribute(
        "title", "Tap: back to the start of this part. Twice: the part before."
    )
    expect(o.page.get_by_test_id("stage-coming")).to_contain_text("Next part: ")  # stopped: the next part named
    o.page.get_by_test_id("stage-exit").click()
    o.page.get_by_test_id("inst-guitar").click()
    o.js("Woodshed.app.seekBar(1)")
    o.js("Woodshed.app.setStage(true, false)")
    expect(o.page.locator(".st-shapes .next small")).to_have_text("next")  # the dimmer shape says what it is


def test_on_a_touch_screen_the_small_buttons_are_finger_sized(browser: Any, pages_root: str) -> None:
    from tests.page.conftest import built

    context = browser.new_context(viewport={"width": 390, "height": 844}, has_touch=True, locale="en-US")
    page = context.new_page()  # a phone: the narrowest header
    page.goto((built("pop", True, pages_root) / "index.html").as_uri())
    for _ in range(100):
        if page.evaluate("window.Woodshed && window.Woodshed.ready === true"):
            break
        page.wait_for_timeout(25)
    box = page.get_by_test_id("theme").first.bounding_box()
    assert box is not None and box["height"] >= 44 and box["width"] >= 44
    # The bigger buttons cover neither the logo nor the title.
    prefs = page.locator(".prefs").first.bounding_box()
    logo = page.get_by_test_id("logo").bounding_box()
    title = page.get_by_test_id("title").bounding_box()
    assert prefs and logo and title
    assert logo["x"] + logo["width"] <= prefs["x"] or logo["y"] >= prefs["y"] + prefs["height"]
    assert title["y"] >= prefs["y"] + prefs["height"] - 1
    context.close()


def test_the_fit_key_button_names_the_key(open_page: Any) -> None:
    o = open_page("ballad")  # a sung melody: a range to match
    o.page.get_by_test_id("inst-voice").click()
    fit = o.page.get_by_test_id("fit-key")
    for voice in ("bass", "soprano", "tenor", "alto", "mezzo", "baritone"):
        o.page.get_by_test_id("voice-" + voice).click()
        if fit.count():
            break
    expect(fit).to_have_text(re.compile(r"^Transpose to [A-G][♯♭]?m? \([+-]\d+\)$"))  # not "Transpose down"


def test_space_on_the_language_or_theme_button_presses_it(open_page: Any) -> None:
    o = open_page("pop")
    o.page.get_by_test_id("lang-fr").focus()
    o.page.keyboard.press("Space")
    expect(o.page.locator("html")).to_have_attribute("lang", "fr")  # the button, as a keyboard user expects
    assert o.js("Woodshed.app.store.get().playing") is False  # not the music
    o.page.get_by_test_id("lang-en").focus()
    o.page.keyboard.press("Space")
    expect(o.page.locator("html")).to_have_attribute("lang", "en")


@pytest.mark.parametrize("name", ["pop", "ballad", "rock"])
def test_on_paper_bar_numbers_sit_under_the_chords_and_no_screen_badge_is_printed(open_page: Any, name: str) -> None:
    o = open_page(name)
    o.js("Woodshed.app.seekBar(1)")  # a bar lit as playing on screen
    o.page.emulate_media(media="print")
    expect(o.page.get_by_test_id("spots").or_(o.page.locator(".okfact"))).to_be_hidden()
    overlaps = o.js(
        "[...document.querySelectorAll('.bar[data-bar]')].filter((b) => {"
        " const n = b.querySelector('.num'), c = b.querySelector('.ch'); if (!n || !c) return false;"
        " const x = n.getBoundingClientRect(), y = c.getBoundingClientRect();"
        " return x.top < y.bottom - 1 && x.left < y.right && y.left < x.right; }).length"
    )
    assert overlaps == 0
    lit = o.js("getComputedStyle(document.querySelector('.bar.cur')).backgroundColor")
    assert lit in ("rgba(0, 0, 0, 0)", "transparent")


def test_a_looped_passage_says_its_bars_without_bass_in_one_line(open_page: Any) -> None:
    o = open_page("pop", variant="bass-doubts")  # bar 2 has no bass
    o.page.get_by_test_id("inst-bass").click()
    o.js("Woodshed.app.store.set({loop: [0, 3], loopOn: true})")
    expect(o.page.get_by_test_id("bass-tab")).to_have_count(3)  # bars 1, 3 and 4
    expect(o.page.get_by_test_id("bass-silent")).to_have_text("Bar 2: no bass heard.")


def test_a_pedal_plays_after_a_tap_on_the_theme_or_language_button(open_page: Any) -> None:
    o = open_page("pop")
    theme = o.js("document.documentElement.dataset.theme || ''")
    o.page.get_by_test_id("theme").first.click()  # a mouse click (or a tap) leaves no focus on it
    changed = o.js("document.documentElement.dataset.theme || ''")
    o.page.keyboard.press(" ")  # the pedal
    until(o, "Woodshed.debug().playing === true")
    assert o.js("document.documentElement.dataset.theme || ''") == changed != theme  # not toggled back


def test_on_paper_the_caveat_on_the_chords_is_printed(open_page: Any) -> None:
    o = open_page("pop")
    o.js("Woodshed.current.song.analysis.chords_reliable = false")
    o.js("Woodshed.app.store.set({corrections: Woodshed.app.store.get().corrections + 1})")
    o.page.emulate_media(media="print")
    expect(o.page.get_by_test_id("unreliable")).to_be_visible()  # about the chart: kept on paper
