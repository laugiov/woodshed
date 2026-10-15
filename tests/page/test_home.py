"""The library home page of `woodshed app`, in a real browser, from upload to playback."""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

from tests import synth
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
