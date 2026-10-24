"""Taking the lead hands the band over (spec 023): a follower that taps Lead leads, the music goes on.

Three devices on the `band` library of test_band.py: a laptop that leads and two phones that follow.
"""

from __future__ import annotations

import itertools
import json
import shutil
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Browser, Page, expect

from tests.page import test_band
from woodshed import app
from woodshed.run import MANIFEST, Options

library, server, until = test_band.library, test_band.server, test_band.until  # the band's fixtures

# Every request to /api/live is logged; a claim (lead: true) can be held before it leaves, or refused.
# Every toast is logged too: one replaces the other on screen.
HOOKS = """
(() => {
  window.__live = [];
  window.__hold = 0;
  window.__toasts = [];
  const f = window.fetch;
  window.fetch = async function (u, o) {
    const body = o && typeof o.body === 'string' ? JSON.parse(o.body) : null;
    if (String(u).includes('/api/live') && body && body.lead === true && window.__hold > 0) {
      await new Promise((r) => setTimeout(r, window.__hold));
    }
    const r = await f.apply(this, arguments);
    if (String(u).includes('/api/live') && body) window.__live.push({ body, status: r.status });
    return r;
  };
  document.addEventListener('DOMContentLoaded', () => {
    const t = document.getElementById('toast');
    if (t) new MutationObserver(() => t.textContent && window.__toasts.push(t.textContent))
      .observe(t, { childList: true, subtree: true, characterData: true });
  });
})();
"""

# What a follower shows, every 50 ms: its banner and its position.
SAMPLE = """
(() => {
  window.__seen = [];
  window.__sampler = setInterval(() => {
    const b = document.querySelector('[data-testid=band-banner]');
    window.__seen.push({ at: performance.now(), banner: b ? b.innerText : '', time: Woodshed.debug().time });
  }, 50);
})()
"""


# The protocol's own cases (states, answers, cancels) run in Chromium only: the browser's part (sound, taps,
# timing) is covered in both browsers by the takeover tests. The page job's time budget is the reason.
CHROMIUM_ONLY = pytest.mark.only_browser("chromium")


def device(browser: Browser, url: str, problems: list[str], touch: bool) -> Page:
    """A laptop (1280x800) or a phone (390x844, touch)."""
    size: Any = {"width": 390, "height": 844} if touch else {"width": 1280, "height": 800}
    page = browser.new_context(viewport=size, has_touch=touch, locale="en-US").new_page()

    # Firefox's automation layer warns about its own layout calls (chrome://juggler): not the page. A 409
    # is the library's answer to a device that does not lead (a refused claim, an old leader's word).
    def said(m: Any) -> None:
        if m.type in ("error", "warning") and "juggler" not in m.text and "409" not in m.text:
            problems.append(m.text)

    page.on("console", said)
    page.on("pageerror", lambda e: problems.append(str(e)))
    page.add_init_script(HOOKS)
    page.goto(url)
    until(page, "window.Woodshed && window.Woodshed.ready === true")
    expect(page.get_by_test_id("band")).to_be_visible()
    return page


def band(browser: Browser, server: app.AppServer, problems: list[str], play: bool = True) -> tuple[Page, Page, Page]:
    """The laptop leads (playing from bar 5, or stopped there), phones A and B follow."""
    url = server.url + "pop.woodshed/index.html"
    laptop = device(browser, url, problems, touch=False)
    a, b = device(browser, url, problems, touch=True), device(browser, url, problems, touch=True)
    laptop.get_by_test_id("band-lead").click()
    until(laptop, "Woodshed.band.mode() === 'lead'")
    for p in (a, b):
        p.get_by_test_id("band-follow").tap()
        until(p, "Woodshed.band.mode() === 'follow'")
    laptop.evaluate("Woodshed.app.seekBar(4)")
    if play:
        laptop.get_by_test_id("play").click()
        until(laptop, "Woodshed.app.transport.playing === true")
        for p in (a, b):
            until(p, "Woodshed.debug().playing === true")
    return laptop, a, b


def one_leader(server: app.AppServer, devices: list[Page]) -> Page:
    """R5: exactly one device leads, the one the library names; every other one follows."""
    leader = server.live.state["leader"]
    modes = {p.evaluate("Woodshed.band.id()"): p.evaluate("Woodshed.band.mode()") for p in devices}
    assert leader in modes and modes[leader] == "lead", (leader, modes)
    assert sorted(modes.values()) == ["follow"] * (len(devices) - 1) + ["lead"], modes
    return next(p for p in devices if p.evaluate("Woodshed.band.id()") == leader)


def band_time(server: app.AppServer) -> float:
    s = server.live.state
    return float(s["time"] + (time.time() - s["at"]) * s["rate"]) if s["playing"] else float(s["time"])


def toasts(page: Page) -> list[str]:
    return list(page.evaluate("window.__toasts"))


