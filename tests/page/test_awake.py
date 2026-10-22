"""A phone on the music stand stays awake while the band follows, leads or plays on stage (spec 008)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from playwright.sync_api import Browser, Page, ViewportSize, expect

from tests.page import test_band as band
from tests.page.test_band import until
from woodshed import app

library = band.library  # the band's library of two songs, served
server = band.server
ASSETS = Path(__file__).resolve().parents[2] / "src" / "woodshed" / "page" / "assets"

# A fake Screen Wake Lock: the requests and releases are counted; `refuse` makes the next ones fail.
FAKE_LOCK = """
window.__locks = { asked: 0, released: 0, held: 0, refuse: false, last: null };
Object.defineProperty(navigator, 'wakeLock', { configurable: true, value: { request: async (kind) => {
  __locks.asked += 1;
  if (__locks.refuse) throw new DOMException('refused', 'NotAllowedError');
  const s = new EventTarget();
  s.released = false;
  s.release = async () => {
    if (s.released) return;
    s.released = true; __locks.released += 1; __locks.held -= 1;
    s.dispatchEvent(new Event('release'));  // as a browser does, whoever released it
  };
  __locks.held += 1; __locks.last = s;
  return s;
} } });
"""
NO_LOCK = "Object.defineProperty(navigator, 'wakeLock', { configurable: true, value: undefined });"
# The video's play() refused until a touch (a page loaded without a gesture), then played.
REFUSED_PLAY = """
window.__plays = { asked: 0 , allowed: false };
const play = HTMLMediaElement.prototype.play;
HTMLMediaElement.prototype.play = function () {
  if (!this.classList.contains('awake-video')) return play.call(this);
  __plays.asked += 1;
  if (!__plays.allowed) return Promise.reject(new DOMException('no gesture', 'NotAllowedError'));
  return play.call(this);
};
document.addEventListener('pointerdown', () => { __plays.allowed = true; }, true);
"""
HIDE = """(hidden) => {
  Object.defineProperty(document, 'hidden', { configurable: true, get: () => hidden });
  Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => hidden ? 'hidden' : 'visible' });
  document.dispatchEvent(new Event('visibilitychange'));
}"""
IPHONE = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko)"
    " Version/17.0 Mobile/15E148 Safari/604.1"
)
ANDROID = (
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Mobile Safari/537.36"
)


def settled(page: Page) -> None:
    """Past the delay the page waits before saying anything (W.AWAKE_SETTLE_MS), with room to say it."""
    page.wait_for_timeout(page.evaluate("Woodshed.AWAKE_SETTLE_MS") + 500)


def device(browser: Browser, url: str, script: str, problems: list[str], **context: Any) -> Page:
    size: ViewportSize = {"width": 390, "height": 844} if context.get("is_mobile") else {"width": 1280, "height": 800}
    page = browser.new_context(viewport=size, locale="en-US", **context).new_page()
    page.add_init_script(script)
    page.on("console", lambda m: problems.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: problems.append(str(e)))
    page.goto(url)
    until(page, "window.Woodshed && window.Woodshed.ready === true")
    return page


def test_follow_lead_and_stage_hold_the_screen_and_leaving_lets_it_go(browser: Browser, server: app.AppServer) -> None:
    problems: list[str] = []
    page = device(browser, server.url + "pop.woodshed/index.html", FAKE_LOCK, problems)
    assert page.evaluate("__locks.held") == 0  # practising alone: the phone sleeps as usual
    page.get_by_test_id("band-follow").click()
    until(page, "__locks.held === 1")
    page.evaluate(HIDE, True)  # the browser lets the lock go while the page is hidden
    page.evaluate("__locks.last.release()")
    page.evaluate(HIDE, False)
    until(page, "__locks.held === 1 && __locks.asked === 2")  # asked again when back in view
    page.evaluate("__locks.last.release()")  # dropped by the system, the page still in view
    until(page, "__locks.held === 1 && __locks.asked === 3")  # dropped by the system, the page in view: again
    page.get_by_test_id("band-alone").click()
    until(page, "__locks.held === 0")
    page.get_by_test_id("band-lead").click()
    until(page, "__locks.held === 1")
    page.get_by_test_id("band-alone").click()
    until(page, "__locks.held === 0")
    page.get_by_test_id("stage-open").click()
    until(page, "__locks.held === 1")
    page.get_by_test_id("stage-exit").click()
    until(page, "__locks.held === 0")
    expect(page.get_by_test_id("awake-line")).to_be_hidden()  # a working lock: nothing to say
    assert problems == []


def test_without_a_lock_the_video_keeps_it_awake_from_the_next_touch(browser: Browser, server: app.AppServer) -> None:
    problems: list[str] = []
    page = device(browser, server.url + "pop.woodshed/index.html?follow=1", NO_LOCK + REFUSED_PLAY, problems)
    until(page, "Woodshed.band.mode() === 'follow'")
    video = page.get_by_test_id("awake-video")
    until(page, "__plays.asked >= 1")  # tried at load (a song change reloads the page): refused
    for name in ("muted", "loop", "playsinline"):
        expect(video).to_have_attribute(name, "")
    box = video.bounding_box()
    assert box and box["width"] >= 1 and box["y"] < 800  # in view: a hidden video is paused by browsers
    page.mouse.click(200, 400)  # the musician's first touch
    until(page, "__plays.asked >= 2 && !document.querySelector('.awake-video').paused")
    page.get_by_test_id("band-alone").click()
    until(page, "document.querySelector('.awake-video').paused")
    assert problems == []


def test_a_refused_lock_falls_back_to_the_video(browser: Browser, server: app.AppServer) -> None:
    problems: list[str] = []
    page = device(browser, server.url + "pop.woodshed/index.html", FAKE_LOCK + "__locks.refuse = true;", problems)
    page.get_by_test_id("stage-open").click()  # a gesture: the video plays at once
    until(
        page,
        "__locks.asked >= 1 && !!document.querySelector('.awake-video')"
        " && !document.querySelector('.awake-video').paused",
    )
    assert problems == []


def test_a_follower_holds_again_on_the_next_song(browser: Browser, server: app.AppServer) -> None:
    problems: list[str] = []
    url = server.url + "pop.woodshed/index.html"
    leader = device(browser, url, FAKE_LOCK, problems)
    follower = device(browser, url, FAKE_LOCK, problems)
    leader.get_by_test_id("band-lead").click()
    until(leader, "Woodshed.band.mode() === 'lead'")
    follower.get_by_test_id("band-follow").click()
    until(follower, "__locks.held === 1")
    leader.keyboard.press("n")
    follower.wait_for_url("**/waltz.woodshed/index.html**")
    until(follower, "window.Woodshed && window.Woodshed.ready === true && Woodshed.band.mode() === 'follow'")
    until(follower, "__locks.held === 1")  # the new page holds without a touch
    assert problems == []


def test_the_follower_is_told_how_to_keep_the_screen_on_only_when_it_may_lock(
    browser: Browser, server: app.AppServer
) -> None:
    problems: list[str] = []
    url = server.url + "pop.woodshed/index.html?follow=1"
    page = device(browser, url, NO_LOCK + REFUSED_PLAY, problems, user_agent=IPHONE, has_touch=True, is_mobile=True)
    line = page.get_by_test_id("awake-line")
    expect(line).to_contain_text("Display & Brightness → Auto-Lock → Never")  # worded for an iPhone
    assert page.evaluate("document.getElementById('awakeLine').closest('[role=status],[aria-live]')") is None
    page.get_by_test_id("awake-close").click()
    expect(line).to_be_hidden()
    page.goto(url)  # the next song, or the page opened again
    until(page, "window.Woodshed && window.Woodshed.ready === true && Woodshed.band.mode() === 'follow'")
    settled(page)
    expect(line).to_be_hidden()  # closed once: not again on this device
    assert problems == []


def test_leading_without_a_lock_says_it_once_as_a_toast(browser: Browser, server: app.AppServer) -> None:
    problems: list[str] = []
    url = server.url + "pop.woodshed/index.html"
    page = device(browser, url, NO_LOCK + REFUSED_PLAY, problems, user_agent=ANDROID)
    page.evaluate("() => { HTMLMediaElement.prototype.play = () => Promise.reject(new Error('never')); }")
    page.evaluate("Woodshed.app.toast('Another message being read')")
    page.get_by_test_id("band-lead").click()
    until(page, "Woodshed.band.mode() === 'lead'")
    # Said when no other toast is being read ("leading the band" may be one): within a few seconds.
    expect(page.get_by_test_id("toast")).to_contain_text("Screen timeout → the longest", timeout=12_000)
    expect(page.get_by_test_id("awake-line")).to_be_hidden()  # the line is for followers
    page.get_by_test_id("band-alone").click()
    page.evaluate("document.getElementById('toast').hidden = true")
    page.get_by_test_id("band-lead").click()
    settled(page)
    expect(page.get_by_test_id("toast")).to_be_hidden()  # once per device
    assert problems == []


def test_the_videos_are_tiny_silent_and_ours() -> None:
    mp4, webm = (ASSETS / "awake" / "awake.mp4").read_bytes(), (ASSETS / "awake" / "awake.webm").read_bytes()
    assert len(mp4) < 20_000 and len(webm) < 20_000
    assert b"soun" not in mp4 and b"vide" in mp4  # no audio handler: no audio track to take the phone's session
    assert b"A_" not in webm and b"V_VP8" in webm  # Matroska codec ids: video only
    script = (Path(__file__).resolve().parents[2] / "scripts" / "awake_video.py").read_text(encoding="utf-8")
    assert '"-an"' in script  # made here, without audio


def test_a_follower_back_from_a_locked_screen_is_told_until_the_lock_holds_again(
    browser: Browser, server: app.AppServer
) -> None:
    problems: list[str] = []
    page = device(browser, server.url + "pop.woodshed/index.html?follow=1", FAKE_LOCK, problems)
    until(page, "Woodshed.band.mode() === 'follow' && __locks.held === 1")
    line = page.get_by_test_id("awake-line")
    settled(page)
    expect(line).to_be_hidden()  # a working lock: nothing to say
    page.evaluate("__locks.refuse = true")  # the phone locked; back, the system refuses the lock
    page.evaluate(HIDE, True)
    page.evaluate("__locks.last.release()")
    page.evaluate(HIDE, False)
    expect(line).to_be_visible(timeout=5000)
    page.get_by_test_id("lang-fr").click()
    expect(line).to_contain_text("L'écran")  # said again in the other language
    page.evaluate("__locks.refuse = false")
    page.evaluate(HIDE, True)
    page.evaluate(HIDE, False)
    expect(line).to_be_hidden(timeout=5000)  # held again: the advice goes
    assert problems == []


def test_the_page_lets_the_videos_play_and_nothing_else_in() -> None:
    template = (ASSETS.parent / "template.html").read_text(encoding="utf-8")
    assert "media-src 'self';" in template  # the awake videos come from the page's own folder
