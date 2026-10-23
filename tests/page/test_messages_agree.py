"""The app's messages agree (spec 020): the recording catching up, the phones, the screen-lock line, the band
note, step 4."""

from __future__ import annotations

import json
from typing import Any

import pytest
from playwright.sync_api import Browser, Page, Playwright, Route, expect

from tests.page import test_band as band
from tests.page import test_singers_key as singers
from tests.page.test_awake import FAKE_LOCK, IPHONE, NO_LOCK, REFUSED_PLAY, settled
from tests.page.test_band import until
from woodshed import app

library = band.library  # two songs in the set: pop and waltz
server = band.server
pitch_server = singers.server  # one song, its recording rendered in another key by a fake ffmpeg
fake_ffmpeg = singers.fake_ffmpeg

KEYS = [f"{way}{n}" for way in ("up", "down") for n in range(1, 7)]
# As iOS: a rendered file is refused until a tap, so it waits for one (the "tap" state).
TAP_FIRST = """
const play = HTMLMediaElement.prototype.play;
HTMLMediaElement.prototype.play = function () {
  if ((this.dataset.file || '').startsWith('audio/key/'))
    return Promise.reject(new DOMException('no gesture', 'NotAllowedError'));
  return play.call(this);
};
"""


def opened(browser: Browser, url: str, problems: list[str], **context: Any) -> Page:
    page = browser.new_context(locale="en-US", **context).new_page()
    page.on("console", lambda m: problems.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: problems.append(str(e)))
    page.goto(url)
    until(page, "window.Woodshed && window.Woodshed.ready === true")
    return page


def rendering(page: Page, eta: int | None) -> None:
    """The library renders every key and has not finished any: with an estimate of `eta` seconds, or none yet."""
    state = {"can": True, "off": False, "keys": {}, "versions": {}, "failed": {}, "eta": {}}
    if eta is not None:
        state["eta"] = dict.fromkeys(KEYS, eta)

    def handle(route: Route) -> None:
        if route.request.method == "POST":
            route.fulfill(status=202, content_type="application/json", body='{"state": "queued"}')
        else:
            route.fulfill(status=200, content_type="application/json", body=json.dumps(state))

    page.route("**/api/pitch**", handle)


# R1: one line for the recording while it renders.


@pytest.mark.parametrize(("eta", "said"), [(40, "catches up in about 40 s."), (None, "catches up in a moment.")])
def test_while_the_recording_renders_the_chart_says_it_catches_up(
    browser: Browser, pitch_server: app.AppServer, eta: int | None, said: str
) -> None:
    problems: list[str] = []
    page = browser.new_context(locale="en-US").new_page()
    page.on("pageerror", lambda e: problems.append(str(e)))
    rendering(page, eta)
    page.goto(pitch_server.url + "pop.woodshed/index.html")
    until(page, "window.Woodshed && window.Woodshed.ready === true")
    page.evaluate("Woodshed.app.setInstrument('voice'); Woodshed.app.transposeTo(2)")  # on for a singer
    note = page.get_by_test_id("key-note")
    expect(page.get_by_test_id("pitch-line")).to_contain_text("Preparing the recording 2 semitones up")
    expect(note).to_have_text("Chords in D: the recording " + said)
    assert "plays in" not in note.inner_text()  # never the recorded key next to a switch that says On
    toast = page.get_by_test_id("toast")
    expect(toast).to_have_text(
        "Transposed to D: the chart and the shapes follow; the recording follows when it is ready."
    )
    page.evaluate("Woodshed.app.useBand({ transpose: 3, key: 'Eb' })")  # the band's key, from another device
    expect(toast).to_contain_text("the chords follow. The recording follows when it is ready.")
    page.get_by_test_id("lang-fr").click()
    french = "Accords en E♭\u00a0: l'enregistrement " + (
        "suit dans environ 40\u00a0s." if eta else "suit dans un instant."
    )
    expect(note).to_have_text(french)
    assert problems == []