def never_stopped(page: Page, jumps: bool = True) -> None:
    """A follower's banner never said "stopped" and (`jumps`) its position never jumped more than 0.5 s."""
    seen = page.evaluate("clearInterval(window.__sampler), window.__seen")
    assert len(seen) > 5  # sampled across the handover
    assert [s["banner"] for s in seen if "stopped" in s["banner"]] == []
    if not jumps:
        return
    moved = [
        round(b["time"] - a["time"] - (b["at"] - a["at"]) / 1000, 2)
        for a, b in itertools.pairwise(seen)
        if abs(b["time"] - a["time"] - (b["at"] - a["at"]) / 1000) > 0.5
    ]
    assert moved == []


def take_lead(browser: Browser, server: app.AppServer, hold: int) -> None:
    problems: list[str] = []
    laptop, a, b = band(browser, server, problems)
    b.evaluate(f"window.__hold = {hold}")
    a.evaluate(SAMPLE)
    b.get_by_test_id("band-lead").tap()
    until(b, "Woodshed.band.mode() === 'lead' && window.__toasts.some((t) => t.includes('the sound plays here now'))")
    until(laptop, "Woodshed.band.mode() === 'follow'")
    b.wait_for_timeout(300)  # the followers' samples go on past the handover
    assert one_leader(server, [laptop, a, b]) == b
    assert server.live.state["playing"] is True
    assert b.evaluate("Woodshed.app.transport.playing") is True
    assert abs(b.evaluate("Woodshed.app.transport.time") - band_time(server)) < 0.5
    assert laptop.evaluate("Woodshed.app.transport.playing") is False  # the sound moved with the lead
    never_stopped(a)
    assert not any("Another device leads" in t for t in toasts(b))
    assert any("Another device leads the band now" in t for t in toasts(laptop))
    assert any("the sound plays here now" in t for t in toasts(b))
    posts = b.evaluate("window.__live")
    assert {x["status"] for x in posts} == {200}  # nothing refused
    claim = posts[0]["body"]  # the claim first: no update of a device that does not lead yet
    assert claim.get("lead") is True and claim["playing"] is True
    assert claim["over"] == laptop.evaluate("Woodshed.band.id()")
    assert problems == []


@pytest.mark.tablet
def test_a_follower_takes_the_lead_and_the_music_goes_on(browser: Browser, server: app.AppServer) -> None:
    """AT1: the claim held 80 ms, as on a phone over Wi-Fi: on 0.5.0 nobody led and the band stopped."""
    take_lead(browser, server, hold=80)


def test_the_lead_goes_round_the_band_five_times_and_never_stops(browser: Browser, server: app.AppServer) -> None:
    """AT2: without any hold, each device in turn takes the lead from the one that leads."""
    problems: list[str] = []
    laptop, a, b = band(browser, server, problems)
    devices = [laptop, a, b]
    for turn, taker in enumerate([b, a, laptop, b, a]):
        leading = next(p for p in devices if p.evaluate("Woodshed.band.mode()") == "lead")
        leading.evaluate("Woodshed.app.seekBar(4)")  # the song is 16 s long: each turn from bar 5
        leading.wait_for_timeout(300)
        followers = [p for p in devices if p is not taker and p.evaluate("Woodshed.band.mode()") == "follow"]
        for p in followers:
            p.evaluate(SAMPLE)
        button = taker.get_by_test_id("band-lead")
        button.tap() if taker is not laptop else button.click()
        until(taker, "Woodshed.band.mode() === 'lead' && Woodshed.band.claiming() === false")
        for p in devices:
            if p is not taker:
                until(p, "Woodshed.band.mode() !== 'lead'")
        taker.wait_for_timeout(300)
        assert one_leader(server, devices) == taker, turn
        assert server.live.state["playing"] is True and taker.evaluate("Woodshed.app.transport.playing") is True, turn
        for p in followers:
            never_stopped(p)
    assert problems == []


def test_an_old_heartbeat_during_the_claim_does_not_take_the_lead_back(browser: Browser, server: app.AppServer) -> None:
    """AT3: the claim takes 1.2 s; the laptop keeps the band and its heartbeats land meanwhile."""
    problems: list[str] = []
    laptop, a, b = band(browser, server, problems)
    b.evaluate("window.__hold = 1200")
    a.evaluate(SAMPLE)
    b.get_by_test_id("band-lead").tap()
    lead = b.get_by_test_id("band-lead")  # the claim waits: said, and the button cannot be pressed again
    expect(lead).to_have_attribute("aria-busy", "true")
    expect(lead).to_have_attribute("aria-disabled", "true")
    expect(lead).to_have_attribute("title", "Taking the lead…")
    expect(b.get_by_test_id("band-banner")).to_contain_text("Taking the lead…")
    assert server.live.state["leader"] == laptop.evaluate("Woodshed.band.id()")  # the old leader keeps the band
    until(b, "Woodshed.band.mode() === 'lead'")
    until(laptop, "Woodshed.band.mode() === 'follow'")
    assert one_leader(server, [laptop, a, b]) == b
    expect(lead).not_to_have_attribute("aria-busy", "true")
    assert server.live.state["playing"] is True and b.evaluate("Woodshed.app.transport.playing") is True
    never_stopped(a)  # the claim says when its place was true, in the library's clock
    assert problems == []


