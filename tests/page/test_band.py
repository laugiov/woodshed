"""The band in a real browser: one page leads, another follows its position and its song."""

from __future__ import annotations

import io
import json
import re
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Browser, Page, expect

from tests import synth
from tests.test_band import LAN, needs_lan
from woodshed import app
from woodshed.run import Options, Reporter, first_pass


@pytest.fixture(scope="module")
def library(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("band") / "library"
    src = root.parent / "src"
    for name in ("pop", "waltz"):
        wav = synth.write(name, src).wav
        opts = Options(use_stems=False, open_page=False, beats_per_bar=synth.SONGS[name].beats_per_bar)
        first_pass(wav, opts, Reporter(io.StringIO()), root)
    return root


@pytest.fixture
def server(library: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[app.AppServer]:
    monkeypatch.setenv("WOODSHED_CACHE", str(tmp_path / "cache"))
    srv = app.AppServer(app.Library(library, Options(use_stems=False, open_page=False)))
    srv.library.set_setlist({"songs": ["pop.woodshed", "waltz.woodshed"]})
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()
    srv.server_close()


def until(page: Page, expression: str, timeout: float = 10, arg: Any = None) -> None:
    deadline = time.monotonic() + timeout
    while not page.evaluate(expression, arg):
        if time.monotonic() > deadline:
            raise AssertionError(f"still false after {timeout} s: {expression}")
        page.wait_for_timeout(50)


def device(browser: Browser, url: str, problems: list[str]) -> Page:
    page = browser.new_context(viewport={"width": 1280, "height": 800}, locale="en-US").new_page()
    page.on("console", lambda m: problems.append(m.text) if m.type in ("error", "warning") else None)
    page.on("pageerror", lambda e: problems.append(str(e)))
    page.goto(url)
    until(page, "window.Woodshed && window.Woodshed.ready === true")
    expect(page.get_by_test_id("band")).to_be_visible()
    return page


@pytest.mark.tablet
def test_the_follower_stays_with_the_leader_and_goes_to_the_next_song(browser: Browser, server: app.AppServer) -> None:
    problems: list[str] = []
    url = server.url + "pop.woodshed/index.html"
    leader = device(browser, url, problems)
    follower = device(browser, url, problems)

    leader.get_by_test_id("band-lead").click()
    until(leader, "Woodshed.band.mode() === 'lead'")
    follower.get_by_test_id("band-follow").click()
    expect(follower.get_by_test_id("band-banner")).to_contain_text("Following the leader")

    # The leader goes to bar 5 and plays: the follower is there, without a sound of its own.
    leader.evaluate("Woodshed.app.seekBar(4)")
    leader.get_by_test_id("play").click()
    until(leader, "Woodshed.debug().playing === true")
    until(follower, "Woodshed.debug().playing === true")
    leader_beat = leader.evaluate("Woodshed.debug().beat")
    follower_beat = follower.evaluate("Woodshed.debug().beat")
    assert leader_beat >= 16 and abs(leader_beat - follower_beat) <= 1
    assert follower.evaluate("[...document.querySelectorAll('audio')].every(a => a.paused)")

    # Nothing on the follower moves it or makes sound: clicks, keys, the pedal, the metronome.
    follower.get_by_test_id("bar").first.click()
    expect(follower.get_by_test_id("toast")).to_contain_text("The leader moves the band")
    for key in (" ", "ArrowLeft", "PageUp", "l"):
        follower.keyboard.press(key)
    follower.get_by_test_id("click").click()
    follower.wait_for_timeout(500)
    assert follower.evaluate("[...document.querySelectorAll('audio')].every(a => a.paused)")
    assert abs(leader.evaluate("Woodshed.debug().beat") - follower.evaluate("Woodshed.debug().beat")) <= 1

    leader.get_by_test_id("play").click()
    until(follower, "Woodshed.debug().playing === false")

    # Next song of the set: both pages go there, roles kept.
    expect(leader.get_by_test_id("next-song")).to_contain_text("waltz")
    leader.keyboard.press("n")
    for page in (leader, follower):
        page.wait_for_url("**/waltz.woodshed/index.html**")
    until(follower, "window.Woodshed && window.Woodshed.ready === true && Woodshed.band.mode() === 'follow'")
    until(leader, "window.Woodshed && window.Woodshed.ready === true && Woodshed.band.mode() === 'lead'")
    assert "lead" not in leader.url and "follow" not in follower.url  # a reload asks nothing again
    assert problems == []


def test_a_second_leader_takes_over_and_the_first_one_follows(browser: Browser, server: app.AppServer) -> None:
    problems: list[str] = []
    url = server.url + "pop.woodshed/index.html"
    first = device(browser, url, problems)
    second = device(browser, url, problems)
    first.get_by_test_id("band-lead").click()
    until(first, "Woodshed.band.mode() === 'lead'")
    second.get_by_test_id("band-lead").click()
    until(second, "Woodshed.band.mode() === 'lead'")
    until(first, "Woodshed.band.mode() === 'follow'")
    expect(first.get_by_test_id("toast")).to_contain_text("Another device leads the band")
    assert problems == []


def test_stage_mode_carries_over_to_the_next_song(browser: Browser, server: app.AppServer) -> None:
    problems: list[str] = []
    page = device(browser, server.url + "pop.woodshed/index.html", problems)
    page.get_by_test_id("stage-open").click()
    expect(page.get_by_test_id("stage-next-song")).to_contain_text("Next song: waltz")
    page.keyboard.press("n")
    page.wait_for_url("**/waltz.woodshed/index.html**")
    until(page, "window.Woodshed && window.Woodshed.ready === true")
    expect(page.get_by_test_id("stage")).to_be_visible()
    assert problems == []


def test_the_next_song_is_a_button_on_the_stage(browser: Browser, server: app.AppServer) -> None:
    problems: list[str] = []
    page = device(browser, server.url + "pop.woodshed/index.html", problems)
    page.get_by_test_id("stage-open").click()
    button = page.get_by_test_id("stage-next-song").get_by_role("button")
    expect(button).to_contain_text("waltz")
    button.click()  # a touch screen has no N key
    page.wait_for_url("**/waltz.woodshed/index.html**")
    assert problems == []


def test_a_pedal_on_the_stage_plays_whatever_button_has_the_focus(browser: Browser, server: app.AppServer) -> None:
    problems: list[str] = []
    page = device(browser, server.url + "pop.woodshed/index.html", problems)
    page.get_by_test_id("stage-open").click()
    page.get_by_test_id("stage-next-song").get_by_role("button").focus()  # as after a tap
    page.keyboard.press(" ")  # a page-turner pedal sends Space
    until(page, "Woodshed.debug().playing === true")
    assert "pop.woodshed" in page.url  # still this song
    assert problems == []


CHART = "Woodshed.current.bars[0].chords.map((c) => c.pc + c.quality).join()"


@pytest.fixture
def pickup_server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[app.AppServer]:
    """A library of one song with a chord to check by ear."""
    monkeypatch.setenv("WOODSHED_CACHE", str(tmp_path / "cache"))
    root = tmp_path / "library"
    wav = synth.write("pickup", tmp_path / "src").wav
    first_pass(wav, Options(use_stems=False, open_page=False), Reporter(io.StringIO()), root)
    srv = app.AppServer(app.Library(root, Options(use_stems=False, open_page=False)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()
    srv.server_close()


def test_one_device_corrects_the_chart_of_every_device(browser: Browser, pickup_server: app.AppServer) -> None:
    problems: list[str] = []
    server = pickup_server
    url = server.url + "pickup.woodshed/index.html"
    try:
        guitar = device(browser, url, problems)
        bass = device(browser, url, problems)  # already open: hears it at once
        before = bass.evaluate(CHART)
        guitar.get_by_test_id("doubt").first.click()
        guitar.get_by_test_id("pick").first.click()
        after = guitar.evaluate(CHART)
        assert after != before
        expect(guitar.get_by_test_id("toast")).to_contain_text("every device")
        until(bass, f"{CHART} === {json.dumps(after)}")
        keys = device(browser, url, problems)  # opened later: reads it from the library
        assert keys.evaluate(CHART) == after
        assert problems == []
    finally:
        (server.library.root / app.CORRECTIONS_DIR / "pickup.woodshed.json").unlink(missing_ok=True)


def test_back_to_the_analysis_reaches_every_device_and_stays(browser: Browser, pickup_server: app.AppServer) -> None:
    problems: list[str] = []
    server = pickup_server
    url = server.url + "pickup.woodshed/index.html"
    try:
        guitar = device(browser, url, problems)
        bass = device(browser, url, problems)
        before = bass.evaluate(CHART)
        guitar.get_by_test_id("doubt").first.click()
        guitar.get_by_test_id("pick").first.click()
        after = guitar.evaluate(CHART)
        until(bass, f"{CHART} === {json.dumps(after)}")
        # A device that took the correction and closed: it keeps it in its browser.
        keys_context = browser.new_context(viewport={"width": 1280, "height": 800}, locale="en-US")
        keys = keys_context.new_page()
        keys.goto(url)
        until(keys, f"window.Woodshed && window.Woodshed.ready === true && {CHART} === {json.dumps(after)}")
        keys.close()
        guitar.get_by_test_id("fixed").first.click()
        guitar.get_by_test_id("doubt-reset").click()
        expect(guitar.get_by_test_id("toast")).to_contain_text("Back to the analysis")
        assert guitar.evaluate(CHART) == before
        expect(guitar.get_by_test_id("doubt")).to_have_count(1)  # a doubt to check again
        until(bass, f"{CHART} === {json.dumps(before)}")  # live, no reload
        again = keys_context.new_page()  # comes back with its old copy of the correction
        again.on("console", lambda m: problems.append(m.text) if m.type in ("error", "warning") else None)
        again.goto(url)
        until(again, f"window.Woodshed && window.Woodshed.ready === true && {CHART} === {json.dumps(before)}")
        again.wait_for_timeout(500)
        key = guitar.evaluate("Woodshed.app.fixesKey")
        assert server.library.corrections("pickup.woodshed", key)["fixes"] == {}  # not shared again
        assert problems == []
    finally:
        (server.library.root / app.CORRECTIONS_DIR / "pickup.woodshed.json").unlink(missing_ok=True)


def test_from_disk_there_is_no_band(open_page: Any) -> None:
    o = open_page("pop")
    expect(o.page.get_by_test_id("band")).to_be_hidden()
    expect(o.page.get_by_test_id("next-song")).to_be_hidden()


def test_the_set_list_is_made_on_the_home_page(browser: Browser, server: app.AppServer) -> None:
    server.library.set_setlist({"songs": []})
    problems: list[str] = []
    page = browser.new_context(locale="en-US").new_page()
    page.on("console", lambda m: problems.append(m.text) if m.type in ("error", "warning") else None)
    page.goto(server.url)
    expect(page.get_by_test_id("set-add")).to_have_count(2)
    page.get_by_test_id("set-add").first.click()  # pop
    expect(page.get_by_test_id("set-item")).to_have_count(1)
    expect(page.get_by_test_id("set-add")).to_have_count(1)  # pop's row says "In the set" at once
    page.get_by_test_id("set-add").first.click()  # waltz, the only one left out
    expect(page.get_by_test_id("set-item")).to_have_count(2)
    page.get_by_test_id("set-down").first.click()  # pop after waltz
    expect(page.get_by_test_id("set-item").first).to_contain_text("waltz")
    assert server.library.setlist() == ["waltz.woodshed", "pop.woodshed"]
    page.get_by_test_id("set-remove").first.click()
    expect(page.get_by_test_id("set-item")).to_have_count(1)
    assert server.library.setlist() == ["pop.woodshed"]
    assert problems == []


@needs_lan
def test_the_band_phones_are_let_in_from_the_library_page(browser: Browser, server: app.AppServer) -> None:
    problems: list[str] = []
    page = browser.new_context(locale="en-US").new_page()
    page.on("console", lambda m: problems.append(m.text) if m.type in ("error", "warning") else None)
    page.goto(server.url)
    switch = page.get_by_test_id("network-switch")
    expect(switch).to_have_attribute("aria-checked", "false")
    expect(page.get_by_test_id("phones")).to_contain_text("allow it on private networks")  # the firewall's question
    switch.click()
    expect(switch).to_have_attribute("aria-checked", "true")
    expect(switch).to_be_focused()
    address = f"http://{LAN[0]}:{server.port}/"
    expect(page.get_by_test_id("network-address")).to_contain_text(address)
    expect(page.get_by_test_id("network-qr")).to_have_attribute("aria-label", "Code to scan: " + address)
    expect(page.get_by_test_id("phones")).to_contain_text("allow it on private networks")  # still said once on
    expect(page.get_by_test_id("phones")).to_contain_text("Follow plays along with the device that leads")
    phone = browser.new_context(locale="en-US").new_page()
    phone.goto(address)  # the phone, through the door
    expect(phone.get_by_test_id("phones")).to_contain_text("This device joined the band")
    expect(phone.get_by_test_id("network-switch")).to_have_count(0)
    expect(phone.get_by_test_id("add")).to_be_hidden()
    expect(phone.get_by_test_id("song-row").first).to_be_visible()
    expect(phone.get_by_test_id("add-words")).to_have_count(0)  # the songs have their words, or no parts yet
    switch.click()
    expect(switch).to_have_attribute("aria-checked", "false")
    expect(page.get_by_test_id("network-qr")).to_have_count(0)
    assert server.doors == []
    assert problems == []


def lead_and_follow(browser: Browser, server: app.AppServer, problems: list[str]) -> tuple[Page, Page]:
    url = server.url + "pop.woodshed/index.html"
    leader = device(browser, url, problems)
    follower = device(browser, url, problems)
    leader.get_by_test_id("band-lead").click()
    until(leader, "Woodshed.band.mode() === 'lead'")
    follower.get_by_test_id("band-follow").click()
    until(follower, "Woodshed.band.mode() === 'follow'")
    return leader, follower


def test_a_leader_that_closes_its_page_lets_the_band_go(browser: Browser, server: app.AppServer) -> None:
    problems: list[str] = []
    leader, follower = lead_and_follow(browser, server, problems)
    leader.get_by_test_id("play").click()
    until(follower, "Woodshed.debug().playing === true")
    leader.close(run_before_unload=True)
    # A browser sends the page's release as it closes; a test browser may cut it: then the
    # leader falls silent. Either way the followers stop.
    expect(follower.get_by_test_id("band-banner")).to_contain_text(
        re.compile("Waiting for a leader|The leader is silent"), timeout=8000
    )
    until(follower, "Woodshed.debug().playing === false")
    assert problems == []


def test_a_leader_that_goes_silent_is_shown_as_silent(browser: Browser, server: app.AppServer) -> None:
    problems: list[str] = []
    leader, follower = lead_and_follow(browser, server, problems)
    leader.get_by_test_id("play").click()
    until(follower, "Woodshed.debug().playing === true")
    leader.context.set_offline(True)  # the laptop's Wi-Fi drops: no word, no release
    expect(follower.get_by_test_id("band-banner")).to_contain_text("The leader is silent", timeout=8000)
    until(follower, "Woodshed.debug().playing === false")
    beat = follower.evaluate("Woodshed.debug().beat")
    follower.wait_for_timeout(600)
    assert follower.evaluate("Woodshed.debug().beat") == beat  # it stopped counting on its own
    offline = ("Failed to fetch", "NetworkError", "Failed to load resource", "ERR_INTERNET_DISCONNECTED")
    problems[:] = [p for p in problems if not any(o in p for o in offline)]
    assert problems == []


def test_the_count_in_does_not_start_the_band_early(browser: Browser, server: app.AppServer) -> None:
    problems: list[str] = []
    leader, follower = lead_and_follow(browser, server, problems)
    leader.get_by_test_id("count-in").click()
    leader.get_by_test_id("play").click()  # one bar of clicks, then the recording
    leader.wait_for_timeout(700)
    assert leader.evaluate("Woodshed.app.transport.playing") is False
    assert follower.evaluate("Woodshed.debug().playing") is False
    until(follower, "Woodshed.debug().playing === true")
    assert problems == []


def test_stop_following_plays_on_from_where_the_band_was(browser: Browser, server: app.AppServer) -> None:
    problems: list[str] = []
    leader, follower = lead_and_follow(browser, server, problems)
    leader.evaluate("Woodshed.app.seekBar(5)")
    until(follower, "Woodshed.debug().beat >= 20")
    follower.get_by_text("Stop following").click()
    until(follower, "Woodshed.band.mode() === 'alone'")
    start = leader.evaluate("Woodshed.current.bars[5].start")
    assert abs(follower.evaluate("Woodshed.app.transport.time") - start) < 0.3
    assert problems == []


@pytest.mark.xfail(
    strict=True,
    reason="band.js draws the banner again on every stream event (its Stop following button with it): moves to "
    "the band lot (spec 025 addendum, PR #45)",
)
def test_stop_following_keeps_the_focus_across_stream_events(browser: Browser, server: app.AppServer) -> None:
    problems: list[str] = []
    leader, follower = lead_and_follow(browser, server, problems)
    stop = follower.get_by_text("Stop following")
    stop.focus()
    follower.evaluate(
        "(() => { window.__btn = document.activeElement; window.__fi = 0;"
        " document.getElementById('bandBanner').addEventListener('focusin', () => window.__fi++); })()"
    )
    leader.evaluate("Woodshed.app.seekBar(5)")
    until(follower, "Woodshed.debug().beat >= 20")
    leader.get_by_test_id("play").click()
    until(follower, "Woodshed.debug().playing === true")
    follower.wait_for_timeout(600)
    assert follower.evaluate("document.activeElement === window.__btn")  # the same button: not drawn again
    assert follower.evaluate("window.__fi") == 0  # nor focused again (no re-announcement)
    assert problems == []


def test_a_reload_does_not_take_the_lead_back(browser: Browser, server: app.AppServer) -> None:
    problems: list[str] = []
    first, second = lead_and_follow(browser, server, problems)
    first.keyboard.press("n")  # the band moves to waltz; first still leads
    for page in (first, second):
        page.wait_for_url("**/waltz.woodshed/index.html**")
    until(first, "window.Woodshed && window.Woodshed.ready === true && Woodshed.band.mode() === 'lead'")
    until(second, "window.Woodshed && window.Woodshed.ready === true && Woodshed.band.mode() === 'follow'")
    second.get_by_test_id("band-lead").click()  # the lead changes hands
    until(first, "Woodshed.band.mode() === 'follow'")
    first.get_by_text("Stop following").click()
    first.reload()  # a phone asleep reloads, or Back
    until(first, "window.Woodshed && window.Woodshed.ready === true")
    first.wait_for_timeout(800)
    assert first.evaluate("Woodshed.band.mode()") == "alone"
    assert second.evaluate("Woodshed.band.mode()") == "lead"
    assert problems == []


def test_the_band_key_chosen_on_one_device_reaches_the_others(browser: Browser, server: app.AppServer) -> None:
    try:
        problems: list[str] = []
        url = server.url + "pop.woodshed/index.html"
        singer = device(browser, url, problems)
        guitarist = device(browser, url, problems)
        until(singer, "Woodshed.app.store.get().bandKey === 0")  # the library answered: the recorded key
        expect(singer.get_by_test_id("band-key-keep")).to_have_count(0)  # nothing to keep yet
        singer.evaluate("Woodshed.app.transposeTo(3)")
        expect(singer.get_by_test_id("key-note")).to_contain_text("the recording plays in")  # said while it lasts
        singer.get_by_test_id("band-key-keep").click()
        expect(singer.get_by_test_id("band-key")).to_be_visible()
        until(guitarist, "Woodshed.app.store.get().transpose === 3")  # the open page follows, no reload
        expect(guitarist.get_by_test_id("toast")).to_contain_text("The band plays this song in")
        expect(guitarist.get_by_test_id("band-key")).to_be_visible()
        later = device(browser, url, problems)  # a page opened afterwards starts in the band's key
        until(later, "Woodshed.app.store.get().transpose === 3")
        later.evaluate("Woodshed.app.transposeTo(0)")  # a device may try another key: the band's stays
        expect(later.get_by_test_id("band-key-back")).to_be_visible()
        assert server.library.corrections("pop.woodshed", "x1")["band"]["transpose"] == 3
        server.library.set_band({"page": "pop.woodshed", "note": "capo 2, starts on the chorus"})
        server.live.corrected("pop.woodshed", server.library.revisions["pop.woodshed"])
        expect(guitarist.get_by_test_id("band-note")).to_contain_text("capo 2, starts on the chorus")
        assert problems == []
    finally:  # the library is the module's: the next tests open pop in its recorded key
        (server.library.root / app.CORRECTIONS_DIR / "pop.woodshed.json").unlink(missing_ok=True)


def test_the_leader_runs_the_set_from_the_library_page(browser: Browser, server: app.AppServer) -> None:
    problems: list[str] = []
    page = browser.new_context(locale="en-US").new_page()
    page.on("console", lambda m: problems.append(m.text) if m.type in ("error", "warning") else None)
    try:
        server.library.set_band({"page": "waltz.woodshed", "transpose": 2, "key": "D"})
        page.goto(server.url)
        items = page.get_by_test_id("set-item")
        expect(items).to_have_count(2)
        expect(page.get_by_test_id("set-summary")).to_contain_text("2 songs · ")  # and the set's length
        expect(items.nth(1)).to_contain_text("BPM")
        expect(items.nth(1)).to_contain_text("(the band's key)")  # the key the band plays, not the record's
        # Straight to a place, not one click per place; the keyboard stays with the song.
        items.nth(1).get_by_test_id("set-place").select_option("0")
        expect(items.first).to_contain_text("waltz")
        assert server.library.setlist() == ["waltz.woodshed", "pop.woodshed"]
        expect(items.first.get_by_test_id("set-place")).to_be_focused()
        # A note per song, kept by the library: Enter keeps it, Escape leaves it as it was.
        items.nth(1).get_by_test_id("set-note").click()
        page.get_by_test_id("set-note-input").fill("capo 2, starts on the chorus")
        page.get_by_test_id("set-note-input").press("Enter")
        expect(items.nth(1).get_by_test_id("set-note")).to_have_text("Note: capo 2, starts on the chorus")
        assert server.library.corrections("pop.woodshed", "x1")["band"]["note"] == "capo 2, starts on the chorus"
        items.nth(1).get_by_test_id("set-note").click()
        page.get_by_test_id("set-note-input").fill("something else")
        page.get_by_test_id("set-note-input").press("Escape")
        expect(items.nth(1).get_by_test_id("set-note")).to_have_text("Note: capo 2, starts on the chorus")
        # Finding a song in a long library.
        page.get_by_test_id("find").fill("WAL")
        expect(page.get_by_test_id("song-row")).to_have_count(1)
        page.get_by_test_id("find").fill("nothing like it")
        expect(page.get_by_test_id("no-match")).to_be_visible()
        # Printed: the set alone, with its notes, without the buttons, readable from a stand.
        page.emulate_media(media="print")
        expect(page.get_by_test_id("set-panel")).to_be_visible()
        expect(page.get_by_test_id("set-summary")).to_be_visible()  # the total at the top
        # Measured in one go on the live list: the library's poll redraws it, and a row read while it is
        # replaced has no style (NaN).
        until(
            page,
            "(() => { const li = document.querySelector('[data-testid=set-item]');"
            " return li && li.isConnected && parseFloat(getComputedStyle(li.querySelector('a')).fontSize) > 0; })()",
        )
        title, key, row = page.evaluate(
            "() => { const li = document.querySelector('[data-testid=set-item]');"
            " return [parseFloat(getComputedStyle(li.querySelector('a')).fontSize),"
            " getComputedStyle(li.querySelector('.set-facts .sk')).fontWeight, li.getBoundingClientRect().height]; }"
        )
        assert title >= 24  # 18 pt
        assert int(key) >= 700
        # Facts on the title's row: a song without a note takes one line, some 25 songs an A4 page.
        assert row <= 42
        expect(page.get_by_test_id("library")).to_be_hidden()
        expect(page.get_by_test_id("band-network")).to_be_hidden()
        expect(page.get_by_test_id("set-place").first).to_be_hidden()
        expect(items.nth(1).get_by_test_id("set-note")).to_be_visible()
        assert problems == []
    finally:
        for name in ("pop", "waltz"):
            (server.library.root / app.CORRECTIONS_DIR / f"{name}.woodshed.json").unlink(missing_ok=True)


def test_a_note_open_while_another_is_saved_stays_open(browser: Browser, server: app.AppServer) -> None:
    problems: list[str] = []
    page = browser.new_context(locale="en-US").new_page()
    page.on("console", lambda m: problems.append(m.text) if m.type in ("error", "warning") else None)
    try:
        page.goto(server.url)
        items = page.get_by_test_id("set-item")
        expect(items).to_have_count(2)
        items.first.get_by_test_id("set-note").click()
        page.get_by_test_id("set-note-input").fill("count of 4")
        items.nth(1).get_by_test_id("set-note").click()  # the first is saved on the way
        editor = page.get_by_test_id("set-note-input")
        expect(editor).to_have_count(1)
        expect(items.nth(1).get_by_test_id("set-note-input")).to_be_focused()
        editor.fill("capo 2")
        editor.press("Enter")
        expect(items.first.get_by_test_id("set-note")).to_have_text("Note: count of 4")
        expect(items.nth(1).get_by_test_id("set-note")).to_have_text("Note: capo 2")
        assert problems == []
    finally:
        for name in ("pop", "waltz"):
            (server.library.root / app.CORRECTIONS_DIR / f"{name}.woodshed.json").unlink(missing_ok=True)


@needs_lan
def test_the_library_poll_leaves_the_set_list_as_it_is(browser: Browser, server: app.AppServer) -> None:
    page = browser.new_context(locale="en-US").new_page()
    page.goto(server.url)
    expect(page.get_by_test_id("set-item")).to_have_count(2)
    page.get_by_test_id("set-place").first.evaluate("(el) => { el.dataset.kept = 'yes'; }")
    server.set_door(True)  # the poll sees a change, not in the set
    expect(page.get_by_test_id("network-switch")).to_have_attribute("aria-checked", "true")
    expect(page.get_by_test_id("set-place").first).to_have_attribute("data-kept", "yes")  # not drawn again
    server.set_door(False)


def test_a_removal_made_offline_reaches_the_band_when_the_app_answers_again(
    browser: Browser, pickup_server: app.AppServer
) -> None:
    problems: list[str] = []
    server = pickup_server
    url = server.url + "pickup.woodshed/index.html"
    try:
        guitar = device(browser, url, problems)
        guitar.get_by_test_id("doubt").first.click()
        guitar.get_by_test_id("pick").first.click()
        key = guitar.evaluate("Woodshed.app.fixesKey")
        until(guitar, "Object.keys(Woodshed.app.fixes()).length === 1")
        assert len(server.library.corrections("pickup.woodshed", key)["fixes"]) == 1
        guitar.route("**/api/corrections", lambda route: route.abort())  # the app does not answer
        guitar.get_by_test_id("fixed").first.click()
        guitar.get_by_test_id("doubt-reset").click()
        expect(guitar.get_by_test_id("toast")).to_contain_text("Saved on this device only")
        assert len(server.library.corrections("pickup.woodshed", key)["fixes"]) == 1  # not heard yet
        guitar.unroute("**/api/corrections")
        guitar.evaluate("document.dispatchEvent(new Event('visibilitychange'))")  # back on screen
        deadline = time.monotonic() + 10
        while server.library.corrections("pickup.woodshed", key)["fixes"]:
            assert time.monotonic() < deadline, "the removal was not shared"
            guitar.wait_for_timeout(100)
        until(guitar, "Woodshed.app.pendingRemovals().size === 0")  # heard by the library: nothing left to share
        assert guitar.get_by_test_id("fixed").count() == 0
        removed = server.library.corrections("pickup.woodshed", key)["removed"]
        assert all(fix is not None for fix in removed.values())  # the fix taken back, kept with its removal
    finally:
        (server.library.root / app.CORRECTIONS_DIR / "pickup.woodshed.json").unlink(missing_ok=True)


def test_a_song_page_says_what_each_band_mode_does(browser: Browser, server: app.AppServer) -> None:
    problems: list[str] = []
    size: Any = {"width": 390, "height": 844}
    context = browser.new_context(viewport=size, has_touch=True, is_mobile=True, locale="en-US")
    page = context.new_page()  # a phone: no hover, so the buttons' titles are never seen
    # Firefox's automation layer warns about its own layout calls (chrome://juggler): not the page.
    page.on(
        "console",
        lambda m: problems.append(m.text) if m.type in ("error", "warning") and "juggler" not in m.text else None,
    )
    page.goto(server.url + "pop.woodshed/index.html")
    until(page, "window.Woodshed && window.Woodshed.ready === true")
    hint = page.get_by_test_id("band-hint")
    expect(hint).to_have_text("This device plays on its own.")  # visible text, not a tooltip only
    page.get_by_test_id("band-lead").click()
    expect(hint).to_have_text("This device plays for the whole band: the song, the place, the loop.")
    page.get_by_test_id("band-alone").click()
    sheet = page.evaluate("document.getElementById('sheet').getBoundingClientRect().top")
    assert sheet < 844 - 120  # the chart still starts on the first screen
    context.close()
    assert problems == []


@pytest.mark.parametrize("can_upload", [True, False])
def test_add_the_words_is_offered_on_every_device_of_the_band(
    browser: Browser, server: app.AppServer, can_upload: bool
) -> None:
    context = browser.new_context(locale="en-US")
    page = context.new_page()
    # A song with its parts and no words, as this device or a phone of the band reads the library.
    state = server.library.state()
    state["songs"] = [{**s, "complete": True, "stems": True, "words": False} for s in state["songs"]]
    body = {**state, "addresses": [], "container": False, "can_upload": can_upload, "network": {"on": False}}
    page.route("**/api/songs", lambda route: route.fulfill(json=body))
    try:
        page.goto(server.url)
        expect(page.get_by_test_id("song-row").first).to_be_visible()
        expect(page.get_by_test_id("add-words")).to_have_count(2)  # tapping along: any device (spec 029-2)
    finally:
        context.close()  # the page polls the library: nothing may answer it after the test


def test_a_note_saved_while_another_is_pressed_still_opens_that_one(browser: Browser, server: app.AppServer) -> None:
    """The first note's save comes back between the press and the release on the second note."""
    page = browser.new_context(locale="en-US").new_page()
    try:
        page.goto(server.url)
        items = page.get_by_test_id("set-item")
        expect(items).to_have_count(2)
        items.first.get_by_test_id("set-note").click()
        page.get_by_test_id("set-note-input").fill("count of 4")
        second = items.nth(1).get_by_test_id("set-note")
        box = second.bounding_box()
        assert box
        page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        with page.expect_response("**/api/band"):
            page.mouse.down()  # the first note loses the focus and is saved
        page.wait_for_timeout(100)  # its answer is back and handled while the button is held
        page.mouse.up()
        expect(items.nth(1).get_by_test_id("set-note-input")).to_be_focused()
        expect(items.first.get_by_test_id("set-note")).to_have_text("Note: count of 4")
    finally:
        for name in ("pop", "waltz"):
            (server.library.root / app.CORRECTIONS_DIR / f"{name}.woodshed.json").unlink(missing_ok=True)
