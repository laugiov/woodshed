"""Skins in a real browser (spec 030): the decor slots a skin draws in, when they show and when they never do, and
what the page tells a skin (playing, stage, the names)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Browser, Page, expect

from tests.page.conftest import built, with_close_calls

NBSP = chr(0xA0)  # French typography: before ":"

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


# Choosing a skin (R17 to R20): per device, before the page is drawn, from a menu beside the theme button.


def pick(page: Page, name: str) -> None:
    page.get_by_test_id("style").click()
    page.get_by_role("menuitemradio", name=name).click()


def test_a_skin_is_chosen_kept_and_shown_before_the_next_page_is_drawn(browser: Browser, pages_root: str) -> None:
    problems: list[str] = []
    page = song_page(browser, pages_root)
    page.on("console", lambda m: problems.append(m.text) if m.type in ("error", "warning") else None)
    redraws = page.evaluate_handle(
        "() => { const n = { count: 0 }; addEventListener('woodshed:theme', () => n.count++); return n; }"
    )
    style = page.get_by_test_id("style")
    expect(style).to_have_attribute("aria-label", "Style: woodshed")
    pick(page, "Spotlight")
    expect(page.locator("html")).to_have_attribute("data-skin", "spotlight")
    assert redraws.evaluate("n => n.count") == 1  # the waveform draws itself in the skin's colours
    assert page.evaluate("getComputedStyle(document.body).backgroundColor") == "rgb(0, 0, 0)"  # dark by default
    expect(style).to_have_attribute("aria-label", "Style: Spotlight")
    page.add_init_script(
        "document.addEventListener('DOMContentLoaded',"
        " () => { window.skinAtLoad = document.documentElement.dataset.skin; });"
    )
    page.reload()
    assert page.evaluate("window.skinAtLoad") == "spotlight"  # set in <head>: no frame of the base
    pick(page, "woodshed")
    expect(page.locator("html")).not_to_have_attribute("data-skin", "spotlight")
    assert page.evaluate("document.documentElement.hasAttribute('data-skin')") is False
    assert problems == []


def test_a_skin_that_is_gone_gives_the_base(browser: Browser, pages_root: str) -> None:
    context = browser.new_context(locale="en-US")
    context.add_init_script("localStorage.setItem('woodshed:skin', 'gone-since')")
    page = context.new_page()
    page.goto((built("pop", True, pages_root) / "index.html").as_uri())
    page.wait_for_function("window.Woodshed && window.Woodshed.ready === true")
    assert page.evaluate("document.documentElement.hasAttribute('data-skin')") is False
    expect(page.get_by_test_id("style")).to_have_attribute("aria-label", "Style: woodshed")


def test_paper_never_sees_a_skin(browser: Browser, pages_root: str) -> None:
    page = song_page(browser, pages_root)
    pick(page, "Spotlight")  # black, in the dark theme
    page.emulate_media(media="print")
    assert page.evaluate("getComputedStyle(document.body).backgroundColor") == "rgb(255, 255, 255)"
    assert page.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--accent').trim()") == "#0c7a68"


def test_the_style_menu_by_keyboard_and_the_app_s_keys_wait(browser: Browser, pages_root: str) -> None:
    page = song_page(browser, pages_root)
    page.get_by_test_id("style").focus()
    page.keyboard.press("Enter")
    menu = page.get_by_role("menu", name="Style")
    expect(menu).to_be_visible()
    items = menu.get_by_role("menuitemradio")
    expect(items.first).to_be_focused()  # the current skin
    expect(items.first).to_have_attribute("aria-checked", "true")
    page.keyboard.press("ArrowDown")
    expect(items.nth(1)).to_be_focused()
    page.keyboard.press("ArrowUp")
    page.keyboard.press("ArrowUp")  # round to the last
    expect(items.last).to_be_focused()
    for key in ("s", "l", "n", "2"):  # stage, loop, next song, step 2: none while the menu is open
        page.keyboard.press(key)
    assert page.evaluate("Woodshed.app.store.get().stage") is False
    assert page.evaluate("Woodshed.app.store.get().loopOn") is False
    expect(menu).to_be_visible()
    page.keyboard.press("Escape")
    expect(menu).to_be_hidden()
    expect(page.get_by_test_id("style")).to_be_focused()  # the keyboard keeps its place
    page.keyboard.press("Enter")
    page.keyboard.press("ArrowDown")
    page.keyboard.press("Enter")
    expect(page.locator("html")).to_have_attribute("data-skin", "spotlight")
    expect(menu).to_be_hidden()


def test_a_pointer_pick_leaves_no_focus_behind(browser: Browser, pages_root: str) -> None:
    page = song_page(browser, pages_root)
    pick(page, "Spotlight")
    assert page.evaluate("document.activeElement === document.body")  # a pedal's Space plays the song
    page.get_by_test_id("style").click()
    page.mouse.click(5, 400)  # outside: closed, nothing chosen
    expect(page.get_by_role("menu")).to_be_hidden()
    expect(page.locator("html")).to_have_attribute("data-skin", "spotlight")


@pytest.mark.parametrize(("width", "height"), [(390, 844), (640, 360)])
def test_the_style_menu_on_a_phone(browser: Browser, pages_root: str, width: int, height: int) -> None:
    page = song_page(browser, pages_root, viewport={"width": width, "height": height}, has_touch=True, is_mobile=True)
    page.get_by_test_id("style").tap()
    menu = page.get_by_role("menu", name="Style")
    expect(menu).to_be_visible()
    for item in menu.get_by_role("menuitemradio").all():
        box = item.bounding_box()
        assert box is not None and box["height"] >= 44
    style = page.get_by_test_id("style").bounding_box()
    assert style is not None and style["width"] >= 44 and style["height"] >= 44
    assert menu.evaluate("m => m.scrollHeight <= m.clientHeight || getComputedStyle(m).overflowY === 'auto'")
    assert menu.evaluate("m => m.getBoundingClientRect().bottom <= innerHeight")
    if width <= 600:
        page.get_by_role("button", name="Close").tap()
        expect(menu).to_be_hidden()


def test_the_style_menu_in_french(browser: Browser, pages_root: str) -> None:
    page = song_page(browser, pages_root)
    page.get_by_test_id("lang-fr").click()
    expect(page.get_by_test_id("style")).to_have_attribute("aria-label", "Style" + NBSP + ": woodshed")
    page.get_by_test_id("style").click()
    expect(page.get_by_role("menuitemradio", name="Pleins feux")).to_be_visible()
    expect(page.get_by_role("menu")).to_contain_text("Seulement sur cet appareil.")


# What no skin changes (R11, R23), and a skin from a folder on disk (A14).

SKINS_SHIPPED = ["spotlight", "disco70", "mixtape80", "grunge90", "y2k"]
LOGO = """() => { const l = document.querySelector('[data-testid="logo"]');
  return [l.outerHTML, getComputedStyle(l).fontFamily, getComputedStyle(l).fontSize]; }"""
DOUBTS = """() => [...document.querySelectorAll('.doubt, .lline.check .wt')].map(e => { const s = getComputedStyle(e);
  return [e.textContent, s.textDecorationLine, s.textDecorationStyle]; })"""


def with_skin(browser: Browser, folder: Path, skin: str | None, **context: Any) -> Page:
    ctx = browser.new_context(locale="en-US", **context)
    if skin:
        ctx.add_init_script(f"localStorage.setItem('woodshed:skin', '{skin}')")
    page = ctx.new_page()
    page.goto((folder / "index.html").as_uri())
    page.wait_for_function("window.Woodshed && window.Woodshed.ready === true")
    page.evaluate("document.fonts.ready")
    return page


def test_the_logo_and_the_doubt_marks_are_the_same_in_every_skin(browser: Browser, pages_root: str) -> None:
    folder = with_close_calls("pickup", True, pages_root)
    base = with_skin(browser, folder, None)
    logo, doubts = base.evaluate(LOGO), base.evaluate(DOUBTS)
    assert doubts and all(line == "underline" and style == "dotted" for _, line, style in doubts)
    for skin in SKINS_SHIPPED:
        page = with_skin(browser, folder, skin)
        assert page.evaluate(LOGO) == logo, skin
        assert page.evaluate(DOUBTS) == doubts, skin  # said by their text and a dotted line, not by colour alone


def test_a_skin_from_a_folder_on_disk_loads_its_fonts_and_pictures(browser: Browser, pages_root: str) -> None:
    problems: list[str] = []
    page = with_skin(browser, built("pop", True, pages_root), "mixtape80", viewport={"width": 1280, "height": 800})
    page.on("console", lambda m: problems.append(m.text) if m.type in ("error", "warning") else None)
    assert page.url.startswith("file://")
    assert page.evaluate("document.fonts.check('20px Audiowide') && document.fonts.check('20px VT323')")
    assert page.evaluate("[...document.fonts].filter(f => f.status === 'loaded').map(f => f.family).join()").count(
        "Audiowide"
    )
    pictures = page.evaluate(
        """() => Promise.all([...document.querySelectorAll('.decor')].map(e => getComputedStyle(e).backgroundImage)
          .flatMap(b => [...b.matchAll(/url\\("([^"]+)"\\)/g)].map(m => m[1]))
          .map(src => new Promise(ok => { const i = new Image(); i.onload = () => ok([src, true]);
            i.onerror = () => ok([src, false]); i.src = src; })))"""
    )
    assert len(pictures) >= 2 and all(loaded for _, loaded in pictures), pictures
    assert problems == []
