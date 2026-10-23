"""Taking the lead hands the band over (spec 023): a follower that taps Lead leads, the music goes on.

Three devices on the `band` library of test_band.py: a laptop that leads and two phones that follow.
"""

from __future__ import annotations

import itertools
import json
import time
from typing import Any

import pytest
from playwright.sync_api import Browser, Page, expect

from tests.page.test_band import library, server, until  # noqa: F401  (fixtures)
from woodshed import app

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


def band(browser: Browser, server: app.AppServer, problems: list[str], play: bool = True) -> tuple[Page, Page, Page]:  # noqa: F811
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
    laptop.wait_for_timeout(1000)  # a heartbeat or two
    return laptop, a, b


def one_leader(server: app.AppServer, devices: list[Page]) -> Page:  # noqa: F811
    """R5: exactly one device leads, the one the library names; every other one follows."""
    leader = server.live.state["leader"]
    modes = {p.evaluate("Woodshed.band.id()"): p.evaluate("Woodshed.band.mode()") for p in devices}
    assert leader in modes and modes[leader] == "lead", (leader, modes)
    assert sorted(modes.values()) == ["follow"] * (len(devices) - 1) + ["lead"], modes
    return next(p for p in devices if p.evaluate("Woodshed.band.id()") == leader)


def band_time(server: app.AppServer) -> float:  # noqa: F811
    s = server.live.state
    return float(s["time"] + (time.time() - s["at"]) * s["rate"]) if s["playing"] else float(s["time"])


def toasts(page: Page) -> list[str]:
    return list(page.evaluate("window.__toasts"))


def never_stopped(page: Page, jumps: bool = True) -> None:
    """A follower's banner never said "stopped" and (`jumps`) its position never jumped more than 0.5 s."""
    seen = page.evaluate("clearInterval(window.__sampler), window.__seen")
    assert len(seen) > 10
    assert [s["banner"] for s in seen if "stopped" in s["banner"]] == []
    if not jumps:
        return
    moved = [
        round(b["time"] - a["time"] - (b["at"] - a["at"]) / 1000, 2)
        for a, b in itertools.pairwise(seen)
        if abs(b["time"] - a["time"] - (b["at"] - a["at"]) / 1000) > 0.5
    ]
    assert moved == []


def take_lead(browser: Browser, server: app.AppServer, hold: int) -> None:  # noqa: F811
    problems: list[str] = []
    laptop, a, b = band(browser, server, problems)
    b.evaluate(f"window.__hold = {hold}")
    a.evaluate(SAMPLE)
    b.get_by_test_id("band-lead").tap()
    b.wait_for_timeout(1500)
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
def test_a_follower_takes_the_lead_and_the_music_goes_on(browser: Browser, server: app.AppServer) -> None:  # noqa: F811
    """AT1: the claim held 80 ms, as on a phone over Wi-Fi: on 0.5.0 nobody led and the band stopped."""
    take_lead(browser, server, hold=80)


def test_the_lead_goes_round_the_band_five_times_and_never_stops(browser: Browser, server: app.AppServer) -> None:  # noqa: F811
    """AT2: without any hold, each device in turn takes the lead from the one that leads."""
    problems: list[str] = []
    laptop, a, b = band(browser, server, problems)
    devices = [laptop, a, b]
    for turn, taker in enumerate([b, a, laptop, b, a]):
        leading = next(p for p in devices if p.evaluate("Woodshed.band.mode()") == "lead")
        leading.evaluate("Woodshed.app.seekBar(4)")  # the song is 16 s long: each turn from bar 5
        leading.wait_for_timeout(600)
        followers = [p for p in devices if p is not taker and p.evaluate("Woodshed.band.mode()") == "follow"]
        for p in followers:
            p.evaluate(SAMPLE)
        button = taker.get_by_test_id("band-lead")
        button.tap() if taker is not laptop else button.click()
        taker.wait_for_timeout(1500)
        assert one_leader(server, devices) == taker, turn
        assert server.live.state["playing"] is True and taker.evaluate("Woodshed.app.transport.playing") is True, turn
        for p in followers:
            never_stopped(p)
    assert problems == []


def test_an_old_heartbeat_during_the_claim_does_not_take_the_lead_back(browser: Browser, server: app.AppServer) -> None:  # noqa: F811
    """AT3: the claim takes 1.2 s; the laptop keeps the band and its heartbeats land meanwhile."""
    problems: list[str] = []
    laptop, a, b = band(browser, server, problems)
    b.evaluate("window.__hold = 1200")
    a.evaluate(SAMPLE)
    b.get_by_test_id("band-lead").tap()
    b.wait_for_timeout(400)
    lead = b.get_by_test_id("band-lead")  # the claim waits: said, and the button cannot be pressed again
    expect(lead).to_have_attribute("aria-busy", "true")
    expect(lead).to_have_attribute("aria-disabled", "true")
    expect(lead).to_have_attribute("title", "Taking the lead…")
    expect(b.get_by_test_id("band-banner")).to_contain_text("Taking the lead…")
    assert server.live.state["leader"] == laptop.evaluate("Woodshed.band.id()")  # the old leader keeps the band
    b.wait_for_timeout(2000)
    assert one_leader(server, [laptop, a, b]) == b
    expect(lead).not_to_have_attribute("aria-busy", "true")
    assert server.live.state["playing"] is True and b.evaluate("Woodshed.app.transport.playing") is True
    never_stopped(a, jumps=False)  # held before it leaves, the claim's place is 1.2 s old when it lands
    assert problems == []


