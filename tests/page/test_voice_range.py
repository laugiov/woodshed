"""The voice panel after a key change (spec 024b, round 6): the range of the ending drawn under the song's, one
sentence saying whether it goes higher, the best key over the whole range, the change line as plain as the best key."""

from __future__ import annotations

import json
import shutil
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Browser, Page, expect
from playwright.sync_api import Error as PlaywrightError

from tests.page.conftest import VARIANTS, rewritten
from tests.page.test_band import until
from woodshed import app, build
from woodshed.run import MANIFEST, Options

NBSP = "\u00a0"


def voice(o: Any, variant: str, lang: str = "en", transpose: int = 0, kind: str | None = None) -> Page:
    """lift's page in `variant`, the voice panel open."""
    o = o("lift", variant=variant)
    page: Page = o.page
    if lang == "fr":
        page.get_by_test_id("lang-fr").click()
    page.evaluate(f"Woodshed.app.setInstrument('voice'); Woodshed.app.transposeTo({transpose})")
    if kind:
        page.get_by_test_id("voice-" + kind).click()
    return page


def ending(page: Page) -> Any:
    return page.get_by_test_id("voice-ending")


def labels(page: Page) -> list[str]:
    texts: list[str] = page.evaluate(
        "[...document.querySelectorAll('#desk .range svg text')].map((t) => t.textContent)"
    )
    return texts


def test_an_ending_inside_the_range_is_said_and_drawn_dashed(open_page: Any) -> None:
    page = voice(open_page, "voice-lift-inside")
    expect(page.get_by_test_id("voice-key-change")).to_have_text("Up a semitone at bar 17: D♭ major.")
    expect(ending(page)).to_have_text("From bar 17 you sing F3 to B♭3: no higher than the rest of the song.")
    expect(ending(page)).not_to_have_class("voice-ending higher")
    bar = page.get_by_test_id("voice-ending-bar")
    expect(bar).to_have_count(1)
    assert bar.get_attribute("stroke-dasharray")  # dashed: a part of the song, not the whole
    assert "Song: F3\u2013D♭4" in labels(page)  # prettified, in the song's first key (C major: D♭)
    assert "From bar 17: F3\u2013B♭3" in labels(page)  # spelled in its own key: B♭3, never A♯3


def test_the_names_move_with_the_transpose(open_page: Any) -> None:
    page = voice(open_page, "voice-lift-inside", transpose=2)
    expect(ending(page)).to_have_text("From bar 17 you sing G3 to C4: no higher than the rest of the song.")
    assert "From bar 17: G3\u2013C4" in labels(page)
    assert "Song: G3\u2013E♭4" in labels(page)


@pytest.mark.tablet
def test_an_ending_that_goes_higher_is_said_in_the_warning_colour(open_page: Any) -> None:
    page = voice(open_page, "voice-lift-higher")
    expect(ending(page)).to_have_text("From bar 17 it goes higher: up to G♭4.")  # in D♭ major: G♭, not F♯
    expect(ending(page)).to_have_class("voice-ending higher")
    colour = page.evaluate("getComputedStyle(document.querySelector('[data-testid=voice-ending]')).color")
    warn = page.evaluate(
        "(() => { const p = document.createElement('p'); p.style.color = 'var(--warn)'; document.body.append(p);"
        " const c = getComputedStyle(p).color; p.remove(); return c; })()"
    )
    assert colour == warn
    assert page.evaluate("getComputedStyle(document.querySelector('[data-testid=voice-ending]')).fontWeight") == "600"


def test_an_ending_that_goes_lower_is_said(open_page: Any) -> None:
    page = voice(open_page, "voice-lift-lower")
    expect(ending(page)).to_have_text("From bar 17 it goes lower: down to D3.")
    expect(ending(page)).to_have_class("voice-ending lower")


def test_a_semitone_above_is_said_without_the_warning(open_page: Any) -> None:
    page = voice(open_page, "voice-lift-semitone")
    expect(ending(page)).to_have_text("From bar 17 it goes higher: up to D4.")
    expect(ending(page)).to_have_class("voice-ending")  # a semitone is within what the measure can tell


