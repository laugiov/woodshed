"""Your part: the instrument alone or left out, at the top of its panel, and its files to take home."""

from __future__ import annotations

import functools
import io
import re
import shutil
import threading
from collections.abc import Iterator
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Browser, expect

from tests import synth
from tests.page.conftest import built
from tests.page.test_band import device, until
from woodshed import app
from woodshed.run import Options, Reporter, first_pass

STEM = {"guitar": "other", "bass": "bass", "piano": "other", "drums": "drums", "voice": "vocals"}


def track(o: Any) -> str:
    return str(o.js("Woodshed.app.store.get().track"))


def test_each_instrument_plays_its_part_alone_without_it_or_the_full_mix(open_page: Any) -> None:
    o = open_page("pop")
    page = o.page
    for inst, stem in STEM.items():
        o.js("(i) => Woodshed.app.setInstrument(i)", inst)
        part = page.get_by_test_id("your-part")
        expect(part).to_be_visible()
        part.get_by_test_id("part-alone").click()
        until(page, f"Woodshed.app.store.get().track === 'solo-{stem}'")
        expect(part.get_by_test_id("part-alone")).to_have_attribute("aria-pressed", "true")
        part.get_by_test_id("part-without").click()
        until(page, f"Woodshed.app.store.get().track === 'minus-{stem}'")
        expect(part.get_by_test_id("part-alone")).to_have_attribute("aria-pressed", "false")
        part.get_by_test_id("part-mix").click()
        until(page, "Woodshed.app.store.get().track === 'mix'")
    # The dock's Tracks menu and the step cards move the same choice.
    o.js("Woodshed.app.setInstrument('bass')")
    o.js("Woodshed.app.setTrack('minus-bass')")
    expect(page.get_by_test_id("part-without")).to_have_attribute("aria-pressed", "true")
    o.js("Woodshed.app.setStep(2, true)")
    expect(page.get_by_test_id("part-alone")).to_have_attribute("aria-pressed", "true")
    # Another instrument's track playing: no choice marked on this panel.
    o.js("Woodshed.app.setStep(1, true); Woodshed.app.setTrack('solo-bass'); Woodshed.app.setInstrument('drums')")
    expect(page.locator("[data-testid=your-part] [aria-pressed=true]")).to_have_count(0)
    assert o.console == []


def test_switching_keeps_the_loop_the_tempo_the_trainer_and_the_focus(open_page: Any) -> None:
    o = open_page("pop")
    page = o.page
    o.js("Woodshed.app.setInstrument('bass'); Woodshed.app.setStep(3, true)")
    before = o.js(
        "(({loop, bpm, trainer, countIn, step}) => ({loop, bpm, trainer, countIn, step}))(Woodshed.app.store.get())"
    )
    page.get_by_test_id("play").click()
    until(page, "Woodshed.debug().playing === true && Woodshed.app.store.get().time > 0.3")
    at = o.js("Woodshed.app.store.get().time")
    alone = page.get_by_test_id("part-alone")
    alone.focus()
    alone.press("Enter")
    until(page, "Woodshed.app.store.get().track === 'solo-bass'")
    page.wait_for_timeout(300)
    assert o.js("Woodshed.debug().playing") is True  # the music goes on
    assert o.js("Woodshed.app.store.get().time") >= at  # from where it was, not from the start
    for beat in (4, 8, 12):  # the bass panel draws itself again at every bar
        o.js("(b) => Woodshed.app.store.set({ beat: b })", beat)
    assert o.js("document.activeElement && document.activeElement.dataset.testid") == "part-alone"
    after = o.js(
        "(({loop, bpm, trainer, countIn, step}) => ({loop, bpm, trainer, countIn, step}))(Woodshed.app.store.get())"
    )
    assert after == before  # step 3 sets no track: it stays marked


def test_a_step_that_plays_another_track_is_no_longer_marked(open_page: Any) -> None:
    o = open_page("pop")
    page = o.page
    o.js("Woodshed.app.setInstrument('bass'); Woodshed.app.setStep(1, true)")
    expect(page.get_by_test_id("step-1")).to_have_class("step on")
    page.get_by_test_id("part-alone").click()
    expect(page.locator(".step.on")).to_have_count(0)
    o.js("Woodshed.app.setStep(2, true)")
    page.get_by_test_id("part-alone").click()  # the track step 2 plays: it stays
    expect(page.get_by_test_id("step-2")).to_have_class("step on")
    o.js("Woodshed.app.setStep(4, true)")
    page.get_by_test_id("tracks").click()
    page.get_by_test_id("track-mix").click()  # the dock's Tracks menu: the same rule
    expect(page.locator(".step.on")).to_have_count(0)


def test_from_disk_the_files_open_and_the_page_says_where_they_are(open_page: Any) -> None:
    o = open_page("pop")
    o.js("Woodshed.app.setInstrument('bass')")
    link = o.page.get_by_test_id("part-download-alone")
    expect(link).to_have_attribute("href", "audio/solo-bass.flac")
    expect(link).to_have_attribute("target", "_blank")  # the rehearsal page stays
    expect(link).not_to_have_attribute("download", re.compile(".*"))  # a file:// link is opened, not downloaded
    with o.page.expect_popup() as popup:
        link.click()
    popup.value.close()
    expect(o.page.get_by_test_id("toast")).to_contain_text(
        "already next to this page, in its audio folder: solo-bass.flac"
    )


@pytest.fixture
def served(pages_root: str) -> Iterator[str]:
    folder = built("pop", True, pages_root)
    handler = functools.partial(SimpleHTTPRequestHandler, directory=str(folder.parent))
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}/{folder.name}/index.html"
    srv.shutdown()
    srv.server_close()