def test_a_key_already_rendered_follows_at_once_and_says_so(browser: Browser, pitch_server: app.AppServer) -> None:
    problems: list[str] = []
    page = opened(browser, pitch_server.url + "pop.woodshed/index.html", problems)
    page.evaluate("Woodshed.app.setInstrument('voice'); Woodshed.app.transposeTo(2)")
    until(page, "Woodshed.app.transport.fileOf('mix').startsWith('audio/key/up2/mix.flac?v=')", 20)
    page.evaluate("Woodshed.app.transposeTo(0); Woodshed.app.transposeTo(2)")
    toast = page.get_by_test_id("toast")
    expect(toast).to_have_text("Transposed to D: the chart, the shapes and the recording follow.")
    expect(page.get_by_test_id("key-note")).to_have_text("Chords in D, the recording too.")
    assert problems == []


def test_a_render_waiting_for_a_tap_is_said_alike_in_the_chart_and_the_panel(
    browser: Browser, pitch_server: app.AppServer
) -> None:
    problems: list[str] = []
    page = browser.new_context(locale="en-US").new_page()
    page.add_init_script(TAP_FIRST)
    page.on("pageerror", lambda e: problems.append(str(e)))
    page.goto(pitch_server.url + "pop.woodshed/index.html")
    until(page, "window.Woodshed && window.Woodshed.ready === true")
    page.evaluate("Woodshed.app.setInstrument('voice')")
    page.get_by_test_id("play").click()
    until(page, "Woodshed.debug().playing === true")
    page.evaluate("Woodshed.app.transposeTo(2)")
    expect(page.get_by_test_id("pitch-line")).to_have_text("Ready: tap the page to hear it.", timeout=20_000)
    expect(page.get_by_test_id("key-note")).to_have_text("Chords in D: tap the page to hear the recording in it.")
    page.get_by_test_id("lang-fr").click()
    expect(page.get_by_test_id("key-note")).to_have_text(
        "Accords en D\u00a0: touche la page pour y entendre l'enregistrement."
    )
    assert problems == []


def test_switched_off_the_chart_says_the_recorded_key(browser: Browser, pitch_server: app.AppServer) -> None:
    problems: list[str] = []
    page = browser.new_context(locale="en-US").new_page()
    page.on("pageerror", lambda e: problems.append(str(e)))
    rendering(page, 40)
    page.goto(pitch_server.url + "pop.woodshed/index.html")
    until(page, "window.Woodshed && window.Woodshed.ready === true")
    page.evaluate("Woodshed.app.setInstrument('bass'); Woodshed.app.transposeTo(2)")  # off by default for a bassist
    expect(page.get_by_test_id("key-note")).to_have_text("Chords in D: the recording plays in C.")
    expect(page.get_by_test_id("toast")).to_contain_text("The recording keeps its key.")
    assert problems == []


# R2: the phones panel says what 0.4.0 does.


def test_the_phones_panel_says_the_screen_stays_on(browser: Browser, server: app.AppServer) -> None:
    page = browser.new_context(locale="en-US").new_page()

    def let_in(route: Route) -> None:
        if route.request.method != "GET":
            return route.continue_()
        data = route.fetch().json()
        data["addresses"] = ["http://192.168.1.20:8000/"]
        data["network"] = {"on": True, "fixed": False, "can_switch": True, "addresses": data["addresses"]}
        route.fulfill(status=200, content_type="application/json", body=json.dumps(data))

    page.route("**/api/songs", let_in)
    page.goto(server.url)
    phones = page.get_by_test_id("phones")
    expect(phones).to_contain_text(
        "The phones can play, lead and follow, not add songs. Their screen stays on while woodshed shows the music;"
        " if one still locks, the page says how to stop it."
    )
    expect(phones).not_to_contain_text("not to lock")
    page.get_by_test_id("lang-fr").click()
    expect(phones).to_contain_text("Leur écran reste allumé")
    page.context.close()  # the library's poll stops with the page, before the server does