def test_an_ending_too_short_to_measure_says_so(open_page: Any) -> None:
    page = voice(open_page, "voice-lift-short")
    expect(ending(page)).to_have_text("From bar 17: too little singing to measure.")
    expect(page.get_by_test_id("voice-ending-bar")).to_have_count(0)


def test_a_long_ending_is_compared_with_the_rest_of_the_song_not_with_itself(open_page: Any) -> None:
    """A third of the song: its top is the whole song's top (E4), but it is higher than the part before (C♯4)."""
    page = voice(open_page, "voice-lift-long")
    expect(ending(page)).to_have_text("From bar 17 it goes higher: up to E4.")
    expect(ending(page)).to_have_class("voice-ending higher")


def test_a_page_not_measured_yet_keeps_its_panel(open_page: Any) -> None:
    page = voice(open_page, "voice-lift-unmeasured")
    expect(page.get_by_test_id("voice-key-change")).to_have_text("Up a semitone at bar 17: D♭ major.")
    expect(ending(page)).to_have_count(0)
    expect(page.get_by_test_id("voice-ending-bar")).to_have_count(0)


def test_two_changes_one_sentence_each_in_its_own_key(open_page: Any) -> None:
    page = voice(open_page, "voice-lift-twice")
    lines = page.locator("[data-testid=voice-key-change], [data-testid=voice-ending]")
    expect(lines).to_have_text(
        [
            "Up a semitone at bar 17: D♭ major.",
            "From bar 17 it goes higher: up to G♭4.",
            "Down a semitone at bar 25: C major.",
            "From bar 25 you sing F3 to C4: no higher than the rest of the song.",
        ]
    )
    expect(page.get_by_test_id("voice-ending-bar")).to_have_count(2)


@pytest.mark.parametrize(
    ("variant", "text"),
    [
        (
            "voice-lift-inside",
            f"À partir de la mesure 17, tu chantes de F3 à B♭3{NBSP}: pas plus haut que le reste du morceau.",
        ),
        ("voice-lift-higher", f"À partir de la mesure 17, ça monte plus haut{NBSP}: jusqu'à G♭4."),
        ("voice-lift-lower", f"À partir de la mesure 17, ça descend plus bas{NBSP}: jusqu'à D3."),
        ("voice-lift-short", f"À partir de la mesure 17{NBSP}: trop peu de chant pour mesurer."),
    ],
)  # fmt: skip
def test_in_french(open_page: Any, variant: str, text: str) -> None:
    page = voice(open_page, variant, "fr")
    expect(ending(page)).to_have_text(text)
    if variant == "voice-lift-inside":
        assert f"À partir de la mesure 17{NBSP}: F3 à B♭3" in labels(page)


@pytest.mark.parametrize(("variant", "best"), [("voice-lift-inside", "-5"), ("voice-lift-higher", "-6")])
def test_the_best_key_fits_the_ending_too(open_page: Any, variant: str, best: str) -> None:
    """A bass voice (E2 to E4): the song's range alone (F3 to C♯4) would go 5 down; with an ending up to G♭4, 6."""
    page = voice(open_page, variant, kind="bass")
    expect(page.get_by_test_id("fit-key")).to_contain_text(f"({best}), ends in")


