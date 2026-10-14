"""Browser tests of the practice page, with Playwright, on pages built from the synthetic songs.

Every test opens the page from disk (file://). Any network request, console error or console
warning fails the test. Browsers are chosen with pytest-playwright's --browser option.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

import pytest
from playwright.sync_api import ConsoleMessage, Page, Request

from tests import synth
from tests.test_analysis import fake_stems
from woodshed import analysis, build

REQUIRED = os.environ.get("WOODSHED_REQUIRE_PAGE") == "1"


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    here = Path(__file__).parent
    for item in items:
        if Path(str(item.fspath)).is_relative_to(here):
            item.add_marker(pytest.mark.page)


@pytest.fixture(scope="session", autouse=True)
def _browsers_installed(request: pytest.FixtureRequest) -> None:
    try:
        request.getfixturevalue("browser")
    except Exception as exc:  # Playwright raises its own Error when a browser is missing
        if REQUIRED:
            raise
        pytest.skip(f"browser not available ({str(exc).splitlines()[0]}): run `playwright install`")


@cache
def built(name: str, stems: bool, root: str, title: str | None = None) -> Path:
    folder = Path(root)
    wav = synth.write(name, folder / "src").wav
    per = synth.SONGS[name].beats_per_bar
    separated = fake_stems(name, folder / "src") if stems else None
    result = analysis.analyze(wav, use_stems=stems, stems_result=separated, beats_per_bar=per, title=title)
    return build.build(result, wav, folder / "pages" / f"{name}-{int(stems)}", separated)


@pytest.fixture(scope="session")
def pages_root(tmp_path_factory: pytest.TempPathFactory) -> str:
    return str(tmp_path_factory.mktemp("pages"))


@dataclass
class Opened:
    page: Page
    folder: Path
    network: list[str] = field(default_factory=list)
    console: list[str] = field(default_factory=list)

    def js(self, expression: str, arg: object = None) -> object:
        return self.page.evaluate(expression, arg)


@pytest.fixture
def open_page(page: Page, pages_root: str) -> Iterator[object]:
    opened: list[Opened] = []

    def open_(name: str = "pop", stems: bool = True, title: str | None = None) -> Opened:
        folder = built(name, stems, pages_root, title)
        o = Opened(page, folder)

        def on_request(req: Request) -> None:
            if not req.url.startswith(("file://", "data:", "blob:")):
                o.network.append(req.url)

        def on_console(msg: ConsoleMessage) -> None:
            if msg.type in ("error", "warning"):
                o.console.append(f"{msg.type}: {msg.text}")

        page.on("request", on_request)
        page.on("console", on_console)
        page.on("pageerror", lambda exc: o.console.append(f"pageerror: {exc}"))
        page.route(
            "**/*", lambda route: route.continue_() if route.request.url.startswith("file://") else route.abort()
        )
        page.goto((folder / "index.html").as_uri())
        for _ in range(200):  # polled: the page's CSP forbids Playwright's string evaluation
            if page.evaluate("window.Woodshed && window.Woodshed.ready === true"):
                break
            page.wait_for_timeout(25)
        opened.append(o)
        return o

    yield open_
    for o in opened:
        assert o.network == [], f"the page tried the network: {o.network}"
        assert o.console == [], f"console errors or warnings: {o.console}"
