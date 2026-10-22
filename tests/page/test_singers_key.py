"""The recording in the chart's key, in the page (spec 007): the switch, the swap, the sentences, the fallbacks."""

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
from woodshed import app, pitch
from woodshed.run import Options

fake_ffmpeg = worker.fake_ffmpeg  # renders that copy: instant, everywhere


def serve(tmp_path: Path, pages_root: str, **options: Any) -> app.AppServer:
    root = tmp_path / "library"
    shutil.copytree(built("pop", True, pages_root), root / "pop.woodshed")
    summary = {"title": "pop", "key": "C", "bpm": 120, "meter": "4/4", "duration": 16, "doubts": 0, "stems": True}
    (root / "pop.woodshed" / "woodshed.json").write_text(
        json.dumps({"settings": {}, "summary": summary, "complete": True})
    )
    pitch.available.cache_clear()
    srv = app.AppServer(app.Library(root, Options(use_stems=False, open_page=False, **options)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


@pytest.fixture
def server(
    tmp_path: Path, pages_root: str, fake_ffmpeg: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[app.AppServer]:
    monkeypatch.setenv("WOODSHED_CACHE", str(tmp_path / "cache"))
    srv = serve(tmp_path, pages_root)
    yield srv
    srv.library.interrupted()
    srv.shutdown()
    srv.server_close()


def opened(browser: Browser, url: str, problems: list[str], **context: Any) -> Page:
    page = browser.new_context(locale="en-US", **context).new_page()
    page.on("console", lambda m: problems.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: problems.append(str(e)))
    page.goto(url)
    until(page, "window.Woodshed && window.Woodshed.ready === true")
    return page


def playing_file(page: Page, track: str) -> str:
    return str(page.evaluate("(t) => Woodshed.app.transport.fileOf(t)", track))


def test_the_bassist_turns_it_on_and_the_track_is_swapped_in_place(browser: Browser, server: app.AppServer) -> None:
    problems: list[str] = []
    page = opened(browser, server.url + "pop.woodshed/index.html", problems)
    page.evaluate("Woodshed.app.setInstrument('bass')")
    switch = page.get_by_test_id("pitch-switch")
    expect(switch).to_have_count(0)  # the recorded key: nothing to switch
    page.evaluate("Woodshed.app.transposeTo(2)")
    expect(switch).to_have_attribute("aria-pressed", "false")  # off by default for a bassist
    expect(page.get_by_test_id("pitch-line")).to_have_text("The recording keeps its key.")
    expect(page.get_by_test_id("key-note")).to_contain_text("the recording plays in C")
    page.get_by_test_id("play").click()
    until(page, "Woodshed.debug().playing === true && Woodshed.app.store.get().time > 0.3")
    switch.click()
    expect(switch).to_have_attribute("aria-pressed", "true")
    until(page, "Woodshed.app.transport.fileOf('mix').startsWith('audio/key/up2/mix.flac?v=')", 20)
    assert page.evaluate("Woodshed.debug().playing") is True  # swapped without stopping
    expect(page.get_by_test_id("pitch-line")).to_have_text("2 semitones up.")
    expect(page.get_by_test_id("key-note")).to_contain_text("Chords in D, the recording too.")
    expect(page.get_by_test_id("key-mark")).to_have_text("♪ +2")
    # The role's tracks follow; the drums alone never.
    until(page, "Woodshed.app.transport.fileOf('solo-bass').startsWith('audio/key/up2/solo-bass.flac?v=')", 20)
    assert playing_file(page, "solo-drums") == "audio/solo-drums.flac"
    # The downloads stay the originals.
    expect(page.get_by_test_id("part-download-alone")).to_have_attribute("href", "audio/solo-bass.flac")
    switch.click()  # off: the originals again
    until(page, "Woodshed.app.transport.fileOf('mix') === 'audio/mix.flac'")
    expect(page.get_by_test_id("key-mark")).to_be_hidden()
    assert problems == []


def test_a_singer_gets_it_at_once_and_a_choice_made_here_wins(browser: Browser, server: app.AppServer) -> None:
    problems: list[str] = []
    page = opened(browser, server.url + "pop.woodshed/index.html", problems)
    page.evaluate("Woodshed.app.setInstrument('voice')")
    page.evaluate("Woodshed.app.transposeTo(-3)")
    until(page, "Woodshed.app.transport.fileOf('mix').startsWith('audio/key/down3/mix.flac?v=')", 20)
    expect(page.get_by_test_id("pitch-line")).to_have_text("3 semitones down.")
    page.get_by_test_id("pitch-switch").click()  # this device turns it off: off for every role, every song
    page.evaluate("Woodshed.app.setInstrument('bass'); Woodshed.app.setInstrument('voice')")
    expect(page.get_by_test_id("pitch-switch")).to_have_attribute("aria-pressed", "false")
    assert problems == []


def test_drums_alone_play_as_recorded(browser: Browser, server: app.AppServer) -> None:
    problems: list[str] = []
    page = opened(browser, server.url + "pop.woodshed/index.html", problems)
    page.evaluate("Woodshed.app.setInstrument('drums'); Woodshed.app.transposeTo(1)")
    page.get_by_test_id("pitch-switch").click()
    page.get_by_test_id("part-alone").click()
    expect(page.get_by_test_id("pitch-line")).to_have_text("Drums have no pitch: played as recorded.")
    assert problems == []


def test_a_rendered_file_that_will_not_play_falls_back_with_retry(browser: Browser, server: app.AppServer) -> None:
    problems: list[str] = []
    broken = server.library.root / "pop.woodshed" / "audio" / "key" / "up2" / "mix.flac"
    broken.parent.mkdir(parents=True)
    broken.write_bytes(b"not a flac file")  # ready for the library, unplayable for the browser
    page = opened(browser, server.url + "pop.woodshed/index.html", problems)
    page.evaluate("Woodshed.app.setInstrument('bass'); Woodshed.app.transposeTo(2)")
    page.get_by_test_id("pitch-switch").click()
    expect(page.get_by_test_id("pitch-retry")).to_be_visible(timeout=15_000)
    assert playing_file(page, "mix") == "audio/mix.flac"  # the original plays on
    expect(page.get_by_test_id("pitch-line")).to_contain_text("could not be changed")
    broken.unlink()  # the library renders it again on Retry
    page.get_by_test_id("pitch-retry").click()
    until(page, "Woodshed.app.transport.fileOf('mix').startsWith('audio/key/up2/mix.flac?v=')", 20)
    assert [p for p in problems if "not a flac" not in p and "Failed to load" not in p and "Media" not in p] == []


def test_where_the_recording_cannot_change_key_it_says_why(
    browser: Browser, tmp_path: Path, pages_root: str, fake_ffmpeg: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("WOODSHED_CACHE", str(tmp_path / "cache"))
    problems: list[str] = []
    for options, env, sentence in (
        ({"pitch": False}, "1", "is off in this library"),
        ({}, "0", "install the full ffmpeg (with Rubber Band), then restart woodshed"),
    ):
        monkeypatch.setenv("FAKE_RUBBERBAND", env)
        srv = serve(tmp_path / env / str(len(options)), pages_root, **options)
        try:
            page = opened(browser, srv.url + "pop.woodshed/index.html", problems)
            page.evaluate("Woodshed.app.transposeTo(2)")
            expect(page.get_by_test_id("pitch-cannot")).to_contain_text(sentence)
            expect(page.get_by_test_id("pitch-switch")).to_have_count(0)
            page.context.close()
        finally:
            srv.shutdown()
            srv.server_close()
    assert problems == []


def test_from_disk_it_says_where_to_open_the_page(open_page: Any) -> None:
    o = open_page("pop")
    o.js("Woodshed.app.transposeTo(2)")
    expect(o.page.get_by_test_id("pitch-cannot")).to_contain_text("Open the page from the woodshed library")
    assert o.console == []


@pytest.mark.parametrize("lang", ["en", "fr"])
def test_on_a_phone_the_switch_fits(browser: Browser, server: app.AppServer, lang: str) -> None:
    problems: list[str] = []
    page = opened(
        browser, server.url + "pop.woodshed/index.html", problems,
        viewport={"width": 390, "height": 844}, has_touch=True, is_mobile=True,
    )  # fmt: skip
    if lang == "fr":
        page.get_by_test_id("lang-fr").click()
    page.evaluate("Woodshed.app.setInstrument('voice'); Woodshed.app.transposeTo(2)")
    switch = page.get_by_test_id("pitch-switch")
    expect(switch).to_contain_text("demi-tons plus haut" if lang == "fr" else "semitones up")
    box = switch.bounding_box()
    assert box and box["height"] >= 44
    assert page.evaluate("document.documentElement.scrollWidth") <= 390
    assert problems == []