@pytest.mark.tablet
def test_labels_are_never_clipped(open_page: Any) -> None:
    for width, height in ((1440, 900), (390, 844)):
        page = voice(open_page, "voice-lift-higher", "fr", transpose=6, kind="soprano")
        page.set_viewport_size({"width": width, "height": height})
        page.evaluate("Woodshed.app.transposeTo(5); Woodshed.app.transposeTo(6)")  # drawn at this width
        outside = page.evaluate(
            """() => {
              const svg = document.querySelector('#desk .range svg').getBoundingClientRect();
              return [...document.querySelectorAll('#desk .range svg text')].filter((t) => {
                const r = t.getBoundingClientRect();
                return r.left < svg.left - 0.5 || r.right > svg.right + 0.5;
              }).map((t) => t.textContent);
            }"""
        )
        assert outside == []
        smallest = page.evaluate(
            """() => {
              const svg = document.querySelector('#desk .range svg');
              const scale = svg.getBoundingClientRect().width / svg.viewBox.baseVal.width;
              const sizes = [...svg.querySelectorAll('text')].map((t) => Number(t.getAttribute('font-size')));
              return Math.min(...sizes) * scale;
            }"""
        )
        assert smallest >= 10  # CSS pixels: readable on a phone


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_the_change_line_is_as_plain_as_the_best_key_line(open_page: Any, theme: str) -> None:
    page = voice(open_page, "voice-lift-inside", kind="mezzo")
    if theme == "light":
        page.get_by_test_id("theme").click()
        expect(page.locator("html")).to_have_attribute("data-theme", "light")
    style = """(sel) => { const c = getComputedStyle(document.querySelector(sel));
      return [c.fontSize, c.color]; }"""
    change = page.evaluate(style, "[data-testid=voice-key-change]")
    fit = page.evaluate(style, "#desk .fit")
    ink = page.evaluate("getComputedStyle(document.body).color")
    assert change[0] == fit[0] == "14px"
    assert change[1] == ink
    key = page.locator("[data-testid=voice-key-change] b")
    expect(key).to_have_text("D♭ major")
    bold = "getComputedStyle(document.querySelector('[data-testid=voice-key-change] b'))"
    assert page.evaluate(bold + ".whiteSpace") == "nowrap"  # the key never split from its mode
    accent = page.evaluate("getComputedStyle(document.querySelector('#desk .fit b')).color")
    assert page.evaluate(bold + ".color") == accent


def test_a_song_in_one_key_shows_nothing_new(open_page: Any) -> None:
    o = open_page("ballad")
    o.page.evaluate("Woodshed.app.setInstrument('voice')")
    expect(o.page.get_by_test_id("voice-key-change")).to_have_count(0)
    expect(ending(o.page)).to_have_count(0)
    expect(o.page.get_by_test_id("voice-ending-bar")).to_have_count(0)
    expect(o.page.locator("#desk .range svg rect")).to_have_count(1)  # the song's range alone