@CHROMIUM_ONLY
def test_an_event_older_than_the_claim_is_not_acted_on(browser: Browser, server: app.AppServer) -> None:
    """The stream can deliver the old leader's last word after the claim's answer: it is older, ignored."""
    problems: list[str] = []
    laptop, a, b = band(browser, server, problems)
    before = b.evaluate("Woodshed.band.state()")
    b.get_by_test_id("band-lead").tap()
    until(b, "Woodshed.band.mode() === 'lead'")
    b.evaluate("(s) => Woodshed.band.hear({ ...s, now: Date.now() / 1000, at: Date.now() / 1000 })", before)
    b.wait_for_timeout(100)
    assert b.evaluate("Woodshed.band.mode()") == "lead"
    assert one_leader(server, [laptop, a, b]) == b
    assert problems == []


def test_two_taps_at_once_the_first_claim_wins(browser: Browser, server: app.AppServer) -> None:
    """AT4: A and B tap Lead together over the laptop; one leads, the other is told and follows."""
    problems: list[str] = []
    laptop, a, b = band(browser, server, problems)
    for p in (a, b):
        p.evaluate("window.__hold = 1000")  # both claims land after both taps
    a.get_by_test_id("band-lead").tap()
    b.get_by_test_id("band-lead").tap()
    for p in (a, b):
        until(p, "Woodshed.band.claiming() === false")
    until(laptop, "Woodshed.band.mode() === 'follow'")
    winner = one_leader(server, [laptop, a, b])
    assert winner in (a, b)
    loser = b if winner is a else a
    assert any("Another device took the lead first: you follow it." in t for t in toasts(loser))
    assert not any("took the lead first" in t for t in toasts(winner))
    assert loser.evaluate("Woodshed.app.transport.playing") is False
    assert server.live.state["playing"] is True and winner.evaluate("Woodshed.app.transport.playing") is True
    until(loser, "Woodshed.debug().playing === true")  # it follows the band, playing
    assert problems == []


def test_a_slower_phone_tapping_at_the_same_moment_follows_the_first(browser: Browser, server: app.AppServer) -> None:
    """AT4 again: both tap over the laptop; B's sound is slow to start, so A's lead reaches B before B
    claims. B claims over the leader it heard when it tapped (the laptop), not over A: refused, it follows A."""
    problems: list[str] = []
    laptop, a, b = band(browser, server, problems)
    slow = "const t = Woodshed.app.transport, play = t.play;"
    slow += " t.play = () => { const r = play(); return new Promise((ok) => setTimeout(() => ok(r), 2000)); }; true"
    b.evaluate(slow)  # a function result is called: the expression ends with true
    a.evaluate("window.__hold = 1000")  # A's claim lands after B's tap, before B's claim leaves
    a.get_by_test_id("band-lead").tap()
    b.get_by_test_id("band-lead").tap()
    until(a, "Woodshed.band.mode() === 'lead'")  # A leads while B's sound is still coming
    until(b, "Woodshed.band.claiming() === false")
    assert one_leader(server, [laptop, a, b]) == a
    assert any("Another device took the lead first: you follow it." in t for t in toasts(b))
    assert b.evaluate("Woodshed.app.transport.playing") is False
    assert problems == []


def test_taking_the_lead_of_a_stopped_band_keeps_its_place(browser: Browser, server: app.AppServer) -> None:
    """AT5: stopped at bar 5, the band stays stopped at bar 5 under its new leader."""
    problems: list[str] = []
    laptop, a, b = band(browser, server, problems, play=False)
    start = laptop.evaluate("Woodshed.current.bars[4].start")
    until(b, "(t) => Math.abs(Woodshed.debug().time - t) < 0.05", arg=start)
    b.get_by_test_id("band-lead").tap()
    until(b, "Woodshed.band.mode() === 'lead'")
    b.wait_for_timeout(500)
    assert one_leader(server, [laptop, a, b]) == b
    assert server.live.state["playing"] is False and abs(server.live.state["time"] - start) < 0.05
    assert b.evaluate("Woodshed.app.transport.playing") is False
    for p in (laptop, a):
        expect(p.get_by_test_id("band-banner")).to_contain_text("stopped")
        assert abs(p.evaluate("Woodshed.debug().time") - start) < 0.05
    assert problems == []


