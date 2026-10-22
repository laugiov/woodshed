"""The library home page of `woodshed app`, in a real browser, from upload to playback."""

from __future__ import annotations

import json
import shutil
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Page, expect

from tests import synth
from tests.page.conftest import built
from woodshed import app
from woodshed.run import Options


@pytest.fixture
def server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[app.AppServer]:
    monkeypatch.setenv("WOODSHED_CACHE", str(tmp_path / "cache"))
    srv = app.AppServer(app.Library(tmp_path / "library", Options(use_stems=False, open_page=False)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()
    srv.server_close()


def until(page: Page, expression: str, timeout: float = 60) -> None:
    deadline = time.monotonic() + timeout
    while not page.evaluate(expression):
        if time.monotonic() > deadline:
            raise AssertionError(f"still false after {timeout} s: {expression}")
        page.wait_for_timeout(100)


def test_add_a_song_then_open_and_play_it(page: Page, server: app.AppServer, tmp_path: Path) -> None:
    problems: list[str] = []
    page.on("console", lambda m: problems.append(m.text) if m.type in ("error", "warning") else None)
    page.goto(server.url)
    expect(page.get_by_test_id("summary")).to_have_text("0 songs")
    wav = synth.write("pop", tmp_path / "src").wav
    page.get_by_test_id("file-input").set_input_files(str(wav))
    link = page.get_by_test_id("song-link")
    expect(link).to_have_text("pop", timeout=60_000)
    expect(page.get_by_test_id("song-status").first).to_contain_text("Ready", timeout=60_000)
    link.click()
    until(page, "window.Woodshed && window.Woodshed.ready === true")
    expect(page.get_by_test_id("back")).to_be_visible()  # served by the app: a way back
    page.get_by_test_id("play").click()
    until(page, "Woodshed.debug().audioTime > 0.5", 10)
    page.evaluate("Woodshed.app.transport.seek(10)")  # seeking needs HTTP ranges
    until(page, "Woodshed.debug().audioTime >= 10", 10)
    page.get_by_test_id("back").click()
    expect(page.get_by_test_id("summary")).to_have_text("1 song")
    assert problems == []


def test_options_and_errors_are_shown(page: Page, server: app.AppServer, tmp_path: Path) -> None:
    page.goto(server.url)
    page.get_by_test_id("drop").locator("summary").click()
    page.get_by_test_id("opt-bpm").fill("5")  # out of range: the server says why
    bad = tmp_path / "x.wav"
    bad.write_bytes(b"data")
    page.get_by_test_id("file-input").set_input_files(str(bad))
    expect(page.get_by_test_id("toast")).to_contain_text("BPM")


def test_a_title_cannot_inject_markup_in_the_library(page: Page, server: app.AppServer, tmp_path: Path) -> None:
    wav = synth.write("pop", tmp_path / "src").wav
    named = tmp_path / '<img src=x onerror="window.pwned=1">.wav'
    named.write_bytes(wav.read_bytes())
    page.goto(server.url)
    page.get_by_test_id("file-input").set_input_files(str(named))
    expect(page.get_by_test_id("song-link")).to_be_visible(timeout=60_000)
    assert page.evaluate("window.pwned === undefined")


def test_the_library_shows_the_logo_and_shares_the_theme_with_the_songs(page: Page, server: app.AppServer) -> None:
    page.goto(server.url)
    expect(page.get_by_test_id("logo")).to_be_visible()
    expect(page.locator("html")).to_have_attribute("data-theme", "dark")
    page.get_by_test_id("theme").click()
    expect(page.locator("html")).to_have_attribute("data-theme", "light")
    page.reload()
    expect(page.locator("html")).to_have_attribute("data-theme", "light")  # one choice for the whole library


@pytest.fixture
def songs(tmp_path: Path, pages_root: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[app.AppServer]:
    """Two songs made from one built page: a waltz in F# by an artist with three chords left to check by
    ear, and a plain pop song with nothing to check."""
    monkeypatch.setenv("WOODSHED_CACHE", str(tmp_path / "cache"))
    srv = app.AppServer(app.Library(tmp_path / "library", Options(use_stems=False, open_page=False)))
    made = {
        "Night Drive (The Band)": {"key": "F#", "bpm": 96, "meter": "3/4", "duration": 200, "doubts": 0},
        "Pop": {"key": "C", "bpm": 120, "meter": "4/4", "duration": 16, "doubts": 0},
    }
    for title, facts in made.items():
        page = srv.library.root / f"{title}.woodshed"
        shutil.copytree(built("pop", True, pages_root), page)
        summary = {"title": title, "stems": True, **facts}
        (page / "woodshed.json").write_text(json.dumps({"settings": {}, "summary": summary, "complete": True}))
    # What is left to check comes from the page's doubts and the band's corrections: three, here.
    monkeypatch.setattr(srv.library, "_left_to_check", lambda folder: 3 if folder.name.startswith("Night") else 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()
    srv.server_close()


def row_of(page: Page, title: str) -> Any:
    return page.get_by_test_id("song-row").filter(has=page.get_by_test_id("song-link").get_by_text(title, exact=True))


def test_a_song_reads_as_its_key_name_and_what_its_page_has(page: Page, songs: app.AppServer) -> None:
    page.goto(songs.url)
    night = row_of(page, "Night Drive")
    expect(night.locator(".sub")).to_have_text("The Band")  # the trailing "(…)" apart from the name
    expect(night.locator(".key-tile .k")).to_have_text("F♯")
    expect(night.locator(".key-tile")).to_have_text("Key F♯")  # said, not only drawn
    expect(night.get_by_test_id("song-status")).to_contain_text("96 BPM")
    expect(night.get_by_test_id("song-status")).to_contain_text("3/4")  # an unusual meter is said
    expect(night.get_by_test_id("song-status")).to_contain_text("3 to check")
    expect(night.get_by_test_id("song-status")).to_contain_text("Parts")
    pop = row_of(page, "Pop")
    expect(pop.locator(".sub")).to_have_count(0)
    expect(pop.get_by_test_id("song-status")).not_to_contain_text("4/4")  # the usual one is not
    expect(pop.get_by_test_id("song-status")).not_to_contain_text("to check")
    # The band's key, when the band chose one, is the key shown, and marked so.
    songs.library.set_band({"page": "Pop.woodshed", "transpose": 2, "key": "D"})
    page.reload()
    expect(row_of(page, "Pop").locator(".key-tile")).to_have_text("The band's key D")
    expect(row_of(page, "Pop").locator(".key-tile")).to_have_class("key-tile band")


def test_the_whole_row_opens_the_song_and_its_buttons_stay_its_own(page: Page, songs: app.AppServer) -> None:
    page.goto(songs.url)
    pop = row_of(page, "Pop")
    pop.get_by_test_id("set-add").click()  # the button, not the song
    expect(page.get_by_test_id("set-item")).to_have_count(1)
    expect(page).to_have_url(songs.url)
    box = pop.locator(".key-tile").bounding_box()
    assert box
    page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)  # on the key, off the title
    page.wait_for_url("**/Pop.woodshed/index.html")
    until(page, "window.Woodshed && window.Woodshed.ready === true")
    expect(page.get_by_test_id("back")).to_be_visible()


def test_the_set_sits_beside_the_songs_and_above_them_on_a_phone(page: Page, songs: app.AppServer) -> None:
    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto(songs.url)
    expect(page.get_by_test_id("song-row")).to_have_count(2)
    lib = page.get_by_test_id("library").bounding_box()
    sets = page.get_by_test_id("set-panel").bounding_box()
    assert lib and sets
    assert sets["x"] >= lib["x"] + lib["width"] and sets["y"] < lib["y"] + lib["height"]  # side by side, in view
    page.set_viewport_size({"width": 390, "height": 844})
    lib = page.get_by_test_id("library").bounding_box()
    sets = page.get_by_test_id("set-panel").bounding_box()
    net = page.get_by_test_id("band-network").bounding_box()
    assert lib and sets and net
    assert sets["y"] + sets["height"] <= lib["y"] < net["y"]  # tonight's set, the songs, then the phones
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")  # no sideways scroll
    page.set_viewport_size({"width": 320, "height": 640})
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    # Printed, the set is the whole page: the column that scrolls on screen does not cut it.
    page.set_viewport_size({"width": 1440, "height": 900})
    page.emulate_media(media="print")
    side = page.locator(".home-side").evaluate("(e) => [getComputedStyle(e).maxHeight, getComputedStyle(e).overflowY]")
    assert side == ["none", "visible"]


def test_an_empty_library_welcomes_the_first_song(page: Page, server: app.AppServer, tmp_path: Path) -> None:
    page.goto(server.url)
    expect(page.locator(".drop-title")).to_be_visible()
    expect(page.get_by_test_id("find")).to_be_hidden()  # nothing to find yet
    wav = synth.write("pop", tmp_path / "src").wav
    page.get_by_test_id("file-input").set_input_files(str(wav))
    expect(page.get_by_test_id("song-link")).to_have_text("pop", timeout=60_000)
    expect(page.locator(".drop-title")).to_be_hidden()  # a quiet strip once there are songs
    expect(page.get_by_test_id("drop")).to_be_visible()
    expect(page.get_by_test_id("find")).to_be_visible()


def test_files_dropped_anywhere_on_the_page_are_added(page: Page, server: app.AppServer) -> None:
    page.goto(server.url)
    expect(page.get_by_test_id("summary")).to_have_text("0 songs")
    drop = """(type) => {
        const dt = new DataTransfer();
        dt.items.add(new File(["data"], "x.wav", { type: "audio/wav" }));
        const event = new DragEvent(type, { dataTransfer: dt, bubbles: true, cancelable: true });
        document.querySelector(".foot").dispatchEvent(event);
    }"""
    page.evaluate(drop, "dragenter")
    expect(page.locator("#dropOver")).to_be_visible()  # said where it lands
    page.evaluate(drop, "drop")
    expect(page.locator("#dropOver")).to_be_hidden()
    expect(page.get_by_test_id("toast")).to_contain_text("x.wav")  # sent: the library answers about it


def test_a_finger_gets_room_on_the_library_buttons(browser: Any, songs: app.AppServer) -> None:
    ctx = browser.new_context(viewport={"width": 390, "height": 844}, has_touch=True, is_mobile=True)
    try:
        page = ctx.new_page()
        page.goto(songs.url)
        add = page.get_by_test_id("set-add").first
        expect(add).to_be_visible()
        box = add.bounding_box()
        assert box and box["height"] >= 44 and box["width"] >= 44
    finally:
        ctx.close()
