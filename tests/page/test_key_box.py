"""The Key box on a song with key changes (spec 024a, round 6): every key of the song, the one of the bar at the
cursor lit, + and - still moving the whole song, said alike to a screen reader, in the toasts and on the switch."""

from __future__ import annotations

import json
import shutil
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Browser, Page, expect

from tests import test_pitch_worker as worker
from tests.page.conftest import built
from tests.page.test_band import until
from tests.page.test_key_change_in_play import _variant
from woodshed import app, build, pitch
from woodshed.run import Options

fake_ffmpeg = worker.fake_ffmpeg  # renders that copy: instant, everywhere

INSTRUMENTS = ["guitar", "piano", "bass", "drums", "voice"]


def box(page: Page) -> Any:
    return page.get_by_test_id("transpose")


def lit(page: Page) -> Any:
    return box(page).locator(".kp.here")


def at(page: Page, u: int) -> None:
    page.evaluate("(u) => Woodshed.app.seekBar(u)", u)


def four_keys(pages_root: str) -> Path:
    """`lift` with four key regions: C, D-flat from bar 9, C from bar 13, D-flat from bar 17."""
    source = built("lift", False, pages_root)
    folder = source.with_name("lift-four.woodshed")
    if folder.exists():
        return folder
    shutil.copytree(source, folder)
    page = folder / "index.html"
    text = page.read_text(encoding="utf-8")
    found = build.DATA_BLOCK.search(text)
    assert found is not None
    data = json.loads(found.group(1))
    song, view = data["song"]["key_regions"], data["view"]["regions"]
    data["song"]["key_regions"] = [song[0], {**song[1], "bar": 8}, {**song[0], "bar": 12}, {**song[1], "bar": 16}]
    data["view"]["regions"] = [view[0], {**view[1], "bar": 8}, {**view[0], "bar": 12}, {**view[1], "bar": 16}]
    page.write_text(text[: found.start(1)] + build.script_json(data) + text[found.end(1) :], encoding="utf-8")
    return folder


@pytest.mark.parametrize("inst", INSTRUMENTS)
def test_the_box_says_both_keys_and_lights_the_bar_s(open_page: Any, inst: str) -> None:
    o = open_page("lift", stems=False)
    page = o.page
    o.js("(i) => Woodshed.app.setInstrument(i)", inst)
    at(page, 4)
    expect(box(page)).to_have_text("C → D♭")
    expect(lit(page)).to_have_text("C")
    at(page, 17)
    expect(box(page)).to_have_text("C → D♭")
    expect(lit(page)).to_have_text("D♭")
    expect(box(page).locator(".kp")).to_have_count(2)
    page.evaluate("Woodshed.app.store.set({ playing: true })")  # as while playing
    at(page, 4)
    expect(lit(page)).to_have_text("C")


def test_while_playing_the_lit_key_moves_at_the_change_and_the_text_stays(open_page: Any) -> None:
    o = open_page("lift", stems=False)
    page = o.page
    o.js("Woodshed.app.setInstrument('guitar')")
    o.js("Woodshed.app.transport.seek(Woodshed.current.bars[16].start - 0.6)")
    expect(lit(page)).to_have_text("C")
    page.get_by_test_id("play").click()
    until(page, "Woodshed.app.store.get().beat >= 16 * Woodshed.current.per + 0.5")
    expect(lit(page)).to_have_text("D♭")
    expect(box(page)).to_have_text("C → D♭")
    page.get_by_test_id("play").click()


def test_part_skips_and_the_count_in_light_the_bar_s_key(open_page: Any) -> None:
    o = open_page("lift", stems=False)
    page = o.page
    o.js("Woodshed.app.setInstrument('piano')")
    at(page, 13)
    expect(lit(page)).to_have_text("C")
    o.js("Woodshed.app.nextPart()")  # Part ⏭: the part of the lift, bar 17
    expect(lit(page)).to_have_text("D♭")
    o.js("Woodshed.app.prevPart(); Woodshed.app.prevPart()")  # Part ⏮ twice: the part before
    expect(lit(page)).to_have_text("C")
    # The count-in never moves the cursor: the bar counted into is the cursor's bar, its key lit throughout.
    o.js("Woodshed.app.store.set({ countIn: true }); Woodshed.app.seekBar(16)")  # the first D♭ bar
    page.get_by_test_id("play").click()
    until(page, "Woodshed.app.counting()")
    expect(lit(page)).to_have_text("D♭")
    page.wait_for_timeout(700)
    assert o.js("Woodshed.app.counting()") is True
    expect(lit(page)).to_have_text("D♭")
    expect(box(page)).to_have_text("C → D♭")
    page.get_by_test_id("play").click()  # cancelled