def test_a_blocked_sound_still_leads_stopped_and_says_so(browser: Browser, server: app.AppServer) -> None:
    """AT7: the browser refuses to start the audio: the device leads, stopped at the band's place."""
    problems: list[str] = []
    laptop, a, b = band(browser, server, problems)
    start = laptop.evaluate("Woodshed.current.bars[4].start")
    until(laptop, "(t) => Woodshed.app.transport.time > t + 1.2", arg=start)  # the band moved on from bar 5
    b.evaluate("(Woodshed.app.transport.play = async () => false, true)")
    b.get_by_test_id("band-lead").tap()
    until(b, "Woodshed.band.mode() === 'lead'")
    b.wait_for_timeout(300)
    assert one_leader(server, [laptop, a, b]) == b
    assert server.live.state["playing"] is False and b.evaluate("Woodshed.app.transport.playing") is False
    taken = server.live.state["time"]
    assert abs(b.evaluate("Woodshed.app.transport.time") - taken) < 0.05
    assert taken > laptop.evaluate("Woodshed.current.bars[4].start") + 0.8  # where the band was, not back
    expected = "This device leads the band, stopped: the browser blocked the sound, press play."
    assert any(expected in t for t in toasts(b))
    assert problems == []


OTHER = "other-device-22"  # a device the library hears that is not one of the pages here


def claim_over(server: app.AppServer, over: str, who: str = OTHER, playing: bool = True) -> None:
    """Another device takes the lead through the library, as a phone not under test would."""
    state = {"id": who, "song": "pop.woodshed", "playing": playing, "time": 9.0, "rate": 1.0, "loop": None}
    server.live.update({**state, "lead": True, "over": over}, server.library.root)


def is_claim(route: Any) -> bool:
    return json.loads(route.request.post_data or "{}").get("lead") is True


def test_a_claim_refused_because_another_came_first_leaves_the_follower_following(
    browser: Browser,
    server: app.AppServer,
) -> None:
    """AT8, refused: while B's claim is on its way, another device takes the lead; B is told and follows it."""
    problems: list[str] = []
    laptop, _a, b = band(browser, server, problems)
    b.evaluate("window.__hold = 1000")
    b.get_by_test_id("band-lead").tap()
    until(b, "Woodshed.app.transport.playing === true")  # the sound started; the claim waits
    claim_over(server, laptop.evaluate("Woodshed.band.id()"))
    until(b, "window.__toasts.some((t) => t.includes('Another device took the lead first: you follow it.'))")
    assert b.evaluate("Woodshed.band.mode()") == "follow" and server.live.state["leader"] == OTHER
    until(b, "Woodshed.app.transport.playing === false && Woodshed.band.state().leader === 'other-device-22'")
    assert problems == []


def test_a_claim_with_no_answer_leaves_the_follower_following(browser: Browser, server: app.AppServer) -> None:
    """AT8, no answer: the device still follows (not alone), silent."""
    problems: list[str] = []
    laptop, a, b = band(browser, server, problems)
    b.route("**/api/live", lambda route: route.abort() if is_claim(route) else route.continue_())
    b.get_by_test_id("band-lead").tap()
    until(
        b,
        "window.__toasts.some((t) => t.includes('Could not lead the band: the app did not answer. You still follow.'))",
    )
    assert b.evaluate("Woodshed.band.mode()") == "follow"
    assert b.evaluate("Woodshed.app.transport.playing") is False
    assert one_leader(server, [laptop, a, b]) == laptop
    until(b, "Woodshed.debug().playing === true")  # still with the band
    problems[:] = [p for p in problems if not any(x in p for x in ("Failed to fetch", "NetworkError", "ERR_FAILED"))]
    assert problems == []


def test_a_claim_whose_answer_was_lost_still_leads(browser: Browser, server: app.AppServer) -> None:
    """The library took the claim, the answer never came back (Wi-Fi dropped it): the stream says this
    device leads, so it leads, with its sound. Nobody leading is never the end state."""
    problems: list[str] = []
    laptop, a, b = band(browser, server, problems)

    def lose_the_answer(route: Any) -> None:
        if not is_claim(route):
            route.continue_()
            return
        route.fetch()  # the library handles it
        route.abort()  # its answer is lost on the way back

    b.route("**/api/live", lose_the_answer)
    b.get_by_test_id("band-lead").tap()
    until(b, "Woodshed.band.mode() === 'lead'")
    assert one_leader(server, [laptop, a, b]) == b
    until(b, "Woodshed.app.transport.playing === true")
    assert server.live.state["playing"] is True
    problems[:] = [p for p in problems if not any(x in p for x in ("Failed to fetch", "NetworkError", "ERR_FAILED"))]
    assert problems == []


@CHROMIUM_ONLY
def test_a_claim_that_hangs_gives_up(browser: Browser, server: app.AppServer) -> None:
    """No answer at all, not even an error: after about 4 s the device gives up and still follows."""
    problems: list[str] = []
    laptop, a, b = band(browser, server, problems)
    held: list[Any] = []
    b.route("**/api/live", lambda route: held.append(route) if is_claim(route) else route.continue_())
    b.get_by_test_id("band-lead").tap()
    until(b, "Woodshed.band.claiming() === true")
    until(b, "Woodshed.band.claiming() === false", timeout=8)
    assert b.evaluate("Woodshed.band.mode()") == "follow"
    until(
        b,
        "window.__toasts.some((t) => t.includes('Could not lead the band: the app did not answer. You still follow.'))",
    )
    assert one_leader(server, [laptop, a, b]) == laptop
    assert held  # the request never got an answer
    problems[:] = [
        p for p in problems if not any(x in p for x in ("Failed to fetch", "NetworkError", "ERR_FAILED", "abort"))
    ]
    assert problems == []


