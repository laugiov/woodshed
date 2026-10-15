"""The look of the pages: the woodshed logo, dark by default, light on demand, remembered."""

from __future__ import annotations

from typing import Any

from playwright.sync_api import Browser, expect

from tests.page.conftest import built


def bg(page: Any) -> str:
    color: str = page.evaluate("getComputedStyle(document.body).backgroundColor")
    return color


def test_the_page_is_dark_by_default_light_on_demand_and_remembers(browser: Browser, pages_root: str) -> None:
    context = browser.new_context(color_scheme="light", locale="en-US")  # even when the computer is set to light
    page = context.new_page()
    url = (built("pop", True, pages_root) / "index.html").as_uri()
    page.goto(url)
    expect(page.locator("html")).to_have_attribute("data-theme", "dark")
    assert bg(page) == "rgb(13, 18, 16)"
    expect(page.get_by_test_id("logo")).to_be_visible()
    button = page.get_by_test_id("theme")
    expect(button).to_have_attribute("aria-label", "Switch to the light theme")
    button.click()
    expect(page.locator("html")).to_have_attribute("data-theme", "light")
    assert bg(page) == "rgb(230, 234, 231)"
    expect(button).to_have_attribute("aria-label", "Switch to the dark theme")
    page.reload()
    expect(page.locator("html")).to_have_attribute("data-theme", "light")  # remembered
    context.close()
