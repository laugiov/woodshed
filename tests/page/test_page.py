"""The practice page in a real browser: what it shows, how it plays, how it reacts."""

from __future__ import annotations

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
    labels = o.page.get_by_test_id("section").all_inner_texts()
    assert labels == [g["label"] for g in groups]
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
    expect(o.page.get_by_test_id("bar-info")).to_have_text("Bar 3 of 8")


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
    assert s["loopOn"] and s["loop"] == [0, 3]  # the line holding bar 1
    end = o.js("Woodshed.current.bars[4].start")
    o.js(f"Woodshed.app.transport.seek({end} - 0.2)")
    o.page.get_by_test_id("play").click()
    o.page.wait_for_timeout(700)
    assert state(o)["audioTime"] < 3.0  # wrapped to bar 1 (running on would be past 4 s)


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
    expect(o.page.get_by_test_id("bar-info")).to_have_text("Bar 3 of 8")
    o.page.keyboard.press("ArrowLeft")
    expect(o.page.get_by_test_id("bar-info")).to_have_text("Bar 2 of 8")
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


def test_a_doubt_offers_alternatives_and_a_correction_is_remembered(open_page: Any) -> None:
    o = open_page("pickup")
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
    o = open_page("pickup")
    o.page.get_by_test_id("doubt").first.click()
    o.page.get_by_test_id("pick").first.click()  # creates the key for this song
    key = o.js("Object.keys(localStorage).find(k => k.startsWith('woodshed:corrections:'))")
    o.js("([k, v]) => localStorage.setItem(k, v)", [key, stored])
    o.page.reload()
    until(o, "window.Woodshed && window.Woodshed.ready === true")
    assert o.js("Woodshed.current.bars[0].chords.some(c => c.fixed)") is False  # ignored, not applied
    expect(o.page.get_by_test_id("spots")).to_be_visible()


def test_a_doubt_opens_from_the_keyboard(open_page: Any) -> None:
    o = open_page("pickup")
    o.page.get_by_test_id("doubt").first.focus()
    o.page.keyboard.press("Enter")
    expect(o.page.get_by_test_id("doubt-pop")).to_be_visible()
    o.page.keyboard.press("Escape")
    expect(o.page.get_by_test_id("doubt-pop")).to_be_hidden()
    assert o.js("document.activeElement.dataset.testid") == "doubt"  # focus back where it was


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
    end = o.js("Woodshed.current.bars[4].start")
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

    context = browser.new_context(device_scale_factor=1.5)
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