@CHROMIUM_ONLY
@pytest.mark.parametrize("choice", ["follow", "alone"])
def test_alone_or_follow_while_the_claim_waits_acts_at_once(
    browser: Browser, server: app.AppServer, choice: str
) -> None:
    problems: list[str] = []
    laptop, _a, b = band(browser, server, problems)
    b.route("**/api/live", lambda route: None if is_claim(route) else route.continue_())  # never answered
    b.get_by_test_id("band-lead").tap()
    until(b, "Woodshed.band.claiming() === true")
    b.get_by_test_id("band-" + choice).tap()
    assert b.evaluate("[Woodshed.band.claiming(), Woodshed.band.mode()]") == [False, choice]
    assert b.evaluate("Woodshed.app.transport.playing") is False
    expect(b.get_by_test_id("band-lead")).not_to_have_attribute("aria-busy", "true")
    assert server.live.state["leader"] == laptop.evaluate("Woodshed.band.id()")
    assert problems == []


@CHROMIUM_ONLY
def test_a_tap_on_follow_while_the_sound_starts_cancels_the_claim(browser: Browser, server: app.AppServer) -> None:
    problems: list[str] = []
    laptop, a, b = band(browser, server, problems)
    b.evaluate("(Woodshed.app.transport.play = () => new Promise(() => {}), true)")  # the file is slow to come
    b.get_by_test_id("band-lead").tap()
    until(b, "Woodshed.band.claiming() === true")
    b.get_by_test_id("band-follow").tap()
    assert b.evaluate("Woodshed.band.claiming()") is False  # at once
    b.wait_for_timeout(3500)  # past the sound's wait: the cancelled claim must not leave then
    assert [x for x in b.evaluate("window.__live") if x["body"].get("lead")] == []  # never sent
    assert one_leader(server, [laptop, a, b]) == laptop
    until(b, "Woodshed.debug().playing === true")
    assert problems == []


@CHROMIUM_ONLY
def test_lead_again_after_a_cancel_leads(browser: Browser, server: app.AppServer) -> None:
    """A cancelled claim does not cancel the next one."""
    problems: list[str] = []
    laptop, a, b = band(browser, server, problems)
    b.evaluate("window.__hold = 600")
    b.get_by_test_id("band-lead").tap()
    until(b, "Woodshed.band.claiming() === true")
    b.get_by_test_id("band-follow").tap()
    b.evaluate("window.__hold = 0")
    b.get_by_test_id("band-lead").tap()
    until(b, "Woodshed.band.mode() === 'lead' && Woodshed.band.claiming() === false")
    b.wait_for_timeout(1000)  # the first claim's answer has come back by now
    assert one_leader(server, [laptop, a, b]) == b
    assert problems == []


@CHROMIUM_ONLY
def test_follow_after_the_claim_left_gives_the_lead_back(browser: Browser, server: app.AppServer) -> None:
    """Follow tapped while the claim is on its way: once the library took it, the device lets the lead go
    (the band waits for a leader) instead of leading against the musician's choice."""
    problems: list[str] = []
    laptop, a, b = band(browser, server, problems)
    b.evaluate("window.__hold = 800")
    b.get_by_test_id("band-lead").tap()
    until(b, "window.__live.length === 0 && Woodshed.band.claiming() === true && Woodshed.app.transport.playing")
    b.wait_for_timeout(100)  # the claim has been handed to fetch (held there)
    b.get_by_test_id("band-follow").tap()
    assert b.evaluate("Woodshed.band.mode()") == "follow"
    until(b, "window.__live.some((x) => x.body.release === true)")
    deadline = time.monotonic() + 5
    while server.live.state["leader"] is not None:
        assert time.monotonic() < deadline, server.live.state
        b.wait_for_timeout(100)
    assert [p.evaluate("Woodshed.band.mode()") for p in (laptop, a, b)] == ["follow"] * 3
    assert problems == []


@CHROMIUM_ONLY
def test_a_leader_that_chooses_follow_lets_the_lead_go(browser: Browser, server: app.AppServer) -> None:
    problems: list[str] = []
    laptop, _a, _b = band(browser, server, problems)
    laptop.get_by_test_id("band-follow").click()
    deadline = time.monotonic() + 5
    while server.live.state["leader"] is not None:
        assert time.monotonic() < deadline, server.live.state
        laptop.wait_for_timeout(100)
    assert problems == []