def test_a_loop_across_the_change_lights_c_again_after_the_wrap(open_page: Any) -> None:
    o = open_page("lift", stems=False)
    page = o.page
    o.js("Woodshed.app.setInstrument('guitar')")
    o.js("Woodshed.app.setLoop([14, 17], true)")  # bars 15-18: C, C, D♭, D♭
    o.js("Woodshed.app.transport.seek(Woodshed.current.bars[17].end - 0.5)")
    expect(lit(page)).to_have_text("D♭")
    page.get_by_test_id("play").click()
    until(page, "Woodshed.app.store.get().beat < 16 * Woodshed.current.per")  # wrapped to bar 15
    expect(lit(page)).to_have_text("C")
    expect(box(page)).to_have_text("C → D♭")
    page.get_by_test_id("play").click()


def test_the_chart_s_key_note_names_the_keys_as_the_box(open_page: Any) -> None:
    o = open_page("lift", stems=False)
    o.js("Woodshed.app.transposeTo(1)")
    note = o.page.get_by_test_id("key-note")
    expect(note).to_contain_text("Chords in D♭ → D")
    expect(note).to_contain_text("the recording plays in C → D♭")


def test_the_panel_title_and_the_badge_are_read_apart(open_page: Any) -> None:
    o = open_page("lift", stems=False)
    o.js("Woodshed.app.setInstrument('bass')")
    at(o.page, 17)
    expect(o.page.get_by_test_id("key-now")).to_be_visible()
    # What a screen reader reads of the title line: never "Your bassnow in D♭ major".
    assert o.js("document.querySelector('.desk-head .label').textContent") == "Your bass, now in D♭ major"


def test_two_regions_in_the_same_key_are_lit_by_position(open_page: Any, pages_root: str) -> None:
    o = open_page("lift", stems=False)
    page = o.page
    page.goto((_variant(pages_root, "twice", 18, back_at=24) / "index.html").as_uri())
    until(page, "window.Woodshed && window.Woodshed.ready === true")
    page.evaluate("Woodshed.app.setInstrument('bass')")
    at(page, 25)
    expect(box(page)).to_have_text("C → D♭ → C")
    keys = box(page).locator(".kp")
    expect(keys.nth(2)).to_have_class("kp here")
    expect(keys.nth(0)).to_have_class("kp")
    at(page, 2)
    expect(keys.nth(0)).to_have_class("kp here")
    expect(keys.nth(2)).to_have_class("kp")


def test_more_than_three_keys_the_middle_is_elided_and_never_swapped(open_page: Any, pages_root: str) -> None:
    o = open_page("lift", stems=False)
    page = o.page
    page.goto((four_keys(pages_root) / "index.html").as_uri())
    until(page, "window.Woodshed && window.Woodshed.ready === true")
    page.evaluate("Woodshed.app.setInstrument('guitar')")
    at(page, 2)
    expect(box(page)).to_have_text("C → … → D♭")
    expect(lit(page)).to_have_text("C")
    for u in (9, 13):
        at(page, u)
        expect(box(page)).to_have_text("C → … → D♭")  # the text never changes, only the lit key
        expect(lit(page)).to_have_text("…")
    at(page, 18)
    expect(lit(page)).to_have_text("D♭")


def test_plus_moves_the_whole_song_and_both_keys(open_page: Any) -> None:
    o = open_page("lift", stems=False)
    page = o.page
    o.js("Woodshed.app.setInstrument('guitar')")
    at(page, 17)
    page.get_by_test_id("transpose-up").click()
    expect(box(page)).to_have_text("D♭ → D (+1)")
    expect(lit(page)).to_have_text("D")
    assert o.js("Woodshed.app.store.get().transpose") == 1
    assert o.js("Woodshed.app.store.get().bandKey") is None
    page.get_by_test_id("transpose-down").click()
    page.get_by_test_id("transpose-down").click()
    expect(box(page)).to_have_text("B → C (-1)")
    expect(lit(page)).to_have_text("C")
    # open_page's teardown: no request left the page (the band's key is not saved by +).


def test_a_song_in_one_key_keeps_its_box(open_page: Any) -> None:
    o = open_page("pop", stems=False)
    page = o.page
    o.js("Woodshed.app.setInstrument('guitar')")
    expect(box(page)).to_have_text("C")
    expect(box(page).locator(".kp-arrow")).to_have_count(0)
    page.get_by_test_id("transpose-up").click()
    expect(box(page)).to_have_text("D♭ (+1)")
    group = page.locator(".stepper", has=page.get_by_test_id("transpose"))
    expect(group).to_have_accessible_name("Transpose. Key: D♭ major, transposed +1")


