"""Moving the bar lines from the page: "Where is beat one?"."""

from __future__ import annotations

import io
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Browser, expect

from tests import synth
from tests.page.test_band import until
from woodshed import app
from woodshed.run import Options, Reporter, first_pass


def test_from_disk_the_sheet_gives_the_command(open_page: Any) -> None:
    o = open_page("pop")
    per = o.js("Woodshed.current.per")
    now = o.js(
        "((Woodshed.current.song.first_beat % Woodshed.current.per) + Woodshed.current.per) % Woodshed.current.per"
    )
    page = o.page
    page.get_by_test_id("edit-chart").click()
    page.get_by_test_id("bar-lines").click()
    dialog = page.get_by_test_id("bars-dialog")
    expect(dialog).to_be_visible()
    expect(page.get_by_test_id("bars-beat")).to_have_count(per)
    expect(page.get_by_test_id("bars-beat").first).to_contain_text("now")
    expect(page.get_by_test_id("bars-command")).to_contain_text(f"--offset {now}")
    page.get_by_test_id("bars-beat").nth(1).click()  # beat 2 is the band's one
    expect(page.get_by_test_id("bars-command")).to_contain_text(f"--offset {(now + 1) % per}")
    expect(page.get_by_test_id("bars-move")).to_have_count(0)  # nothing to send from disk
    page.get_by_test_id("bars-cancel").click()
    expect(dialog).to_be_hidden()


@pytest.fixture
def library(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[app.AppServer]:
    monkeypatch.setenv("WOODSHED_CACHE", str(tmp_path / "cache"))
    srv = app.AppServer(app.Library(tmp_path / "library", Options(use_stems=False, open_page=False)))
    src = srv.library.songs / "pop.wav"
    src.write_bytes(synth.write("pop", tmp_path / "src").wav.read_bytes())
    first_pass(src, srv.library.options(), Reporter(io.StringIO()), srv.library.root)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()
    srv.server_close()


def test_served_the_bar_lines_move_and_typed_chords_stay(browser: Browser, library: app.AppServer) -> None:
    page = browser.new_context(viewport={"width": 1280, "height": 800}, locale="en-US").new_page()
    problems: list[str] = []
    page.on("console", lambda m: problems.append(m.text) if m.type in ("error", "warning") else None)
    page.goto(library.url + "pop.woodshed/index.html")
    until(page, "window.Woodshed && window.Woodshed.ready === true")
    per = page.evaluate("Woodshed.current.per")
    first = page.evaluate("Woodshed.current.song.first_beat")
    page.evaluate("Woodshed.app.typeBars([2], [[4, 'Dsus4']])")  # typed before the move, on beats
    key = str(first + 2 * per)
    page.get_by_test_id("edit-chart").click()
    page.get_by_test_id("bar-lines").click()
    expect(page.get_by_test_id("bars-dialog")).to_contain_text("1 typed bar")
    page.get_by_test_id("bars-beat").nth(1).click()
    page.get_by_test_id("bars-move").click()
    page.wait_for_url("**/pop.woodshed/index.html", wait_until="load", timeout=60_000)
    until(
        page,
        "window.Woodshed && window.Woodshed.ready === true"
        f" && Woodshed.current.song.first_beat % Woodshed.current.per !== {first % per}",
        60,
    )
    expect(page.get_by_test_id("toast")).to_contain_text("The bar lines moved")
    assert page.evaluate(f"!!Woodshed.app.typedBars.get('{key}')")  # kept on its beats
    assert page.evaluate("Woodshed.current.bars.some((b) => b.chords.some((c) => c.typed && c.quality === 'sus4'))")
    assert problems == []