@CHROMIUM_ONLY
def test_a_claim_answered_after_another_took_the_lead_follows(browser: Browser, server: app.AppServer) -> None:
    """Stopped band: B's claim is taken, then another device takes the lead over B before B hears its own
    answer. B must follow: two devices leading a stopped band would never find out (no heartbeat)."""
    problems: list[str] = []
    _laptop, _a, b = band(browser, server, problems, play=False)
    answers: list[Any] = []

    def late(route: Any) -> None:
        if is_claim(route):
            answers.append((route, route.fetch()))  # handled by the library, answered later
        else:
            route.continue_()

    b.route("**/api/live", late)
    b.get_by_test_id("band-lead").tap()
    deadline = time.monotonic() + 5
    while not answers:
        assert time.monotonic() < deadline
        b.wait_for_timeout(50)
    me = b.evaluate("Woodshed.band.id()")
    assert server.live.state["leader"] == me
    claim_over(server, me, playing=False)
    until(b, "Woodshed.band.state().leader === 'other-device-22'")  # heard while claiming
    route, response = answers[0]
    route.fulfill(response=response)
    until(b, "Woodshed.band.claiming() === false")
    until(b, "Woodshed.band.mode() === 'follow'")
    assert server.live.state["leader"] == OTHER
    assert problems == []


@CHROMIUM_ONLY
def test_a_takeover_from_a_screen_that_stopped_hearing_is_refused(browser: Browser, server: app.AppServer) -> None:
    """B's stream died (an iPhone asleep): its screen still shows an old place. Its claim is refused, the
    band plays on under its leader, and B follows the band as it is now."""
    problems: list[str] = []
    laptop, a, b = band(browser, server, problems)
    b.evaluate("window.dispatchEvent(new Event('pagehide'))")  # the stream closes and stays closed
    laptop.wait_for_timeout(3500)  # the band plays on, unheard by B
    b.get_by_test_id("band-lead").tap()
    expected = "The band moved on since this screen last heard it: you follow it again."
    until(b, "(w) => window.__toasts.some((t) => t.includes(w))", arg=expected)
    assert one_leader(server, [laptop, a, b]) == laptop
    assert server.live.state["playing"] is True and laptop.evaluate("Woodshed.app.transport.playing") is True
    assert b.evaluate("Woodshed.app.transport.playing") is False
    assert problems == []


@CHROMIUM_ONLY
def test_a_leader_change_heard_while_claiming_waits_for_the_answer(browser: Browser, server: app.AppServer) -> None:
    """An event naming another leader (and another song) while the claim is on its way changes nothing:
    the claim's answer decides."""
    problems: list[str] = []
    laptop, a, b = band(browser, server, problems)
    b.evaluate("window.__hold = 600")
    b.get_by_test_id("band-lead").tap()
    until(b, "Woodshed.band.claiming() === true")
    b.evaluate(
        "(s) => Woodshed.band.hear({ ...s, leader: 'other-device-22', song: 'waltz.woodshed', v: s.v + 1,"
        " now: Date.now() / 1000, at: Date.now() / 1000 })",
        b.evaluate("Woodshed.band.state()"),
    )
    until(b, "Woodshed.band.mode() === 'lead'")
    assert "pop.woodshed" in b.url
    assert one_leader(server, [laptop, a, b]) == b
    assert problems == []


def test_a_play_cut_short_by_pause_says_nothing(browser: Browser, server: app.AppServer) -> None:
    """A pause while a play is starting is not a blocked sound: no "browser blocked playback" toast."""
    problems: list[str] = []
    page = device(browser, server.url + "pop.woodshed/index.html", problems, touch=False)
    page.get_by_test_id("play").click()  # the page has had a tap
    page.get_by_test_id("play").click()
    started = page.evaluate(
        "async () => { const t = Woodshed.app.transport; t.seek(7); const p = t.play(); t.pause(); return await p; }"
    )
    assert started in (True, False)  # Firefox may still resolve it, Chromium rejects it (AbortError)
    assert page.evaluate("Woodshed.app.transport.playing") is False
    page.wait_for_timeout(300)
    assert not any("blocked" in t for t in toasts(page))
    assert problems == []


@CHROMIUM_ONLY
def test_a_sound_that_does_not_start_in_time_leads_stopped_and_says_so(browser: Browser, server: app.AppServer) -> None:
    problems: list[str] = []
    laptop, a, b = band(browser, server, problems)
    b.evaluate("(Woodshed.app.transport.play = () => new Promise(() => {}), true)")  # the file never comes
    b.get_by_test_id("band-lead").tap()
    until(b, "Woodshed.band.mode() === 'lead'", timeout=8)
    assert one_leader(server, [laptop, a, b]) == b
    assert server.live.state["playing"] is False
    expected = "This device leads the band, stopped: the sound did not start in 3 s, press play."
    until(b, "(w) => window.__toasts.some((t) => t.includes(w))", arg=expected)
    assert problems == []


