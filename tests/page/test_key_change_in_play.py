"""A key change where the band meets it (spec 013, round 5): the stage warns on the bar, the guitar's shapes come by
key, the voice panel says the song moves, a doubtful seam says "check by ear"."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

from tests.page.conftest import built
from woodshed import build


def _variant(
    pages_root: str,
    tag: str,
    change_at: int,
    doubt_at: int | None = None,
    back_at: int | None = None,
    same_at: int | None = None,
) -> Path:
    """`lift` (C, then D-flat from bar 17) with its change moved to bar `change_at` + 1, and a doubt there."""
    source = built("lift", False, pages_root)
    folder = source.with_name(f"lift-{tag}.woodshed")
    if folder.exists():
        return folder
    shutil.copytree(source, folder)
    page = folder / "index.html"
    text = page.read_text(encoding="utf-8")
    found = build.DATA_BLOCK.search(text)
    assert found is not None
    data = json.loads(found.group(1))
    data["song"]["key_regions"][1]["bar"] = change_at
    data["view"]["regions"][1]["bar"] = change_at
    if back_at is not None:  # a third region: back to the first key
        data["song"]["key_regions"].append({**data["song"]["key_regions"][0], "bar": back_at})
        data["view"]["regions"].append({**data["view"]["regions"][0], "bar": back_at})
    if same_at is not None:  # the chord of the bar before runs on over the change
        data["song"]["bars"][same_at]["chords"] = [dict(c) for c in data["song"]["bars"][same_at - 1]["chords"]]
    if doubt_at is not None:
        chord = data["song"]["bars"][doubt_at]["chords"][0]
        alternatives = [{"pc": chord["pc"], "quality": "m", "share": 40}]
        chord["doubt"] = {
            "id": 990,
            "why": "Close call between the top candidates.",
            "kind": "chord",
            "alternatives": alternatives,
        }
    page.write_text(text[: found.start(1)] + build.script_json(data) + text[found.end(1) :], encoding="utf-8")
    return folder


def opened(page: Page, folder: Path, lang: str = "en") -> Page:
    page.add_init_script(f"try {{ localStorage.setItem('woodshed:lang', '{lang}') }} catch (e) {{}}")
    page.goto((folder / "index.html").as_uri())
    for _ in range(200):
        if page.evaluate("window.Woodshed && window.Woodshed.ready === true"):
            break
        page.wait_for_timeout(25)
    return page


def at(page: Page, bar: int, playing: bool) -> None:
    """The stage at `bar` (0-based), as while playing or stopped."""
    page.evaluate("([u, playing]) => { Woodshed.app.seekBar(u); Woodshed.app.store.set({ playing }); }", [bar, playing])
    page.wait_for_timeout(150)


def stage(page: Page) -> None:
    page.get_by_test_id("stage-open").click()
    expect(page.get_by_test_id("stage")).to_be_visible()


@pytest.fixture
def mid(pages_root: str) -> Path:
    return _variant(pages_root, "mid", 18, doubt_at=17)  # the change on bar 19, inside the second part


def test_a_change_inside_a_part_is_said_on_the_stage_from_two_bars_before(page: Page, mid: Path) -> None:
    opened(page, mid)
    stage(page)
    key = page.get_by_test_id("stage-key")
    at(page, 15, True)
    expect(key).to_have_text("")  # 3 bars ahead: nothing yet
    at(page, 16, True)
    expect(key).to_have_text("Key change in 2 bars: D♭ major")
    at(page, 17, True)
    expect(key).to_have_text("Key change next bar: D♭ major")
    at(page, 18, True)
    expect(key).to_have_text("Now in D♭ major")
    expect(page.locator("#stTop")).to_contain_text("D♭ major")  # the bar's key, never lost
    at(page, 16, False)
    expect(key).to_have_text("Key change at bar 19: D♭ major")


def test_a_change_at_a_part_start_keeps_the_part_and_adds_its_key(page: Page, pages_root: str) -> None:
    opened(page, built("lift", False, pages_root))
    stage(page)
    at(page, 15, True)
    expect(page.get_by_test_id("stage-coming")).to_contain_text(re.compile(r"next bar · in D♭ major"))
    expect(page.get_by_test_id("stage-key")).to_have_text("")
    expect(page.locator("#stTop")).to_contain_text("C major")


def test_transposed_every_key_text_follows(page: Page, mid: Path) -> None:
    opened(page, mid)
    page.evaluate("Woodshed.app.transposeTo(6)")
    stage(page)
    at(page, 17, True)
    expect(page.get_by_test_id("stage-key")).to_have_text("Key change next bar: G major")


def test_the_guitar_s_shapes_come_by_key_with_a_word_for_the_hands(page: Page, pages_root: str) -> None:
    opened(page, built("lift", False, pages_root))
    page.evaluate("Woodshed.app.setInstrument('guitar')")
    groups = page.get_by_test_id("shape-group")
    expect(groups).to_have_count(2)
    expect(groups.nth(0)).to_have_text("C major")
    expect(groups.nth(1)).to_have_text("From bar 17: D♭ major")
    expect(page.get_by_test_id("shape-hands")).to_have_text(
        "A semitone up: the same shapes one fret higher, as barre chords."
    )
    later = page.locator(".shape-card[data-region='1']")
    expect(later.first).to_be_visible()


def test_the_panel_says_the_key_of_the_bar_playing(page: Page, mid: Path) -> None:
    opened(page, mid)
    page.evaluate("Woodshed.app.setInstrument('voice')")
    badge = page.get_by_test_id("key-now")
    at(page, 17, False)
    expect(badge).to_be_hidden()
    at(page, 19, False)  # the same instrument, no chord change needed: the region changed
    expect(badge).to_be_visible()
    expect(badge).to_have_text("now in D♭ major")


def test_the_voice_panel_says_the_song_moves(page: Page, pages_root: str) -> None:
    opened(page, built("lift", False, pages_root))
    page.evaluate("Woodshed.app.setInstrument('voice')")
    expect(page.get_by_test_id("voice-key-change")).to_have_text("Up a semitone at bar 17: D♭ major.")


def test_a_doubtful_seam_says_check_by_ear(page: Page, mid: Path) -> None:
    opened(page, mid)
    mark = page.get_by_test_id("key-change")
    expect(mark).to_have_text("→ D♭ major · check by ear")
    label = page.locator("#sheet .bar[data-bar='18']").get_attribute("aria-label") or ""
    assert "check by ear around the key change" in label


def test_the_key_note_says_where_the_key_moves(page: Page, pages_root: str) -> None:
    opened(page, built("lift", False, pages_root))
    expect(page.get_by_test_id("key-moves")).to_have_text("D♭ major from bar 17")


def test_a_song_in_one_key_shows_none_of_it(page: Page, pages_root: str) -> None:
    opened(page, built("pop", False, pages_root))
    page.evaluate("Woodshed.app.setInstrument('guitar')")
    expect(page.get_by_test_id("shape-group")).to_have_count(0)
    expect(page.get_by_test_id("key-now")).to_be_hidden()
    page.evaluate("Woodshed.app.setInstrument('voice')")
    expect(page.get_by_test_id("voice-key-change")).to_have_count(0)
    stage(page)
    at(page, 2, True)
    expect(page.get_by_test_id("stage-key")).to_have_text("")


def test_in_french(page: Page, mid: Path) -> None:
    opened(page, mid, "fr")
    stage(page)
    at(page, 17, True)
    expect(page.get_by_test_id("stage-key")).to_have_text("Changement de tonalité à la mesure suivante : D♭ majeur")


def test_inside_a_loop_no_warning_crosses_its_end(page: Page, mid: Path) -> None:
    opened(page, mid)
    stage(page)
    page.evaluate("Woodshed.app.store.set({ loop: [15, 17], loopOn: true })")  # the change (bar 19) is after the loop
    at(page, 16, True)
    expect(page.get_by_test_id("stage-key")).to_have_text("")


def test_two_changes_two_lines_for_the_singer(page: Page, pages_root: str) -> None:
    opened(page, _variant(pages_root, "twice", 18, back_at=24))
    page.evaluate("Woodshed.app.setInstrument('voice')")
    lines = page.get_by_test_id("voice-key-change")
    expect(lines).to_have_count(2)
    expect(lines.nth(0)).to_have_text("Up a semitone at bar 19: D♭ major.")
    expect(lines.nth(1)).to_have_text("Down a semitone at bar 25: C major.")


def test_a_loop_switched_off_no_longer_holds_the_warning_back(page: Page, mid: Path) -> None:
    opened(page, mid)
    stage(page)
    page.evaluate("Woodshed.app.store.set({ loop: [15, 17], loopOn: false })")  # the range kept, the loop off
    at(page, 16, True)
    expect(page.get_by_test_id("stage-key")).to_have_text("Key change in 2 bars: D♭ major")


def test_a_change_on_a_part_s_second_bar_is_warned_from_the_part_before(page: Page, pages_root: str) -> None:
    opened(page, _variant(pages_root, "second", 17))  # the second part starts on bar 17 (index 16)
    stage(page)
    at(page, 15, True)
    expect(page.get_by_test_id("stage-key")).to_have_text("Key change in 2 bars: D♭ major")


def test_back_in_the_start_key_the_badge_goes(page: Page, pages_root: str) -> None:
    opened(page, _variant(pages_root, "twice", 18, back_at=24))
    page.evaluate("Woodshed.app.setInstrument('guitar')")
    at(page, 20, False)
    expect(page.get_by_test_id("key-now")).to_be_visible()
    at(page, 25, False)
    expect(page.get_by_test_id("key-now")).to_be_hidden()


def test_the_lit_shape_is_the_one_of_the_key_playing(page: Page, pages_root: str) -> None:
    opened(page, built("lift", False, pages_root))
    page.evaluate("Woodshed.app.setInstrument('guitar')")
    at(page, 16, False)
    lit = page.locator(".shape-card.cur")
    expect(lit).to_have_count(1)
    expect(lit).to_have_attribute("data-region", "1")


def test_the_shape_groups_follow_the_band_s_key_and_the_language(page: Page, pages_root: str) -> None:
    opened(page, built("lift", False, pages_root), "fr")
    page.evaluate("Woodshed.app.transposeTo(6); Woodshed.app.setInstrument('guitar')")
    groups = page.get_by_test_id("shape-group")
    expect(groups.nth(0)).to_have_text("F♯ majeur")
    expect(groups.nth(1)).to_have_text("Dès la mesure 17 : G majeur")


def test_the_lit_shape_moves_with_the_key_on_the_same_chord(page: Page, pages_root: str) -> None:
    opened(page, _variant(pages_root, "same", 16, same_at=16))  # F on bars 16 and 17, the key changes on 17
    page.evaluate("Woodshed.app.setInstrument('guitar')")
    at(page, 15, False)
    expect(page.locator(".shape-card.cur")).to_have_attribute("data-region", "0")
    page.evaluate("Woodshed.app.transport.seek(Woodshed.current.bars[16].start + 0.05)")  # as playback moves on
    page.wait_for_timeout(300)
    expect(page.locator(".shape-card.cur")).to_have_attribute("data-region", "1")
