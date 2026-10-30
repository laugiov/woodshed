"""Skins in a real browser (spec 030): the decor slots a skin draws in, when they show and when they never do, and
what the page tells a skin (playing, stage, the names)."""

from __future__ import annotations

from typing import Any

import pytest
from playwright.sync_api import Browser, Page, expect

from tests.page.conftest import built

# A skin that draws every slot and turns every part of it: what the base does with any skin.
FIXTURE = """
:root[data-skin="t"] .decor { display: block; width: 40px; height: 40px; background: var(--accent); }
:root[data-skin="t"] .decor[data-slot="page"] { width: auto; height: auto; }
:root[data-skin="t"] .decor i { display: block; width: 10px; height: 10px; background: var(--warn); }
:root[data-skin="t"] .decor::before, :root[data-skin="t"] .decor::after {
  content: ""; display: block; width: 4px; height: 4px;
}
:root[data-skin="t"][data-playing] .decor, :root[data-skin="t"][data-playing] .decor i,
:root[data-skin="t"][data-playing] .decor::before, :root[data-skin="t"][data-playing] .decor::after,
:root[data-skin="t"][data-playing] .decor i::before { animation: t-turn 1s linear infinite; }
@keyframes t-turn { to { transform: rotate(1turn); } }
"""
SHOWN = """() => [...document.querySelectorAll('.decor')].filter(e => getComputedStyle(e).display !== 'none')
    .map(e => e.dataset.slot).sort()"""
ANIMATED = """() => [...document.querySelectorAll('.decor')].flatMap(e => [
    getComputedStyle(e).animationName, getComputedStyle(e, '::before').animationName,
    getComputedStyle(e, '::after').animationName, ...[...e.children].map(i => getComputedStyle(i).animationName)])
    .filter(n => n !== 'none').length"""


def song_page(browser: Browser, root: str, **context: Any) -> Page:
    page = browser.new_context(locale="en-US", **context).new_page()
    page.goto((built("pop", True, root) / "index.html").as_uri())
    page.wait_for_function("window.Woodshed && window.Woodshed.ready === true")
    return page


def skinned(page: Page) -> Page:
    page.add_style_tag(content=FIXTURE)
    page.evaluate("document.documentElement.setAttribute('data-skin', 't')")
    return page


def test_the_base_draws_no_decor(browser: Browser, pages_root: str) -> None:
    page = song_page(browser, pages_root)
    assert page.evaluate(SHOWN) == []
    assert page.evaluate("document.querySelectorAll('.decor[aria-hidden=\"true\"]').length") == 3


def test_a_skin_draws_its_slots_but_never_on_stage_on_paper_or_crowding_a_phone(
    browser: Browser, pages_root: str
) -> None:
    page = skinned(song_page(browser, pages_root, viewport={"width": 1280, "height": 800}))
    assert page.evaluate(SHOWN) == ["page", "player", "song-head"]
    page.get_by_test_id("stage-open").click()
    expect(page.locator("html")).to_have_attribute("data-stage", "")
    assert page.evaluate(SHOWN) == []
    page.keyboard.press("Escape")
    expect(page.locator("html")).not_to_have_attribute("data-stage", "")
    assert page.evaluate(SHOWN) == ["page", "player", "song-head"]
    page.emulate_media(media="print")
    assert page.evaluate(SHOWN) == []
    page.emulate_media(media="screen")
    page.set_viewport_size({"width": 500, "height": 800})
    assert page.evaluate(SHOWN) == ["page", "song-head"]  # the player's slot would crowd the dock


def test_the_decor_turns_only_while_the_song_plays_and_never_under_reduced_motion(
    browser: Browser, pages_root: str
) -> None:
    page = skinned(song_page(browser, pages_root))
    assert page.evaluate(ANIMATED) == 0
    page.evaluate("Woodshed.app.store.set({ playing: true })")
    expect(page.locator("html")).to_have_attribute("data-playing", "")
    assert page.evaluate(ANIMATED) > 0
    page.evaluate("Woodshed.app.store.set({ playing: false })")
    expect(page.locator("html")).not_to_have_attribute("data-playing", "")
    still = skinned(song_page(browser, pages_root, reduced_motion="reduce"))
    still.evaluate("Woodshed.app.store.set({ playing: true })")
    assert still.evaluate(ANIMATED) == 0


@pytest.mark.parametrize("count_in", [False, True])
def test_the_page_says_it_plays_from_the_first_click(browser: Browser, pages_root: str, count_in: bool) -> None:
    page = song_page(browser, pages_root)
    if count_in:
        page.evaluate("Woodshed.app.store.set({ countIn: true })")
    page.get_by_test_id("play").click()
    expect(page.locator("html")).to_have_attribute("data-playing", "")
    page.get_by_test_id("play").click()
    expect(page.locator("html")).not_to_have_attribute("data-playing", "")


def test_the_slots_carry_the_names_a_skin_may_print(browser: Browser, pages_root: str) -> None:
    page = song_page(browser, pages_root)
    player = page.locator('.decor[data-slot="player"]')
    expect(player).to_have_attribute("data-song-title", "pop")
    expect(player).not_to_have_attribute("data-set-title", "")  # a page from a folder: no set
    page.evaluate("Woodshed.app.store.set({ setName: 'Les Imprévus' })")
    expect(player).to_have_attribute("data-set-title", "Les Imprévus")
    page.evaluate("Woodshed.app.store.set({ setName: '' })")
    assert player.get_attribute("data-set-title") is None  # absent, not empty: a skin draws nothing