@pytest.mark.parametrize("playing", [True, False])
def test_a_leader_whose_app_restarted_leads_again(browser: Browser, server: app.AppServer, playing: bool) -> None:
    """The numbers start again at 0 with the app: the leader's own claim number does not hide the new run.
    Playing, its next heartbeat is refused and says nobody leads; stopped, only the stream says it."""
    problems: list[str] = []
    _laptop, _a, b = band(browser, server, problems)
    b.get_by_test_id("band-lead").tap()
    until(b, "Woodshed.band.mode() === 'lead'")
    if not playing:
        b.get_by_test_id("play").tap()
        until(b, "Woodshed.app.transport.playing === false")
    old = server.live
    server.live = app.Live()  # the library restarted: nobody leads, its states count from 0 again
    old.close()  # the streams end; the pages open them again
    until(b, "window.__toasts.some((t) => t.includes('The band had no leader'))", timeout=15)
    until(b, "Woodshed.band.mode() === 'lead'")
    deadline = time.monotonic() + 5
    while server.live.state["leader"] != b.evaluate("Woodshed.band.id()"):
        assert time.monotonic() < deadline
        b.wait_for_timeout(100)
    assert problems == []


@CHROMIUM_ONLY
def test_a_follower_leads_a_band_its_leader_left(browser: Browser, server: app.AppServer) -> None:
    """The leader chose Alone: nobody leads; a follower's tap on Lead leads (the place is not kept: spec 023 R8)."""
    problems: list[str] = []
    laptop, a, b = band(browser, server, problems, play=False)
    laptop.get_by_test_id("band-alone").click()
    expect(b.get_by_test_id("band-banner")).to_contain_text("Waiting for a leader")
    b.get_by_test_id("band-lead").tap()
    until(b, "Woodshed.band.mode() === 'lead'")
    until(a, "(id) => (Woodshed.band.state() || {}).leader === id", arg=b.evaluate("Woodshed.band.id()"))
    assert server.live.state["leader"] == b.evaluate("Woodshed.band.id()")
    assert laptop.evaluate("Woodshed.band.mode()") == "alone"
    assert problems == []