@pytest.fixture
def library(tmp_path: Path, pages_root: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[app.AppServer]:
    """lift's page as a page built before the voice range per key (not measured yet), served by a library."""
    monkeypatch.setenv("WOODSHED_CACHE", str(tmp_path / "cache"))
    root = tmp_path / "library"
    shutil.copytree(
        rewritten("lift", pages_root, "voice-lift-unmeasured", VARIANTS["voice-lift-unmeasured"]), PAGE(root)
    )
    summary = {"title": "lift", "key": "C", "bpm": 120, "meter": "4/4", "duration": 58, "doubts": 0, "stems": True}
    (PAGE(root) / MANIFEST).write_text(json.dumps({"settings": {}, "summary": summary, "complete": True}))
    srv = app.AppServer(app.Library(root, Options(use_stems=False, open_page=False)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.library.interrupted()
    srv.shutdown()
    srv.server_close()


def PAGE(root: Path) -> Path:
    return root / "lift.woodshed"


def measured(srv: app.AppServer) -> str:
    """The library's measure, as build.add_vocal_regions leaves the page; the old page's text is returned."""
    index = PAGE(srv.library.root) / "index.html"
    text = index.read_text(encoding="utf-8")
    found = build.DATA_BLOCK.search(text)
    assert found is not None
    data = json.loads(found.group(1))
    data["song"]["parts"]["vocal"]["regions"] = [
        {"bar": 0, "low": 53, "high": 61, "notes": 68},
        {"bar": 16, "low": 53, "high": 58, "notes": 13},
    ]
    index.write_text(text[: found.start(1)] + build.script_json(data) + text[found.end(1) :], encoding="utf-8")
    srv.live.page_updated("lift.woodshed")
    return text


def settled(page: Page, expression: str, timeout: float = 15) -> None:
    """`expression` true, across the page's own reloads."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            if page.evaluate(expression):
                return
        except PlaywrightError:  # loading again
            pass
        assert time.monotonic() < deadline, f"still false after {timeout} s: {expression}"
        page.wait_for_timeout(50)


def listening(srv: app.AppServer) -> None:
    deadline = time.monotonic() + 10
    while srv.live.followers < 1:  # the page listens to the library
        assert time.monotonic() < deadline
        time.sleep(0.05)


def test_an_open_page_loads_again_once_the_library_measured_it(browser: Browser, library: app.AppServer) -> None:
    page = browser.new_context(locale="en-US").new_page()
    page.goto(library.url + "lift.woodshed/index.html")
    until(page, "window.Woodshed && window.Woodshed.ready === true")
    listening(library)
    page.get_by_test_id("stage-open").click()  # on stage, playing
    page.evaluate("window.notReloaded = true; Woodshed.app.togglePlay()")
    until(page, "Woodshed.debug().playing === true")
    measured(library)
    page.wait_for_timeout(1000)
    assert page.evaluate("window.notReloaded === true")  # never under the music
    with page.expect_navigation():  # stopped: the page loads again, with what the library measured
        page.evaluate("Woodshed.app.togglePlay()")
    until(page, "window.Woodshed && window.Woodshed.ready === true && window.notReloaded === undefined")
    until(page, "Woodshed.app.store.get().stage === true")  # still on stage
    page.evaluate("Woodshed.app.setInstrument('voice')")
    expect(page.get_by_test_id("voice-ending")).to_have_count(1)
    page.evaluate("window.notReloaded = true")
    page.wait_for_timeout(1000)
    assert page.evaluate("window.notReloaded === true")  # measured now: loaded once, not again
    page.context.close()


def test_a_page_that_loaded_before_the_measure_never_misses_it(browser: Browser, library: app.AppServer) -> None:
    """The measure lands between the page's load and its first word with the library: still loaded again."""
    old = measured(library)
    page = browser.new_context(locale="en-US").new_page()
    served: list[str] = []

    def first_the_old_page(route: Any) -> None:
        if not served:
            served.append(route.request.url)
            route.fulfill(body=old, content_type="text/html; charset=utf-8")
        else:
            route.continue_()

    page.route("**/lift.woodshed/index.html", first_the_old_page)
    page.goto(library.url + "lift.woodshed/index.html")  # the old page, then the measured one
    settled(page, "window.Woodshed && window.Woodshed.ready === true && !!Woodshed.app.song.parts.vocal.regions")
    assert len(served) == 1
    page.context.close()


def test_a_leading_page_is_not_loaded_again_until_it_leads_no_more(browser: Browser, library: app.AppServer) -> None:
    """A reload does not take the lead back: the band would lose its leader."""
    page = browser.new_context(locale="en-US").new_page()
    page.goto(library.url + "lift.woodshed/index.html")
    until(page, "window.Woodshed && window.Woodshed.ready === true")
    listening(library)
    page.get_by_test_id("band-lead").click()
    until(page, "Woodshed.band.mode() === 'lead'")
    page.evaluate("window.notReloaded = true")
    measured(library)
    page.wait_for_timeout(1500)
    assert page.evaluate("window.notReloaded === true")  # stopped, but leading
    with page.expect_navigation():
        page.get_by_test_id("band-alone").click()  # on its own again: now it loads
    settled(page, "window.Woodshed && window.Woodshed.ready === true && !!Woodshed.app.song.parts.vocal.regions")
    page.context.close()


def test_a_page_already_measured_is_not_loaded_again(browser: Browser, library: app.AppServer) -> None:
    measured(library)
    page = browser.new_context(locale="en-US").new_page()
    page.goto(library.url + "lift.woodshed/index.html")
    until(page, "window.Woodshed && window.Woodshed.ready === true")
    listening(library)
    page.evaluate("window.notReloaded = true")
    page.wait_for_timeout(1000)
    assert page.evaluate("window.notReloaded === true")
    page.context.close()
