"""The set's name on the library page (spec 030): named in place, in the tab and on paper, seen live by every
library open on the band's devices, never overwritten while it is typed."""

from __future__ import annotations

import io
import json
import os
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

from tests import synth
from tests.page.test_band import until
from woodshed import app
from woodshed.run import Options, Reporter, first_pass

NAME = "Les Imprévus · saison 2026-2027"
CASES = json.loads((Path(__file__).parents[1] / "set_name_cases.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def library(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("setname") / "library"
    wav = synth.write("pop", root.parent / "src").wav
    first_pass(wav, Options(use_stems=False, open_page=False), Reporter(io.StringIO()), root)
    return root


@pytest.fixture
def server(library: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[app.AppServer]:
    monkeypatch.setenv("WOODSHED_CACHE", str(tmp_path / "cache"))
    (library / app.SETLIST).unlink(missing_ok=True)
    srv = app.AppServer(app.Library(library, Options(use_stems=False, open_page=False)))
    srv.library.set_setlist({"songs": ["pop.woodshed"]})
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()
    srv.server_close()


def opened(page: Page, srv: app.AppServer) -> Page:
    page.goto(srv.url)
    until(page, "window.Woodshed && window.Woodshed.ready === true")
    expect(page.get_by_test_id("set-panel")).to_be_visible()
    return page


def test_the_band_names_its_set_in_place(page: Page, server: app.AppServer) -> None:
    opened(page, server)
    expect(page.get_by_test_id("set-label")).to_have_text("Set list")
    expect(page.get_by_test_id("set-name")).to_have_count(0)
    page.get_by_test_id("set-name-add").click()
    field = page.get_by_test_id("set-name-input")
    expect(field).to_be_focused()
    expect(field).to_have_attribute("placeholder", "The band, the gig, the season")
    field.fill("  Les   Imprévus  ")
    field.press("Enter")
    expect(page.get_by_test_id("set-name")).to_have_text("Les Imprévus")
    assert server.library.set_title() == "Les Imprévus"
    expect(page).to_have_title("Les Imprévus · woodshed")
    page.get_by_test_id("set-rename").click()
    expect(page.get_by_test_id("set-name-input")).to_have_value("Les Imprévus")
    page.get_by_test_id("set-name-input").fill("Something else")
    page.get_by_test_id("set-name-input").press("Escape")  # cancelled
    expect(page.get_by_test_id("set-name")).to_have_text("Les Imprévus")
    page.get_by_test_id("set-rename").click()
    page.get_by_test_id("set-name-input").fill("")
    page.get_by_test_id("set-name-input").press("Enter")  # emptied: the name is gone
    expect(page.get_by_test_id("set-name-add")).to_be_visible()
    assert server.library.set_title() is None
    expect(page).to_have_title("Library · woodshed")


def test_the_name_in_french_and_on_paper(page: Page, server: app.AppServer) -> None:
    opened(page, server)
    page.get_by_test_id("lang-fr").click()
    expect(page.get_by_test_id("set-name-add")).to_have_text("+ Nommer le set")
    server.library.set_setlist({"title": NAME})
    expect(page.get_by_test_id("set-name")).to_have_text(NAME, timeout=5000)
    expect(page.get_by_test_id("set-rename")).to_have_attribute("aria-label", "Renommer le set")
    expect(page).to_have_title(NAME + " · woodshed")
    page.emulate_media(media="print")
    name = page.get_by_test_id("set-name")
    expect(name).to_be_visible()
    expect(page.get_by_test_id("set-rename")).to_be_hidden()
    assert name.evaluate("e => getComputedStyle(e).fontSize") == "32px"  # 24 pt, the paper's heading
    label = page.get_by_test_id("set-label").bounding_box()
    assert label is not None and name.bounding_box()["y"] < label["y"]  # type: ignore[index]  # the name first


def test_a_long_name_stays_in_its_panel(page: Page, server: app.AppServer) -> None:
    server.library.set_setlist({"title": "Les Imprévus " + "x" * 67})
    for width in (1440, 390, 320):
        page.set_viewport_size({"width": width, "height": 800})
        opened(page, server)
        expect(page.get_by_test_id("set-name")).to_be_visible()
        assert page.get_by_test_id("set-panel").evaluate("p => p.scrollWidth <= p.clientWidth")


def test_the_page_keeps_a_name_as_the_library_does(page: Page, server: app.AppServer) -> None:
    opened(page, server)
    got = page.evaluate(
        """cases => cases.map(([given]) => {
            try { return Woodshed.setName.normalise(given); } catch (err) { return "refused"; }
        })""",
        CASES,
    )
    assert got == [kept for _, kept in CASES]


def test_a_name_given_elsewhere_reaches_an_open_library(page: Page, server: app.AppServer) -> None:
    opened(page, server)
    server.library.set_setlist({"title": NAME})  # another device of the band
    expect(page.get_by_test_id("set-name")).to_have_text(NAME, timeout=5000)
    setlist = server.library.root / app.SETLIST  # a hand edit, or another woodshed on the library
    setlist.write_text(json.dumps({"title": "Les Imprévistes", "songs": ["pop.woodshed"]}), encoding="utf-8")
    stat = setlist.stat()
    os.utime(setlist, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
    expect(page.get_by_test_id("set-name")).to_have_text("Les Imprévistes", timeout=5000)


def test_a_name_being_typed_is_never_overwritten(page: Page, server: app.AppServer) -> None:
    opened(page, server)
    page.get_by_test_id("set-name-add").click()
    page.get_by_test_id("set-name-input").fill("Les Imp")
    server.library.set_setlist({"title": "Another name"})
    page.wait_for_timeout(3500)  # two polls
    expect(page.get_by_test_id("set-name-input")).to_have_value("Les Imp")
    expect(page.get_by_test_id("set-name-input")).to_be_focused()


def test_the_saver_reads_its_own_name_once(page: Page, server: app.AppServer) -> None:
    opened(page, server)
    page.evaluate(
        """() => {
            window.setReads = 0;
            const real = window.fetch;
            window.fetch = (url, opts) => {
                if (String(url).endsWith("/api/setlist") && !(opts && opts.method === "POST")) window.setReads++;
                return real(url, opts);
            };
        }"""
    )
    page.get_by_test_id("set-name-add").click()
    page.get_by_test_id("set-name-input").fill(NAME)
    page.get_by_test_id("set-name-input").press("Enter")
    expect(page.get_by_test_id("set-name")).to_have_text(NAME)
    page.wait_for_timeout(3500)  # two polls with the revision of its own save: nothing read again
    assert page.evaluate("window.setReads") == 0
