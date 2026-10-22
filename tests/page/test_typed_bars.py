"""Chords typed on bars: kept by the browser from disk, shared live by the band's library."""

from __future__ import annotations

import json
from typing import Any

from playwright.sync_api import Browser, expect

from tests.page.test_band import device, pickup_server, until  # noqa: F401  (the fixture)
from woodshed import app
from woodshed.build import DATA_BLOCK

BAR1 = "Woodshed.current.bars[1].chords.map((c) => Woodshed.chords.key(c) + 'x' + c.beats).join()"
TYPED = "2|sus4|x2,7||x2"  # Dsus4 for two beats, G for two


def test_from_disk_a_typed_bar_shows_stays_and_goes_back(open_page: Any) -> None:
    o = open_page("pop")
    before = o.js(BAR1)
    o.js("Woodshed.app.typeBars([1], [[2, 'Dsus4'], [2, 'G']])")
    assert o.js(BAR1) == TYPED and o.js("Woodshed.current.bars[1].edited") is True
    assert "Dsus4" in o.js("Woodshed.exports.chordpro(Woodshed.current, null)")
    o.page.reload()
    until(o.page, "window.Woodshed && window.Woodshed.ready === true")
    assert o.js(BAR1) == TYPED  # this browser remembers it for the song
    o.js("Woodshed.app.untypeBar(1)")
    assert o.js(BAR1) == before and o.js("Woodshed.current.bars[1].edited") is False


def test_a_typed_bar_settles_a_doubt_and_its_pick_comes_back_after(open_page: Any) -> None:
    o = open_page("pickup", close_calls=True)
    doubt = o.js("(() => { const d = Woodshed.current.doubts()[0]; return [d.bar, d.chord.doubt.id]; })()")
    u, did = doubt
    count = o.js("Woodshed.current.doubts().length")
    o.js(f"Woodshed.app.typeBars([{u}], [[{o.js('Woodshed.current.per')}, 'Cmaj7']])")
    assert o.js("Woodshed.current.doubts().length") < count  # typed over: nothing left to check there
    o.js(f"Woodshed.app.untypeBar({u})")
    assert o.js("Woodshed.current.doubts().length") == count
    assert did in o.js("Woodshed.current.doubts().map((d) => d.chord.doubt.id)")


def test_one_device_types_a_bar_and_every_device_has_it(browser: Browser, pickup_server: app.AppServer) -> None:  # noqa: F811
    problems: list[str] = []
    server = pickup_server
    url = server.url + "pickup.woodshed/index.html"
    try:
        guitar = device(browser, url, problems)
        bass = device(browser, url, problems)
        guitar.evaluate("Woodshed.app.typeBars([1], [[2, 'Dsus4'], [2, 'G']])")
        until(bass, f"{BAR1} === {json.dumps(TYPED)}")  # live, no reload
        expect(bass.get_by_test_id("toast")).to_contain_text("Bar 2 changed on another device")
        keys = device(browser, url, problems)  # opened later: reads it from the library, says nothing
        assert keys.evaluate(BAR1) == TYPED
        expect(keys.get_by_test_id("toast")).to_be_hidden()
        page = (server.library.root / "pickup.woodshed" / "index.html").read_text(encoding="utf-8")
        song = json.loads(DATA_BLOCK.search(page).group(1))["song"]  # type: ignore[union-attr]
        assert guitar.evaluate("Woodshed.app.editsKey") == app.beats_key(song)  # the library's key
        guitar.evaluate("Woodshed.app.untypeBar(1)")
        until(bass, f"{BAR1} !== {json.dumps(TYPED)}")
        assert server.library.corrections("pickup.woodshed", "x", app.beats_key(song))["edits"]["bars"] == {}
        assert problems == []
    finally:
        (server.library.root / app.CORRECTIONS_DIR / "pickup.woodshed.json").unlink(missing_ok=True)


def test_a_bar_typed_offline_is_shared_when_the_device_comes_back(
    browser: Browser,
    pickup_server: app.AppServer,  # noqa: F811
) -> None:
    problems: list[str] = []
    server = pickup_server
    url = server.url + "pickup.woodshed/index.html"
    try:
        guitar = device(browser, url, problems)
        guitar.context.set_offline(True)
        guitar.evaluate("Woodshed.app.typeBars([1], [[2, 'Dsus4'], [2, 'G']])")  # the library does not hear it
        guitar.wait_for_timeout(300)
        guitar.context.set_offline(False)
        problems.clear()  # the failed share said so on the console
        guitar.evaluate("document.dispatchEvent(new Event('visibilitychange'))")  # the page comes back to the screen
        bass = device(browser, url, problems)
        until(bass, f"{BAR1} === {json.dumps(TYPED)}")
    finally:
        (server.library.root / app.CORRECTIONS_DIR / "pickup.woodshed.json").unlink(missing_ok=True)
