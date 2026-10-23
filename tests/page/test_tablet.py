"""iPad and tablets (spec 011): the library served to a tablet, iOS's rule that a sound starts only from a tap, and
the iPad's widths. Run in WebKit in CI (`-m tablet --browser webkit`); WebKit on Linux is not iPadOS Safari, so a
real iPad stays the last check (tasks.md)."""

from __future__ import annotations

from typing import Any

import pytest
from playwright.sync_api import Browser, Page, expect

from tests.page import test_my_part
from tests.page.test_awake import NO_LOCK, REFUSED_PLAY, settled
from tests.page.test_band import until
from woodshed import app

pytestmark = pytest.mark.tablet

server = test_my_part.band_server  # a library page with its instruments' tracks, served

# iPadOS Safari says it is a Mac; only its touch points tell it apart.
IPAD = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko)"
    " Version/17.0 Safari/605.1.15"
)
TOUCH_POINTS = "Object.defineProperty(Navigator.prototype, 'maxTouchPoints', { configurable: true, get: () => 5 });"
# play() refused for the tracks or files named in __refuse, as iOS refuses a sound not started by a tap; every
# call counted per element, to see which ones a tap unlocked.
REFUSE = """
window.__refuse = new Set();
window.__odd = new Set();
window.__started = {};
const play = HTMLMediaElement.prototype.play;
HTMLMediaElement.prototype.play = function () {
  const key = this.dataset.track + '|' + this.dataset.file;
  __started[key] = (__started[key] || 0) + 1;
  if (__refuse.has(this.dataset.track) || __refuse.has(this.dataset.file))
    return Promise.reject(new DOMException('no gesture', 'NotAllowedError'));
  if (__odd.has(this.dataset.track)) {
    play.call(this);
    return Promise.reject(new DOMException('odd', 'NotSupportedError'));
  }
  return play.call(this);
};
"""


# As WebKit decides: an element may play once a play() of it ran during a tap. The tap is ours to say:
# Playwright's own calls count as user activation in Chromium, so a tap here is a trusted touchend or click,
# active for a second.
WEBKIT_RULE = """
window.__tap = false;
for (const type of ['touchend', 'click']) window.addEventListener(type, (e) => {
  if (!e.isTrusted) return;
  __tap = true;
  setTimeout(() => { __tap = false; }, 1000);
}, true);
Object.defineProperty(Navigator.prototype, 'userActivation', { configurable: true,
  get: () => ({ isActive: __tap, hasBeenActive: __tap }) });
window.__started = {};
window.__blessed = new WeakSet();
const play = HTMLMediaElement.prototype.play;
HTMLMediaElement.prototype.play = function () {
  const key = this.dataset.track + '|' + this.dataset.file;
  __started[key] = (__started[key] || 0) + 1;
  if (navigator.userActivation.isActive) __blessed.add(this);
  if (!__blessed.has(this)) return Promise.reject(new DOMException('no gesture', 'NotAllowedError'));
  return play.call(this);
};
"""


def tablet(browser: Browser, url: str, problems: list[str], *scripts: str, ipad: bool = True, **context: Any) -> Page:
    options: dict[str, Any] = {"viewport": {"width": 1024, "height": 1366}, "locale": "en-US", **context}
    if ipad:
        options.update(user_agent=IPAD, has_touch=True)
    page = browser.new_context(**options).new_page()
    for script in ((TOUCH_POINTS,) if ipad else ()) + scripts:
        page.add_init_script(script)
    page.on("console", lambda m: problems.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: problems.append(str(e)))
    page.goto(url)
    until(page, "window.Woodshed && window.Woodshed.ready === true")
    return page


def playing(page: Page) -> None:
    page.get_by_test_id("play").click()
    until(page, "Woodshed.debug().playing === true && Woodshed.app.store.get().time > 0.3")


def paused(page: Page, track: str) -> bool:
    return bool(page.evaluate("(t) => document.querySelector(`audio[data-track='${t}']`).paused", track))


def test_a_track_switch_the_browser_refuses_keeps_the_old_track_playing(
    browser: Browser, server: app.AppServer
) -> None:
    problems: list[str] = []
    page = tablet(browser, server.url + "pop.woodshed/index.html", problems, REFUSE, ipad=False)
    playing(page)
    page.evaluate("__refuse.add('solo-bass')")
    assert page.evaluate("Woodshed.app.setTrack('solo-bass')") is False
    expect(page.get_by_test_id("toast")).to_contain_text("Tap the track again to switch.")
    assert page.evaluate("[Woodshed.app.store.get().track, Woodshed.app.transport.track]") == ["mix", "mix"]
    assert not paused(page, "mix")  # the music goes on: no silence
    assert paused(page, "solo-bass")
    page.evaluate("__refuse.clear()")  # the tap again
    assert page.evaluate("Woodshed.app.setTrack('solo-bass')") is True
    until(page, "Woodshed.app.transport.track === 'solo-bass' && Woodshed.app.transport.playing")
    assert paused(page, "mix")
    assert problems == []


