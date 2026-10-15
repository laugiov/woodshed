"""Browser tests of the practice page, with Playwright, on pages built from the synthetic songs.

Every test opens the page from disk (file://). Any network request, console error or console
warning fails the test. Browsers are chosen with pytest-playwright's --browser option.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any

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


@cache
def with_close_calls(name: str, stems: bool, root: str) -> Path:
    """The page of `name` with every doubt turned into a close call (the synthetic songs only have
    timing doubts: their chords are clear)."""
    source = built(name, stems, root)
    folder = source.with_name(source.name.replace(".woodshed", "-close.woodshed"))
    shutil.copytree(source, folder)
    page = folder / "index.html"
    text = page.read_text(encoding="utf-8")
    assert '"kind":"timing"' in text
    page.write_text(text.replace('"kind":"timing"', '"kind":"chord"'), encoding="utf-8")
    return folder


def rewritten(name: str, root: str, tag: str, change: Callable[[dict[str, Any]], None]) -> Path:
    """A copy of the page of `name` whose song data `change` rewrote."""
    source = built(name, True, root)
    folder = source.with_name(source.name.replace(".woodshed", f"-{tag}.woodshed"))
    if folder.exists():
        return folder
    shutil.copytree(source, folder)
    page = folder / "index.html"
    text = page.read_text(encoding="utf-8")
    match = re.search(r'(<script type="application/json" id="woodshed-data">)(.*?)(</script>)', text, re.S)
    assert match is not None
    data = json.loads(match.group(2))
    change(data["song"])
    page.write_text(text[: match.start(2)] + build.script_json(data) + text[match.end(2) :], encoding="utf-8")
    return folder


def _two_sections(song: dict[str, Any]) -> None:
    """pop as a verse and a chorus: each line its own group, two sections of one line each."""
    bars = song["bars"]
    lines = [list(range(i, min(i + 4, len(bars)))) for i in range(0, len(bars), 4)]
    song["groups"] = [{"label": "A", "family": "A", "occurrences": [line]} for line in lines]
    for g, line in enumerate(lines):
        for c, i in enumerate(line):
            bars[i].update(group=g, occurrence=0, column=c)
    song["sections"] = [
        {"name": "Verse 1", "role": "verse", "letter": "A", "start": 0, "end": 4},
        {"name": "Chorus 1", "role": "chorus", "letter": "B", "start": 4, "end": len(bars)},
    ]


def _no_sections(song: dict[str, Any]) -> None:
    song["sections"] = []


VARIANTS: dict[str, Callable[[dict[str, Any]], None]] = {"sections": _two_sections, "nosections": _no_sections}


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

    def open_(
        name: str = "pop", stems: bool = True, title: str | None = None, close_calls: bool = False, variant: str = ""
    ) -> Opened:
        if variant:
            folder = rewritten(name, pages_root, variant, VARIANTS[variant])
        elif close_calls:
            folder = with_close_calls(name, stems, pages_root)
        else:
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