def test_an_event_older_than_the_claim_is_not_acted_on(browser: Browser, server: app.AppServer) -> None:  # noqa: F811
    """The stream can deliver the old leader's last word after the claim's answer: it is older, ignored."""
    problems: list[str] = []
    laptop, a, b = band(browser, server, problems)
    before = b.evaluate("Woodshed.band.state()")
    b.get_by_test_id("band-lead").tap()
    until(b, "Woodshed.band.mode() === 'lead'")
    b.evaluate("(s) => Woodshed.band.hear({ ...s, now: Date.now() / 1000, at: Date.now() / 1000 })", before)
    b.wait_for_timeout(300)
    assert b.evaluate("Woodshed.band.mode()") == "lead"
    assert one_leader(server, [laptop, a, b]) == b
    assert problems == []


def test_two_taps_at_once_the_first_claim_wins(browser: Browser, server: app.AppServer) -> None:  # noqa: F811
    """AT4: A and B tap Lead together over the laptop; one leads, the other is told and follows."""
    problems: list[str] = []
    laptop, a, b = band(browser, server, problems)
    for p in (a, b):
        p.evaluate("window.__hold = 1000")  # both claims land after both taps
    a.get_by_test_id("band-lead").tap()
    b.get_by_test_id("band-lead").tap()
    b.wait_for_timeout(1500)
    winner = one_leader(server, [laptop, a, b])
    assert winner in (a, b)
    loser = b if winner is a else a
    assert any("Another device took the lead first: you follow it." in t for t in toasts(loser))
    assert not any("took the lead first" in t for t in toasts(winner))
    assert loser.evaluate("Woodshed.app.transport.playing") is False
    assert server.live.state["playing"] is True and winner.evaluate("Woodshed.app.transport.playing") is True
    until(loser, "Woodshed.debug().playing === true")  # it follows the band, playing
    assert problems == []


def test_a_slower_phone_tapping_at_the_same_moment_follows_the_first(browser: Browser, server: app.AppServer) -> None:  # noqa: F811
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
    b.wait_for_timeout(2500)
    assert one_leader(server, [laptop, a, b]) == a
    assert any("Another device took the lead first: you follow it." in t for t in toasts(b))
    assert b.evaluate("Woodshed.app.transport.playing") is False
    assert problems == []


def test_taking_the_lead_of_a_stopped_band_keeps_its_place(browser: Browser, server: app.AppServer) -> None:  # noqa: F811
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


def test_a_blocked_sound_still_leads_stopped_and_says_so(browser: Browser, server: app.AppServer) -> None:  # noqa: F811
    """AT7: the browser refuses to start the audio: the device leads, stopped at the band's place."""
    problems: list[str] = []
    laptop, a, b = band(browser, server, problems)
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


@pytest.mark.parametrize("answer", ["refused", "none"])
def test_a_claim_that_fails_leaves_the_follower_following(browser: Browser, server: app.AppServer, answer: str) -> None:  # noqa: F811
    """AT8: the app says no, or nothing: the device still follows (not alone), silent."""
    problems: list[str] = []
    laptop, a, b = band(browser, server, problems)

    def refuse(route: Any) -> None:
        if json.loads(route.request.post_data or "{}").get("lead") is not True:
            route.continue_()
        elif answer == "refused":
            route.fulfill(
                status=409, content_type="application/json", body='{"error": "another device leads the band"}'
            )
        else:
            route.abort()

    b.route("**/api/live", refuse)
    b.get_by_test_id("band-lead").tap()
    why = "another device leads the band" if answer == "refused" else "the app did not answer"
    until(
        b, "(w) => window.__toasts.some((t) => t.includes(w))", arg=f"Could not lead the band: {why}. You still follow."
    )
    assert b.evaluate("Woodshed.band.mode()") == "follow"
    assert b.evaluate("Woodshed.app.transport.playing") is False
    assert one_leader(server, [laptop, a, b]) == laptop
    until(b, "Woodshed.debug().playing === true")  # still with the band
    problems[:] = [
        p for p in problems if "Failed to fetch" not in p and "NetworkError" not in p and "ERR_FAILED" not in p
    ]
    assert problems == []


def test_a_tap_on_follow_while_the_sound_starts_cancels_the_claim(browser: Browser, server: app.AppServer) -> None:  # noqa: F811
    problems: list[str] = []
    laptop, a, b = band(browser, server, problems)
    b.evaluate(
        "(Woodshed.app.transport.play = () => new Promise(() => {}), true)"
    )  # a function result is called  # the file is slow to come
    b.get_by_test_id("band-lead").tap()
    b.wait_for_timeout(300)
    b.get_by_test_id("band-follow").tap()
    b.wait_for_timeout(3500)
    assert [x for x in b.evaluate("window.__live") if x["body"].get("lead")] == []  # never sent
    assert one_leader(server, [laptop, a, b]) == laptop
    until(b, "Woodshed.debug().playing === true")
    assert problems == []


@pytest.mark.parametrize("playing", [True, False])
def test_a_leader_whose_app_restarted_leads_again(browser: Browser, server: app.AppServer, playing: bool) -> None:  # noqa: F811
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


def test_a_follower_leads_a_band_its_leader_left(browser: Browser, server: app.AppServer) -> None:  # noqa: F811
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