def test_the_files_are_taken_home_from_the_library(browser: Browser, served: str) -> None:
    page = browser.new_context(accept_downloads=True, locale="en-US").new_page()
    page.goto(served)
    until(page, "window.Woodshed && window.Woodshed.ready === true")
    title = page.evaluate("Woodshed.current.song.title")

    def names(inst: str) -> list[str]:
        page.evaluate("(i) => Woodshed.app.setInstrument(i)", inst)
        out = []
        for which in ("alone", "without"):
            with page.expect_download() as info:
                page.get_by_test_id(f"part-download-{which}").click()
            out.append(info.value.suggested_filename)
        return out

    assert names("drums") == [f"{title} - drums alone.flac", f"{title} - without drums.flac"]
    guitars = [f"{title} - guitars and keys alone.flac", f"{title} - without guitars and keys.flac"]
    assert names("guitar") == guitars and names("piano") == guitars
    assert len(page.context.pages) == 1  # downloaded, no tab opened


def test_what_each_part_says(open_page: Any) -> None:
    o = open_page("pop")
    part = o.page.get_by_test_id("your-part")
    o.js("Woodshed.app.setInstrument('guitar')")
    expect(part).to_contain_text("Guitars and keys are one track")
    expect(part).to_contain_text("lossless, about 10 MB per minute of song")
    expect(part.get_by_role("group", name="Listen to")).to_be_visible()
    expect(part.get_by_test_id("part-mix")).to_have_attribute("aria-pressed", "true")
    expect(part).not_to_contain_text("keeps its key")
    o.js("Woodshed.app.transposeTo(2)")
    expect(part).to_contain_text("The recording keeps its key.")
    o.js("Woodshed.app.setInstrument('voice')")
    expect(part).to_contain_text("Separated by software")
    expect(part).not_to_contain_text("Guitars and keys")


def test_a_page_without_the_instruments_tracks_says_where_they_come_from(open_page: Any) -> None:
    o = open_page("pop", stems=False)
    o.js("Woodshed.app.setInstrument('bass')")
    part = o.page.get_by_test_id("your-part")
    expect(part).to_contain_text("Your part's track comes with the separated instruments")
    expect(part.get_by_role("button")).to_have_count(0)
    expect(part.get_by_role("link")).to_have_count(0)


@pytest.fixture
def band_server(pages_root: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[app.AppServer]:
    monkeypatch.setenv("WOODSHED_CACHE", str(tmp_path / "cache"))
    # A library page (its manifest) with the instruments' tracks of a page built with them.
    root = tmp_path / "library"
    first_pass(
        synth.write("pop", tmp_path / "src").wav,
        Options(use_stems=False, open_page=False),
        Reporter(io.StringIO()),
        root,
    )
    stems = built("pop", True, pages_root)
    shutil.copy(stems / "index.html", root / "pop.woodshed" / "index.html")
    shutil.copytree(stems / "audio", root / "pop.woodshed" / "audio", dirs_exist_ok=True)
    srv = app.AppServer(app.Library(tmp_path / "library", Options(use_stems=False, open_page=False)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()
    srv.server_close()


def test_each_device_keeps_its_own_part_in_the_band(browser: Browser, band_server: app.AppServer) -> None:
    problems: list[str] = []
    url = band_server.url + "pop.woodshed/index.html"
    leader = device(browser, url, problems)
    follower = device(browser, url, problems)
    leader.get_by_test_id("band-lead").click()
    until(leader, "Woodshed.band.mode() === 'lead'")
    follower.get_by_test_id("band-follow").click()
    until(follower, "Woodshed.band.mode() === 'follow'")
    for page, inst in ((leader, "drums"), (follower, "bass")):
        page.evaluate("(i) => Woodshed.app.setInstrument(i)", inst)
    follower.get_by_test_id("part-alone").click()
    leader.get_by_test_id("part-without").click()
    until(follower, "Woodshed.app.store.get().track === 'solo-bass'")
    until(leader, "Woodshed.app.store.get().track === 'minus-drums'")
    leader.wait_for_timeout(500)
    assert follower.evaluate("Woodshed.app.store.get().track") == "solo-bass"
    assert problems == []


@pytest.mark.parametrize("lang", ["en", "fr"])
@pytest.mark.parametrize("inst", ["guitar", "bass", "piano", "drums", "voice"])
def test_on_a_phone_the_part_fits_and_is_easy_to_touch(browser: Browser, pages_root: str, lang: str, inst: str) -> None:
    folder = built("pop", True, pages_root)
    context = browser.new_context(
        viewport={"width": 390, "height": 844},
        has_touch=True,
        is_mobile=True,
        locale="fr-FR" if lang == "fr" else "en-US",
    )
    page = context.new_page()
    page.add_init_script(f"try {{ localStorage.setItem('woodshed:lang', '{lang}'); }} catch (e) {{}}")
    page.goto((folder / "index.html").as_uri())
    until(page, "window.Woodshed && window.Woodshed.ready === true")
    page.evaluate("(i) => Woodshed.app.setInstrument(i)", inst)
    part = page.get_by_test_id("your-part")
    part.scroll_into_view_if_needed()
    expect(part).to_contain_text("Ta partie seule" if lang == "fr" else "Your part alone")
    if lang == "fr":
        expect(part).to_contain_text("Le mix sans ta partie (FLAC)")
    for target in part.locator("button, a").all():
        box = target.bounding_box()
        assert box and box["height"] >= 44, target.inner_text()
    wide = page.evaluate(
        "[...document.querySelectorAll('body *')].filter((e) => e.getBoundingClientRect().right > 390.5)"
        ".map((e) => e.className || e.tagName).slice(0, 5)"
    )
    assert page.evaluate("document.documentElement.scrollWidth") <= 390, wide
    context.close()