def test_a_key_the_browser_refuses_keeps_the_original_file_playing(browser: Browser, server: app.AppServer) -> None:
    problems: list[str] = []
    page = tablet(browser, server.url + "pop.woodshed/index.html", problems, REFUSE, ipad=False)
    playing(page)
    page.evaluate("__refuse.add('audio/minus-bass.flac')")  # a file standing in for a rendered key
    said = page.evaluate("Woodshed.app.transport.setFile('mix', 'audio/minus-bass.flac')")
    assert said == "refused"
    assert page.evaluate("Woodshed.app.transport.fileOf('mix')") == "audio/mix.flac"
    assert not page.evaluate("document.querySelector(`audio[data-file='audio/mix.flac']`).paused")
    assert problems == []


def test_on_an_ipad_the_first_tap_unlocks_every_track(browser: Browser, server: app.AppServer) -> None:
    problems: list[str] = []
    page = tablet(browser, server.url + "pop.woodshed/index.html", problems, WEBKIT_RULE)
    count = page.evaluate("Woodshed.current.tracks.length")
    page.evaluate("document.dispatchEvent(new Event('touchend'))")  # no tap (a scroll's end): nothing unlocked
    assert page.evaluate("Object.keys(__started).length") == 0
    page.get_by_test_id("transpose").tap()  # any tap on the page
    until(page, f"Object.keys(Woodshed.app.transport.elements()).length === {count}")
    states = page.evaluate(
        "Object.values(Woodshed.app.transport.elements()).map((el) => [el.dataset.track, el.paused, el.muted,"
        " __started[el.dataset.track + '|' + el.dataset.file] || 0])"
    )
    assert len(states) == count
    for track, is_paused, muted, started in states:
        assert started == 1, track  # started once in the tap: WebKit lets it play later
        assert is_paused and not muted, track  # and left silent, as it was
    page.get_by_test_id("transpose").tap()
    assert page.evaluate("Object.values(__started).every((n) => n === 1)")  # once is enough
    playing(page)
    page.wait_for_timeout(1200)  # the tap is over: a switch without one, as after a file loads
    assert page.evaluate("Woodshed.app.setTrack('solo-bass')") is True
    until(page, "Woodshed.app.transport.track === 'solo-bass' && Woodshed.app.transport.playing")
    assert problems == []


def test_a_failure_that_is_not_a_refusal_still_switches(browser: Browser, server: app.AppServer) -> None:
    problems: list[str] = []
    page = tablet(browser, server.url + "pop.woodshed/index.html", problems, REFUSE, ipad=False)
    playing(page)
    page.evaluate("__odd.add('solo-bass')")
    assert page.evaluate("Woodshed.app.setTrack('solo-bass')") is True  # not taken for a refused start
    expect(page.get_by_test_id("toast")).not_to_contain_text("Tap the track again")
    problems.clear()  # the error said by the page is the point here


def test_a_computer_unlocks_nothing(browser: Browser, server: app.AppServer) -> None:
    problems: list[str] = []
    page = tablet(browser, server.url + "pop.woodshed/index.html", problems, REFUSE, ipad=False)
    page.get_by_test_id("transpose").click()
    page.wait_for_timeout(300)
    assert page.evaluate("Object.keys(__started).length") == 0
    assert problems == []


def test_an_ipad_following_the_band_is_told_how_to_keep_its_screen_on(browser: Browser, server: app.AppServer) -> None:
    problems: list[str] = []
    url = server.url + "pop.woodshed/index.html?follow=1"
    page = tablet(browser, url, problems, NO_LOCK + REFUSED_PLAY)
    settled(page)
    expect(page.get_by_test_id("awake-line")).to_contain_text("Display & Brightness → Auto-Lock → Never")
    assert problems == []


@pytest.mark.parametrize(
    ("width", "height"),
    [
        (1024, 1366),  # iPad Pro 12.9 portrait
        (1366, 1024),  # and landscape
        (1180, 820),  # iPad Air landscape
        (678, 1000),  # Split View, half
        (507, 1000),  # Split View, a third
        (320, 700),  # Slide Over
    ],
)
def test_every_ipad_width_fits_and_keeps_the_controls_in_reach(open_page: Any, width: int, height: int) -> None:
    o = open_page("pop")
    page = o.page
    page.set_viewport_size({"width": width, "height": height})
    o.js("Woodshed.app.setInstrument('guitar')")
    page.wait_for_timeout(200)
    assert o.js("document.documentElement.scrollWidth <= window.innerWidth")  # no sideways scroll
    for testid in ("play", "part-alone", "transpose-up"):
        target = page.get_by_test_id(testid)
        target.scroll_into_view_if_needed()
        box = target.bounding_box()
        assert box is not None and box["x"] >= 0 and box["x"] + box["width"] <= width, testid
    page.get_by_test_id("part-alone").click()
    until(page, "Woodshed.app.store.get().track === 'solo-other'")