@pytest.fixture
def stems_server(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Iterator[app.AppServer]:
    """A library with one page that has its instruments' tracks (fake stems)."""
    from tests.page.conftest import built

    monkeypatch.setenv("WOODSHED_CACHE", str(tmp_path / "cache"))
    built_page = built("pop", True, str(tmp_path_factory.getbasetemp() / "stems-band"))
    page = tmp_path / "library" / "pop.woodshed"
    shutil.copytree(built_page, page)
    summary = {"title": "pop", "folder": page.name, "key": "C", "bpm": 120, "meter": "4/4", "duration": 16, "doubts": 0}
    (page / MANIFEST).write_text(json.dumps({"settings": {}, "summary": summary, "complete": False}))
    srv = app.AppServer(app.Library(page.parent, Options(use_stems=False, open_page=False)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()
    srv.server_close()


@CHROMIUM_ONLY
def test_the_new_leader_plays_the_full_mix_for_the_band(browser: Browser, stems_server: app.AppServer) -> None:
    """B practised on a track of its own while following: leading, the band hears the full mix from it."""
    problems: list[str] = []
    folder = next(stems_server.library.root.glob("*.woodshed")).name
    url = stems_server.url + folder + "/index.html"
    laptop = device(browser, url, problems, touch=False)
    b = device(browser, url, problems, touch=True)
    laptop.get_by_test_id("band-lead").click()
    until(laptop, "Woodshed.band.mode() === 'lead'")
    b.get_by_test_id("band-follow").tap()
    until(b, "Woodshed.band.mode() === 'follow'")
    own = b.evaluate("Woodshed.current.tracks.find((t) => t.id !== 'mix').id")
    b.evaluate("(id) => Woodshed.app.setTrack(id)", own)
    until(b, "(id) => Woodshed.app.transport.track === id", arg=own)
    laptop.evaluate("Woodshed.app.seekBar(2)")
    laptop.get_by_test_id("play").click()
    until(b, "Woodshed.debug().playing === true")
    b.get_by_test_id("band-lead").tap()
    until(b, "Woodshed.band.mode() === 'lead'")
    until(b, "Woodshed.app.transport.track === 'mix' && Woodshed.app.transport.playing === true")
    assert b.evaluate("Woodshed.app.store.get().track") == "mix"
    assert stems_server.live.state["leader"] == b.evaluate("Woodshed.band.id()")
    assert problems == []


@CHROMIUM_ONLY
def test_a_new_leader_in_another_key_than_the_band_is_told(browser: Browser, server: app.AppServer) -> None:
    """B's recording plays in its own key (a singer's): leading, the band would hear that key. Said."""
    problems: list[str] = []
    laptop, _a, b = band(browser, server, problems)
    b.evaluate(
        "(Woodshed.app.store.set({ transpose: 2 }), Woodshed.app.pitchFollows = () => true,"
        " Woodshed.app.pitchReady = () => true, true)"
    )
    b.get_by_test_id("band-lead").tap()
    until(b, "Woodshed.band.mode() === 'lead'")
    until(b, "window.__toasts.some((t) => t.includes('You lead: the band hears this device'))")
    assert server.live.state["leader"] == b.evaluate("Woodshed.band.id()")
    assert laptop.evaluate("Woodshed.band.mode()") == "follow"
    assert problems == []


@CHROMIUM_ONLY
def test_a_claim_that_reaches_the_library_after_the_device_gave_up_still_leads(
    browser: Browser,
    server: app.AppServer,
) -> None:
    """The claim got no answer and the device went back to following; then the claim reaches the library
    after all (a slow network). The stream names the device: it leads, nobody else is left to."""
    problems: list[str] = []
    laptop, a, b = band(browser, server, problems)
    bodies: list[str] = []

    def lost(route: Any) -> None:
        if is_claim(route):
            bodies.append(route.request.post_data or "")
            route.abort()
        else:
            route.continue_()

    b.route("**/api/live", lost)
    b.get_by_test_id("band-lead").tap()
    until(b, "Woodshed.band.claiming() === false && Woodshed.band.mode() === 'follow'")
    server.live.update(json.loads(bodies[0]), server.library.root)  # it arrives now
    until(b, "Woodshed.band.mode() === 'lead'")
    assert one_leader(server, [laptop, a, b]) == b
    problems[:] = [p for p in problems if not any(x in p for x in ("Failed to fetch", "NetworkError", "ERR_FAILED"))]
    assert problems == []


@CHROMIUM_ONLY
def test_a_device_named_leader_without_asking_lets_the_lead_go(browser: Browser, server: app.AppServer) -> None:
    """The library names a following device that did not claim (a release of its own lost on the way):
    it gives the lead back rather than leave the band led by a device that does not lead."""
    problems: list[str] = []
    laptop, _a, b = band(browser, server, problems, play=False)
    me = b.evaluate("Woodshed.band.id()")
    claim_over(server, laptop.evaluate("Woodshed.band.id()"), who=me, playing=False)
    deadline = time.monotonic() + 5
    while server.live.state["leader"] is not None:
        assert time.monotonic() < deadline, server.live.state
        b.wait_for_timeout(100)
    assert b.evaluate("Woodshed.band.mode()") == "follow"
    assert problems == []


@CHROMIUM_ONLY
def test_alone_after_a_lost_claim_lets_its_late_arrival_go(browser: Browser, server: app.AppServer) -> None:
    """The claim got no answer ("You still follow"), the musician then chooses Alone: when the claim reaches
    the library late after all, the device lets the lead go instead of taking it."""
    problems: list[str] = []
    laptop, _a, b = band(browser, server, problems)
    bodies: list[str] = []

    def lost(route: Any) -> None:
        if is_claim(route):
            bodies.append(route.request.post_data or "")
            route.abort()
        else:
            route.continue_()

    b.route("**/api/live", lost)
    b.get_by_test_id("band-lead").tap()
    until(b, "window.__toasts.some((t) => t.includes('You still follow'))")
    b.get_by_test_id("band-alone").tap()
    until(b, "Woodshed.band.mode() === 'alone'")
    server.live.update(json.loads(bodies[0]), server.library.root)  # it arrives now
    me = b.evaluate("Woodshed.band.id()")
    deadline = time.monotonic() + 5
    while server.live.state["leader"] == me:
        assert time.monotonic() < deadline, server.live.state
        b.wait_for_timeout(100)
    assert b.evaluate("Woodshed.band.mode()") == "alone"
    assert server.live.state["leader"] is None  # the late claim had taken it from the laptop: let go
    assert laptop.evaluate("Woodshed.band.mode()") == "follow"
    problems[:] = [p for p in problems if not any(x in p for x in ("Failed to fetch", "NetworkError", "ERR_FAILED"))]
    assert problems == []


@CHROMIUM_ONLY
def test_a_failed_claim_gives_the_follower_its_track_back(browser: Browser, stems_server: app.AppServer) -> None:
    """The switch to the full mix comes before the claim: refused, the follower is back on its own track."""
    problems: list[str] = []
    folder = next(stems_server.library.root.glob("*.woodshed")).name
    url = stems_server.url + folder + "/index.html"
    laptop = device(browser, url, problems, touch=False)
    b = device(browser, url, problems, touch=True)
    laptop.get_by_test_id("band-lead").click()
    until(laptop, "Woodshed.band.mode() === 'lead'")
    b.get_by_test_id("band-follow").tap()
    until(b, "Woodshed.band.mode() === 'follow'")
    own = b.evaluate("Woodshed.current.tracks.find((t) => t.id !== 'mix').id")
    b.evaluate("(id) => Woodshed.app.setTrack(id)", own)
    until(b, "(id) => Woodshed.app.transport.track === id", arg=own)
    b.route("**/api/live", lambda route: route.abort() if is_claim(route) else route.continue_())
    b.get_by_test_id("band-lead").tap()
    until(b, "window.__toasts.some((t) => t.includes('You still follow'))")
    until(b, "(id) => Woodshed.app.store.get().track === id && Woodshed.app.transport.track === id", arg=own)
    problems[:] = [p for p in problems if not any(x in p for x in ("Failed to fetch", "NetworkError", "ERR_FAILED"))]
    assert problems == []
