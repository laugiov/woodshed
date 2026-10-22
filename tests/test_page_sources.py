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


# The page in French (core/i18n.js, core/i18n-fr.js): every text of the page's own is translated.
def french() -> dict[str, str]:
    src = (PAGE / "assets" / "js" / "core" / "i18n-fr.js").read_text(encoding="utf-8")
    pairs = re.findall(r'^\s*(?:"((?:[^"\\]|\\.)*)"|([A-Za-z]+)):\s*\n?\s*"((?:[^"\\]|\\.)*)",?$', src, re.M)
    return {(quoted or bare).replace('\\"', '"'): fr for quoted, bare, fr in pairs}


TRANSLATED = re.compile(r'\bW\.t\(\s*"((?:[^"\\]|\\.)*)"')
NOT_WORDS = {"BPM", "EN", "FR", "auto", "+ Set", "English", "Français"}  # the same in French, or each in its own


def test_every_text_the_page_code_says_has_its_french() -> None:
    fr = french()
    missing = [
        f"{p.relative_to(PAGE)}: {text}"
        for p in OWN_JS
        for text in TRANSLATED.findall(p.read_text(encoding="utf-8"))
        if text.replace('\\"', '"') not in fr
    ]
    assert missing == []


def test_no_text_has_two_frenchs() -> None:
    """A key given twice: the later French silently replaces the earlier, wherever the text is used."""
    source = (PAGE / "assets" / "js" / "core" / "i18n-fr.js").read_text(encoding="utf-8")
    keys = [k.strip('"') for k in re.findall(r'^\s*("(?:[^"\\]|\\.)*"|[A-Za-z_]\w*):', source, re.M)]
    assert sorted({k for k in keys if keys.count(k) > 1}) == []


def test_every_fixed_text_of_the_pages_has_its_french() -> None:
    from html.parser import HTMLParser

    class Texts(HTMLParser):
        def __init__(self) -> None:
            super().__init__()
            self.found: list[str] = []
            self.kept: list[bool] = []  # inside translate="no", code or a drawing

        def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            a = dict(attrs)
            if tag not in ("br", "img", "input", "meta", "link", "path", "rect", "line", "circle"):
                self.kept.append(a.get("translate") == "no" or tag in ("script", "style", "svg", "code", "pre"))
            if not any(self.kept):
                self.found += [v for k, v in a.items() if k in ("title", "aria-label", "placeholder") and v]

        def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            if not any(self.kept):  # <path ... />: no content, nothing to close
                self.found += [v for k, v in attrs if k in ("title", "aria-label", "placeholder") and v]

        def handle_endtag(self, tag: str) -> None:
            if self.kept:
                self.kept.pop()

        def handle_data(self, data: str) -> None:
            if data.strip() and not any(self.kept):
                self.found.append(" ".join(data.split()))

    fr = french()
    missing = []
    for name in ("body.html", "home.html"):
        texts = Texts()
        texts.feed((PAGE / name).read_text(encoding="utf-8"))
        words = [t for t in texts.found if len(re.findall(r"[A-Za-z]", t)) > 1 and t not in NOT_WORDS]
        missing += [f"{name}: {t}" for t in words if t not in fr]
    assert missing == []


SAME_IN_FRENCH = {"structure"}  # an analysis step's name the page shows as it is


def test_every_text_the_page_shows_from_python_has_its_french() -> None:
    """Doubt reasons, sung-line checks, progression names, track labels, job steps and the library's
    reasons for saying no come from Python: the page says them through W.t(variable)."""
    from woodshed import theory, tracks

    src = PAGE.parent

    def found(name: str, pattern: str) -> list[str]:
        return re.findall(pattern, (src / name).read_text(encoding="utf-8"))

    texts = [name for _, name in theory.PROGRESSIONS] + [t.label for t in tracks.track_list(True)]
    texts += [s for pair in found("structure.py", r'why = \(\s*"([^"]+)"[^"]*"([^"]+)"') for s in pair]
    texts += found("lyrics.py", r'left\[[^\]]+\] = "([^"]+)"') + found("lyrics.py", r'check = "([^"]+)"')
    texts += found("lyrics.py", r'say\("([^"]+)"\)') + found("lyrics.py", r'^(?:LISTENING|CHORUS_NOTE) = "([^"]+)"')
    texts += found("analysis.py", r'report\("([a-z]+)"') + found("app.py", r'_error\(HTTPStatus\.\w+, "([^"]+)"\)')
    assert len(texts) > 40  # the patterns still find what they look for
    fr = french()
    assert [t for t in dict.fromkeys(texts) if t not in fr and t not in SAME_IN_FRENCH] == []


def test_every_french_text_keeps_the_names_it_fills_in() -> None:
    names = re.compile(r"\{(\w+)\}")
    assert [en for en, fr in french().items() if sorted(names.findall(en)) != sorted(names.findall(fr))] == []