# R3: the screen-lock line, said only when the screen may lock, until the musician taps or closes it.

EVER_SAID = """
window.__said = false;
new MutationObserver(() => {
  const line = document.getElementById('awakeLine');
  if (line && !line.hidden) __said = true;
}).observe(document, { subtree: true, childList: true, attributes: true, attributeFilter: ['hidden'] });
"""


@pytest.mark.tablet
def test_a_following_phone_whose_screen_is_held_never_says_it_may_lock(browser: Browser, server: app.AppServer) -> None:
    problems: list[str] = []
    page = browser.new_context(user_agent=IPHONE, has_touch=True, locale="en-US").new_page()
    for script in (FAKE_LOCK, EVER_SAID):
        page.add_init_script(script)
    page.on("pageerror", lambda e: problems.append(str(e)))
    page.goto(server.url + "pop.woodshed/index.html?follow=1")
    until(page, "window.Woodshed && window.Woodshed.ready === true && Woodshed.band.mode() === 'follow'")
    until(page, "__locks.held === 1")
    settled(page)
    assert page.evaluate("__said") is False  # not even a moment: the lock was on its way
    expect(page.get_by_test_id("awake-line")).to_be_hidden()
    assert problems == []


@pytest.mark.tablet
def test_an_iphone_in_webkit_following_without_fakes_never_says_it_may_lock(
    browser: Browser, playwright: Playwright, server: app.AppServer, browser_name: str
) -> None:
    """Round 5's reproduction: WebKit, an iPhone profile, no autoplay flag. The screen is held (the Wake Lock
    on this secure page, or the muted video): the line must not flash up while it is taken."""
    if browser_name != "webkit":
        pytest.skip("the iPhone's own engine")
    problems: list[str] = []
    page = browser.new_context(**playwright.devices["iPhone 13"], locale="en-US").new_page()
    page.add_init_script(EVER_SAID)
    page.on("pageerror", lambda e: problems.append(str(e)))
    page.goto(server.url + "pop.woodshed/index.html?follow=1")
    until(page, "window.Woodshed && window.Woodshed.ready === true && Woodshed.band.mode() === 'follow'")
    until(page, "Woodshed.awake.holding()")
    settled(page)
    assert page.evaluate("__said") is False
    assert problems == []


@pytest.mark.tablet
def test_a_follower_whose_screen_may_lock_is_told_until_the_first_tap(browser: Browser, server: app.AppServer) -> None:
    problems: list[str] = []
    page = browser.new_context(user_agent=IPHONE, has_touch=True, locale="en-US").new_page()
    for script in (NO_LOCK, REFUSED_PLAY):
        page.add_init_script(script)
    page.on("pageerror", lambda e: problems.append(str(e)))
    page.goto(server.url + "pop.woodshed/index.html?follow=1")
    until(page, "window.Woodshed && window.Woodshed.ready === true && Woodshed.band.mode() === 'follow'")
    line = page.get_by_test_id("awake-line")
    expect(line).to_contain_text("Settings → Display & Brightness → Auto-Lock → Never")  # the iPhone's path
    page.wait_for_timeout(10_000)
    expect(line).to_be_visible()  # still there: read on the stand, not a passing toast
    page.mouse.click(200, 500)  # the first tap: the video keeps the screen on
    until(page, "!document.querySelector('.awake-video').paused")
    expect(line).to_be_hidden(timeout=5000)
    assert problems == []


# R4: the band note reads as a note, and belongs to the set.


