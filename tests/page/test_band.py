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
        (server.library.root / "pickup.woodshed" / "corrections.json").unlink(missing_ok=True)


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
    expect(page.get_by_test_id("phones")).to_contain_text("--allow-network")  # on loopback: how to open it up
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