def test_the_screen_reader_hears_both_keys(open_page: Any) -> None:
    o = open_page("lift", stems=False)
    page = o.page
    group = page.locator(".stepper", has=page.get_by_test_id("transpose"))
    expect(group).to_have_accessible_name("Transpose. Key: C major, then D♭ major from bar 17")
    assert box(page).locator(".kp-arrow").first.get_attribute("aria-hidden") == "true"
    page.get_by_test_id("transpose-up").click()
    expect(group).to_have_accessible_name("Transpose. Key: D♭ major, then D major from bar 17, transposed +1")


@pytest.mark.browser_context_args(locale="fr-FR")
def test_the_screen_reader_hears_both_keys_in_french(open_page: Any) -> None:
    o = open_page("lift", stems=False)
    page = o.page
    group = page.locator(".stepper", has=page.get_by_test_id("transpose"))
    expect(group).to_have_accessible_name(
        "Transposer. Tonalité\u00a0: C majeur, puis D♭ majeur à partir de la mesure 17"
    )
    page.get_by_test_id("transpose-up").click()
    expect(group).to_have_accessible_name(
        "Transposer. Tonalité\u00a0: D♭ majeur, puis D majeur à partir de la mesure 17, transposé de +1"
    )


@pytest.mark.browser_context_args(locale="fr-FR", viewport={"width": 390, "height": 844})
def test_on_a_phone_each_label_stays_with_its_box(open_page: Any) -> None:
    o = open_page("lift", stems=False)
    page = o.page
    o.js("Woodshed.app.setInstrument('guitar')")
    at(page, 17)
    o.js("Woodshed.app.transposeTo(6)")  # the widest text: "F♯ → G (+6)"
    page.locator(".desk-col").scroll_into_view_if_needed()
    expect(box(page)).to_have_text("F♯ → G (+6)")

    def middle(selector: str) -> float:
        b = page.locator(selector).bounding_box()
        assert b is not None
        return float(b["y"] + b["height"] / 2)

    expect(page.locator("#capoWrap")).to_be_visible()
    assert abs(middle("#capoWrap") - middle("#capoStepper")) < 6  # "Capo" never alone at a line's end
    assert abs(middle(".keyrow .ctl:first-child > span") - middle("#trVal")) < 6
    right = page.locator("#capoStepper").bounding_box()
    assert right is not None and right["x"] + right["width"] <= 390
    assert page.evaluate("document.documentElement.scrollWidth") <= 390


def test_the_toasts_name_the_keys_as_the_box(open_page: Any) -> None:
    o = open_page("lift", stems=False)
    page = o.page
    page.get_by_test_id("transpose-up").click()
    expect(page.get_by_test_id("toast")).to_contain_text("Transposed to D♭ → D:")
    o.js("Woodshed.app.useBand({ transpose: 2 })")
    expect(page.get_by_test_id("toast")).to_contain_text("The band plays this song in D → E♭:")


def test_one_key_toasts_unchanged(open_page: Any) -> None:
    o = open_page("pop", stems=False)
    page = o.page
    page.get_by_test_id("transpose-up").click()
    expect(page.get_by_test_id("toast")).to_contain_text("Transposed to D♭:")


@pytest.fixture
def lift_server(
    tmp_path: Path, pages_root: str, fake_ffmpeg: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[app.AppServer]:
    monkeypatch.setenv("WOODSHED_CACHE", str(tmp_path / "cache"))
    root = tmp_path / "library"
    shutil.copytree(built("lift", True, pages_root), root / "lift.woodshed")
    summary = {"title": "lift", "key": "C", "bpm": 120, "meter": "4/4", "duration": 56, "doubts": 0, "stems": True}
    (root / "lift.woodshed" / "woodshed.json").write_text(
        json.dumps({"settings": {}, "summary": summary, "complete": True})
    )
    pitch.available.cache_clear()
    srv = app.AppServer(app.Library(root, Options(use_stems=False, open_page=False)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.library.interrupted()
    srv.shutdown()
    srv.server_close()


def test_the_recording_s_pitch_switch_names_the_keys_as_the_box(browser: Browser, lift_server: app.AppServer) -> None:
    from tests.page.test_singers_key import opened

    problems: list[str] = []
    page = opened(browser, lift_server.url + "lift.woodshed/index.html", problems)
    page.evaluate("Woodshed.app.setInstrument('bass'); Woodshed.app.transposeTo(1)")
    expect(page.get_by_test_id("pitch-switch")).to_contain_text("(in D♭ → D)")
    expect(page.get_by_test_id("band-key-keep")).to_have_text("Keep D♭ → D for the band")
    page.context.close()
    assert problems == []
