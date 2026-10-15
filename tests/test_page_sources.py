"""Static rules on the page sources: no markup from strings, every script loaded, nothing remote."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

PAGE = Path(__file__).resolve().parents[1] / "src" / "woodshed" / "page"
OWN_JS = sorted(p for p in (PAGE / "assets" / "js").rglob("*.js"))
FORBIDDEN = re.compile(r"innerHTML|outerHTML|insertAdjacentHTML|document\.write|\beval\(|new Function")


@pytest.mark.parametrize("script", OWN_JS, ids=lambda p: p.name)
def test_page_code_never_parses_strings_as_markup_or_code(script: Path) -> None:
    # Song data (titles, file names) reaches the DOM only as text: see core/woodshed.js.
    assert FORBIDDEN.findall(script.read_text(encoding="utf-8")) == []


def test_every_script_is_loaded_by_the_template_in_dependency_order() -> None:
    template = (PAGE / "template.html").read_text(encoding="utf-8")
    loaded = re.findall(r'<script src="assets/js/([^"]+)"></script>', template)
    song_page = [p for p in OWN_JS if p.parent.name != "home"]  # home/: the library page of `woodshed app`
    assert sorted(loaded) == sorted(p.relative_to(PAGE / "assets" / "js").as_posix() for p in song_page)
    # prefs.js first, in <head>: it depends on nothing and sets the theme before the page is drawn.
    assert loaded[:2] == ["core/prefs.js", "core/woodshed.js"] and loaded[-1] == "app.js"
    assert loaded.index("core/song.js") < loaded.index("views/chart.js")


def test_the_page_forbids_remote_content() -> None:
    template = (PAGE / "template.html").read_text(encoding="utf-8")
    policy = re.search(r'http-equiv="Content-Security-Policy" content="([^"]+)"', template)
    assert policy is not None
    rules = dict(rule.strip().split(" ", 1) for rule in policy.group(1).split(";"))
    # connect-src 'self': served by `woodshed app`, the page talks to that app only (the band);
    # opened from disk it has no server to talk to.
    assert rules["default-src"] == "'self'" and rules["connect-src"] == "'self'" and rules["script-src"] == "'self'"


# The data a page carries, by format version: a page built by an older woodshed gets the new page
# code only when its data has the format that code reads (build.refresh_code). A schema change
# must come with a new version number, here, in song.py or view.py, and in core/song.js.
DATA_FORMATS = {(2, 1): ("9ab2b7d621a5157b", "6c8a1aef3cb83902")}


def test_a_change_of_the_page_data_format_comes_with_a_new_version() -> None:
    import hashlib

    from woodshed.song import SCHEMA_VERSION
    from woodshed.view import VIEW_VERSION

    src = PAGE.parent
    hashes = tuple(
        hashlib.sha256((src / f).read_bytes().replace(b"\r\n", b"\n")).hexdigest()[:16]
        for f in ("song.schema.json", "view.schema.json")
    )
    assert DATA_FORMATS.get((SCHEMA_VERSION, VIEW_VERSION)) == hashes, "bump SCHEMA_VERSION or VIEW_VERSION"
    js = (PAGE / "assets" / "js" / "core" / "song.js").read_text(encoding="utf-8")
    assert f"const SONG_VERSION = {SCHEMA_VERSION};" in js and f"const VIEW_VERSION = {VIEW_VERSION};" in js