def test_the_band_note_is_ink_with_a_muted_label(browser: Browser, server: app.AppServer) -> None:
    problems: list[str] = []
    try:
        server.library.set_band({"page": "pop.woodshed", "note": "capo 2, starts on the chorus"})
        page = opened(browser, server.url + "pop.woodshed/index.html", problems)
        note = page.get_by_test_id("band-note")
        expect(note).to_contain_text("capo 2, starts on the chorus")
        colours = page.evaluate(
            """() => {
              const probe = (v) => { const s = document.createElement('span'); s.style.color = `var(${v})`;
                document.body.appendChild(s); const c = getComputedStyle(s).color; s.remove(); return c; };
              const note = document.querySelector('[data-testid=band-note]');
              const label = note.querySelector('.note-label');
              return { note: getComputedStyle(note).color, label: getComputedStyle(label).color,
                       ink: probe('--ink'), muted: probe('--muted'), warn: probe('--warn') };
            }"""
        )
        assert colours["note"] != colours["warn"]
        assert colours["note"] == colours["ink"]
        assert colours["label"] == colours["muted"]
        expect(note.locator(".note-label")).to_have_text("Note:")
        page.get_by_test_id("lang-fr").click()
        expect(note.locator(".note-label")).to_have_text("Note\u00a0:")
        assert problems == []
    finally:
        (server.library.root / app.CORRECTIONS_DIR / "pop.woodshed.json").unlink(missing_ok=True)


def test_a_song_out_of_the_set_loses_its_note_on_every_page(browser: Browser, server: app.AppServer) -> None:
    problems: list[str] = []
    try:
        server.library.set_band({"page": "pop.woodshed", "transpose": 2, "key": "D", "note": "starts on the chorus"})
        song = opened(browser, server.url + "pop.woodshed/index.html", problems)
        expect(song.get_by_test_id("band-note")).to_contain_text("starts on the chorus")
        home = opened(browser, server.url, problems)
        row = home.locator('[data-set-song="pop.woodshed"]')
        expect(row.get_by_test_id("set-note")).to_have_text("Note: starts on the chorus")  # labelled as in the page
        expect(row.get_by_test_id("set-remove")).to_have_attribute("title", "Out of the set, and its note with it")
        ink, warn, said = home.evaluate(
            """() => ['--ink', '--warn'].map((v) => {
                const s = document.createElement('span'); s.style.color = `var(${v})`;
                document.body.appendChild(s); const c = getComputedStyle(s).color; s.remove(); return c; })
              .concat([getComputedStyle(document.querySelector('[data-testid=set-note] [translate=no]')).color])"""
        )
        assert said == ink != warn  # a note, not a warning, in the set as in the page
        home.route("**/api/songs", lambda route: None)  # the library's next answer is late: the page alone
        row.get_by_test_id("set-remove").click()
        expect(home.get_by_test_id("set-item")).to_have_count(1)
        assert "note" not in server.library.corrections("pop.woodshed", "x1")["band"]
        assert server.library.corrections("pop.woodshed", "x1")["band"]["transpose"] == 2  # the key stays
        expect(song.get_by_test_id("band-note")).to_have_count(0)  # the open page hears it, no reload
        home.get_by_test_id("set-add").first.click()  # back in the set: a fresh line for a note
        expect(home.locator('[data-set-song="pop.woodshed"]').get_by_test_id("set-note")).to_have_text("+ Note")
        assert problems == []
        home.context.close()
    finally:
        (server.library.root / app.CORRECTIONS_DIR / "pop.woodshed.json").unlink(missing_ok=True)
        server.library.set_setlist({"songs": ["pop.woodshed", "waltz.woodshed"]})


# R5: step 4 is not the Play button.


def test_step_4_is_playing_with_the_band(browser: Browser, server: app.AppServer) -> None:
    problems: list[str] = []
    page = opened(browser, server.url + "pop.woodshed/index.html", problems)
    step = page.get_by_test_id("step-4")
    expect(step.locator(".t")).to_have_text("Play with the band")
    page.get_by_test_id("lang-fr").click()
    expect(step.locator(".t")).to_have_text("Jouer avec le groupe")
    assert problems == []
