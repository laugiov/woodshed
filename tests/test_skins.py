"""Skins (spec 030): the contract the page keeps with every skin, and every skin with the page.

The page draws with tokens only (colours, fonts, radii, shadows), so a feature added tomorrow works in every skin:
the scans below fail on a literal a skin could not reach. A skin sets tokens and draws in decor slots only, both
themes, legible: the checks below say what is missing or too faint."""

from __future__ import annotations

import math
import re
from pathlib import Path

import pytest

PAGE = Path(__file__).parents[1] / "src" / "woodshed" / "page"
ASSETS = PAGE / "assets"
SKINS = ASSETS / "skins"
APP_CSS = ASSETS / "app.css"

COLOUR = re.compile(r"#[0-9a-fA-F]{3,8}\b|\b(?:rgba?|hsla?)\((?![^)]*var\()[^)]*\)|\b(?:black|white)\b")
COLOUR_TOKENS = ("bg", "panel", "sheet", "dock", "ink", "muted", "line", "accent", "accent-soft", "accent-ink",
                 "warn", "warn-soft", "wave")  # fmt: skip


def registry_slots() -> list[str]:
    text = (SKINS / "skins.js").read_text(encoding="utf-8")
    found = re.search(r"slots: \[([^\]]*)\]", text)
    assert found is not None
    return re.findall(r'"([a-z-]+)"', found.group(1))


SLOTS = tuple(registry_slots())


# A small reader for the page's own CSS: enough for its format (no nested rules, no strings with braces).


def rules(css: str) -> list[tuple[tuple[str, ...], str, list[tuple[str, str]]]]:
    """Every style rule: (the at-rules around it, its selector, its declarations)."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    out: list[tuple[tuple[str, ...], str, list[tuple[str, str]]]] = []
    stack: list[str] = []
    head = ""
    i = 0
    while i < len(css):
        c = css[i]
        if c == "{":
            prelude = head.strip()
            head = ""
            if prelude.startswith("@") and not prelude.startswith(("@font-face", "@page")):
                stack.append(prelude)
                i += 1
                continue
            end = css.index("}", i)
            body = css[i + 1 : end]
            decls = [(p.strip(), v.strip()) for p, _, v in (d.partition(":") for d in body.split(";")) if p.strip()]
            out.append((tuple(stack), prelude, decls))
            i = end + 1
            continue
        if c == "}":
            if stack:
                stack.pop()
            head = ""
        elif c == ";" and head.strip().startswith("@"):
            out.append((tuple(stack), head.strip(), []))  # @import …;
            head = ""
        else:
            head += c
        i += 1
    return out


def in_print(at: tuple[str, ...]) -> bool:
    return any(a.startswith("@media") and "print" in a for a in at)


# What the page may write as a literal, and why.
LITERAL_COLOURS_ALLOWED = {
    "[hidden]": "not a colour",
}
FONT_ALLOWED = {".brand"}  # the logo's own font: never a skin's (R11)


def literal_colours(css: str) -> list[str]:
    """Colours written outside a token's definition and outside paper (print stays black on white)."""
    found = []
    for at, selector, decls in rules(css):
        if in_print(at) or any(a.startswith("@keyframes") for a in at):
            continue
        for prop, value in decls:
            if prop.startswith("--"):
                continue  # a token's own value
            found += [f"{selector} {{ {prop}: {value} }}" for _ in COLOUR.findall(value)[:1]]
    return found


RADIUS_OK = re.compile(
    r"^(?:(?:0|50%|999px|var\(--radius(?:-sm)?\)|calc\(var\(--radius(?:-sm)?\) \* [0-9.]+\))\s*)+(?:!important)?$"
)


def literal_radii(css: str) -> list[str]:
    """Radii in px outside the tokens: a skin's square or round look would not reach them."""
    return [
        f"{selector} {{ {prop}: {value} }}"
        for at, selector, decls in rules(css)
        if not in_print(at)
        for prop, value in decls
        if re.fullmatch(r"border(?:-[a-z]+)*-radius", prop) and not RADIUS_OK.match(value)
    ]


def literal_fonts(css: str) -> list[str]:
    return [
        f"{selector} {{ {prop}: {value} }}"
        for at, selector, decls in rules(css)
        if not in_print(at) and selector not in FONT_ALLOWED
        for prop, value in decls
        if (prop == "font-family" and not value.startswith("var(--"))
        or (prop == "font" and value != "inherit" and "var(--" not in value)
    ]


def test_the_page_writes_no_colour_a_skin_cannot_reach() -> None:
    assert literal_colours(APP_CSS.read_text(encoding="utf-8")) == []


def test_every_radius_is_a_token() -> None:
    assert literal_radii(APP_CSS.read_text(encoding="utf-8")) == []


def test_every_font_is_a_token_but_the_logos() -> None:
    assert literal_fonts(APP_CSS.read_text(encoding="utf-8")) == []


@pytest.mark.parametrize(
    ("planted", "scan"),
    [
        (".x { color: #123456; }", literal_colours),
        (".x { box-shadow: 0 1px 2px rgba(0, 0, 0, 0.3); }", literal_colours),
        (".x { border-radius: 7px; }", literal_radii),
        (".x { border-top-left-radius: 7px 0; }", literal_radii),
        (".x { font-family: Comic Sans MS, cursive; }", literal_fonts),
    ],
)
def test_the_scans_catch_a_planted_literal(planted: str, scan: object) -> None:
    base = APP_CSS.read_text(encoding="utf-8")
    assert callable(scan) and len(scan(base + "\n" + planted)) == len(scan(base)) + 1


PAGE_SCRIPTS = sorted((ASSETS / "js").rglob("*.js"))
# The QR code the phones scan is black on white whatever the skin: a reader needs that contrast.
SCRIPT_COLOURS_ALLOWED = {"home/home.js": 2}
JS_COLOUR = re.compile(r"""["'`](?:#[0-9a-fA-F]{3,8}|(?:rgba?|hsla?)\([^)]*\)|black|white)["'`]""")


def test_no_page_script_writes_a_colour() -> None:
    counts = {
        p.relative_to(ASSETS / "js").as_posix(): len(JS_COLOUR.findall(p.read_text(encoding="utf-8")))
        for p in PAGE_SCRIPTS
    }
    assert {k: n for k, n in counts.items() if n} == SCRIPT_COLOURS_ALLOWED


HTML_STYLE_COLOUR = re.compile(r'style="[^"]*(?:#[0-9a-fA-F]{3,8}\b|rgba?\()')
SVG_COLOUR = re.compile(r'(?:fill|stroke)="(?!none|currentColor)[^"]+"')


def test_no_page_markup_writes_a_colour() -> None:
    found = {}
    for name in ("template.html", "body.html", "home.html"):
        text = (PAGE / name).read_text(encoding="utf-8")
        # The note shown when the stylesheet did not load (a page opened inside a ZIP): it cannot use tokens.
        text = re.sub(r'<div class="missing-files".*?</div>', "", text, flags=re.S)
        found[name] = HTML_STYLE_COLOUR.findall(text) + SVG_COLOUR.findall(text)
    assert found == {"template.html": [], "body.html": [], "home.html": []}


# Tokens: the base's, read from app.css, and what a skin sets.


def blocks(css: str) -> dict[str, dict[str, str]]:
    """Custom properties per selector (comma lists split)."""
    out: dict[str, dict[str, str]] = {}
    for at, selector, decls in rules(css):
        if in_print(at):
            continue
        for one in (s.strip() for s in selector.split(",")):
            out.setdefault(one, {}).update({p[2:]: v for p, v in decls if p.startswith("--")})
    return out


def base_tokens() -> dict[str, dict[str, str]]:
    found = blocks(APP_CSS.read_text(encoding="utf-8"))
    return {"light": found[":root"], "dark": {**found[":root"], **found[':root[data-theme="dark"]']}}


def lin(x: float) -> float:
    return x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4


def rgb(hex_colour: str) -> list[float]:
    h = hex_colour.lstrip("#")
    return [int(h[i : i + 2], 16) / 255 for i in (0, 2, 4)]


def contrast(a: str, b: str) -> float:
    def lum(h: str) -> float:
        r, g, b_ = (lin(x) for x in rgb(h))
        return 0.2126 * r + 0.7152 * g + 0.0722 * b_

    hi, lo = sorted((lum(a), lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


# Machado, Oliveira and Fernandes 2009, severity 1, on linear RGB.
COLOUR_BLIND = {
    "deuteranope": [[0.367322, 0.860646, -0.227968], [0.280085, 0.672501, 0.047413], [-0.011820, 0.042940, 0.968881]],
    "protanope": [[0.152286, 1.052583, -0.204868], [0.114503, 0.786281, 0.099216], [-0.003882, -0.048116, 1.051998]],
}


def oklab(c: list[float]) -> tuple[float, float, float]:
    r, g, b = c
    lc = (0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b) ** (1 / 3)
    mc = (0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b) ** (1 / 3)
    sc = (0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b) ** (1 / 3)
    return (0.2104542553 * lc + 0.7936177850 * mc - 0.0040720468 * sc,
            1.9779984951 * lc - 2.4285922050 * mc + 0.4505937099 * sc,
            0.0259040371 * lc + 0.7827717662 * mc - 0.8086757660 * sc)  # fmt: skip


def apart(a: str, b: str) -> float:
    """How far two colours stay for the colour-blind (OKLab distance × 100, the closer of two simulations)."""

    def seen(h: str, m: list[list[float]]) -> list[float]:
        c = [lin(x) for x in rgb(h)]
        return [max(0.0, min(1.0, sum(m[i][j] * c[j] for j in range(3)))) for i in range(3)]

    return min(100 * math.dist(oklab(seen(a, m)), oklab(seen(b, m))) for m in COLOUR_BLIND.values())


STRICT = {"spotlight"}  # 7:1 text (WCAG AAA): sunlight, or a dark stage


def palette_problems(name: str, t: dict[str, str], base: dict[str, str]) -> list[str]:
    """R22 and R23: what is too faint or too close in one theme of a skin."""
    text = 7.0 if name in STRICT else 4.5
    pairs = [(f, g, text) for f in ("ink", "muted", "warn") for g in ("bg", "panel", "sheet", "dock")]
    ui = 4.5 if name in STRICT else 3.0
    pairs += [("accent-ink", "accent", text), ("ink", "accent-soft", text), ("muted", "accent-soft", text),
              ("warn", "warn-soft", text), ("ink", "warn-soft", text),
              ("accent", "panel", ui), ("accent", "sheet", ui)]  # fmt: skip
    pairs += [("wave", g, min(contrast(base["wave"], base[s]) for s in ("panel", "dock"))) for g in ("panel", "dock")]
    bad = [
        f"{f} on {g}: {contrast(t[f], t[g]):.2f} < {floor:.2f}"
        for f, g, floor in pairs
        if contrast(t[f], t[g]) < floor - 0.005
    ]
    if apart(t["accent"], t["warn"]) < 10:
        bad.append(f"accent and warn too close for the colour-blind: {apart(t['accent'], t['warn']):.1f} < 10")
    return bad


def test_the_base_passes_its_own_floors() -> None:
    base = base_tokens()
    for theme in ("light", "dark"):
        assert palette_problems("woodshed", base[theme], base[theme]) == []


# A skin: what it may write (R8 to R10).

SCOPE = r':root\[data-skin="{id}"\](?:\[data-theme="dark"\])?'
SLOT_RULE = (
    SCOPE + r'(?:\[data-playing\])? \.decor\[data-slot="(?P<slot>[a-z-]+)"\](?:\[data-set-title\])?'
    r"(?: i(?::first-child|:last-child)?)?(?:::before|::after)?"
)


def skin_problems(skin: str, css: str) -> list[str]:
    """Everything a skin does that the contract does not allow, or leaves out."""
    tokens_known = set(base_tokens()["light"])
    problems = []
    token_selectors = {
        f':root[data-skin="{skin}"]': "light",
        f'[data-skin-probe="{skin}"]': "light",
        f':root[data-skin="{skin}"][data-theme="dark"]': "dark",
        f':root[data-theme="dark"] [data-skin-probe="{skin}"]': "dark",
    }
    themes: dict[str, dict[str, str]] = {"light": {}, "dark": {}}
    for at, selector, decls in rules(css):
        if selector.startswith("@font-face") or selector.startswith("@import"):
            continue
        if any(a.startswith("@keyframes") for a in at):
            continue
        if any(not a.startswith(("@media", "@keyframes")) for a in at):
            problems.append(f"at-rule not allowed: {at}")
        for one in (s.strip() for s in selector.split(",")):
            if one in token_selectors:
                for prop, value in decls:
                    if not prop.startswith("--"):
                        problems.append(f"{one}: only tokens here, not {prop}")
                    elif prop[2:] not in tokens_known:
                        problems.append(f"{one}: unknown token {prop}")
                    elif "url(" in value:
                        problems.append(f"{one}: no url() in a token ({prop}): images go in a decor slot")
                    else:
                        themes[token_selectors[one]][prop[2:]] = value
            else:
                m = re.fullmatch(SLOT_RULE.format(id=re.escape(skin)), one)
                if not m:
                    problems.append(f"selector outside the skin's tokens and slots: {one}")
                elif m.group("slot") not in SLOTS:
                    problems.append(f"no such decor slot: {m.group('slot')}")
                elif any(p.startswith("--") for p, _ in decls):
                    problems.append(f"{one}: tokens are set on the skin's scope, not on a slot")
    for theme, values in themes.items():
        for name in COLOUR_TOKENS:
            got = values.get(name)
            if got is None:
                problems.append(f"{theme}: --{name} missing")
            elif not re.fullmatch(r"#[0-9a-fA-F]{6}", got):
                problems.append(f"{theme}: --{name} is not a plain colour ({got})")
    return problems


def skin_tokens(css: str, skin: str) -> dict[str, dict[str, str]]:
    found = blocks(css)
    light = found[f':root[data-skin="{skin}"]']
    return {"light": light, "dark": {**light, **found[f':root[data-skin="{skin}"][data-theme="dark"]']}}


GOOD = """
:root[data-skin="t"], [data-skin-probe="t"] { --bg: #ffffff; --panel: #ffffff; --sheet: #ffffff; --dock: #ffffff;
  --ink: #000000; --muted: #333333; --line: #777777; --accent: #0038a8; --accent-soft: #dce6ff; --accent-ink: #ffffff;
  --warn: #7a2e00; --warn-soft: #ffe6d1; --wave: #8c8c8c; }
:root[data-skin="t"][data-theme="dark"], :root[data-theme="dark"] [data-skin-probe="t"] { --bg: #000000;
  --panel: #000000; --sheet: #0a0a0a; --dock: #000000; --ink: #ffffff; --muted: #d6d6d6; --line: #7a7a7a;
  --accent: #ffd400; --accent-soft: #3d3300; --accent-ink: #000000; --warn: #5cc8ff; --warn-soft: #08283a;
  --wave: #6e6e6e; }
:root[data-skin="t"] .decor[data-slot="player"] { display: block; }
:root[data-skin="t"][data-playing] .decor[data-slot="player"] i:first-child { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(1turn); } }
@media (max-width: 600px) { :root[data-skin="t"] .decor[data-slot="page"] { background-size: 200px; } }
"""


def test_a_skin_that_keeps_the_contract_passes() -> None:
    assert skin_problems("t", GOOD) == []


@pytest.mark.parametrize(
    ("broken", "said"),
    [
        (GOOD.replace("--warn: #7a2e00;", ""), "light: --warn missing"),
        (GOOD.replace("--wave: #6e6e6e;", "--wave: color-mix(in srgb, red, blue);"), "not a plain colour"),
        (GOOD + ':root[data-skin="t"] { --bg-image: url("x.svg"); }', "unknown token --bg-image"),
        (GOOD + ':root[data-skin="t"] { --dock-image: url("x.svg"); }', "no url() in a token"),
        (GOOD + ':root[data-skin="t"] body { background: red; }', "outside the skin's tokens and slots"),
        (GOOD + ':root[data-skin="t"] .dock { padding: 0; }', "outside the skin's tokens and slots"),
        (GOOD + ':root[data-skin="other"] .decor[data-slot="page"] { display: block; }', "outside the skin"),
        (GOOD + ':root[data-skin="t"] .decor[data-slot="nowhere"] { display: block; }', "no such decor slot"),
        (GOOD + ':root[data-skin="t"] { color: red; }', "only tokens here"),
    ],
)
def test_a_skin_that_breaks_the_contract_is_told_why(broken: str, said: str) -> None:
    assert any(said in p for p in skin_problems("t", broken))


def test_a_faint_palette_is_told_why() -> None:
    base = base_tokens()["light"]
    faint = {**skin_tokens(GOOD, "t")["light"], "muted": "#9a9a9a"}
    assert any(p.startswith("muted on") for p in palette_problems("t", faint, base))
    close = {**skin_tokens(GOOD, "t")["light"], "warn": "#7a1f1f", "accent": "#a0261d"}
    assert any("colour-blind" in p for p in palette_problems("t", close, base))


def test_every_decor_slot_of_the_pages_is_listed_once() -> None:
    """A slot added to a page is one element and one line in skins.js: a skin can only draw where the list says."""
    in_markup = []
    for name in ("body.html", "home.html"):
        in_markup += re.findall(r'class="decor" data-slot="([a-z-]+)"', (PAGE / name).read_text(encoding="utf-8"))
    home = (ASSETS / "js" / "home" / "home.js").read_text(encoding="utf-8")
    in_markup += re.findall(r'decorSlot\("([a-z-]+)"\)', home)
    assert set(in_markup) == set(SLOTS) and len(set(SLOTS)) == len(SLOTS)


# The skins woodshed ships (A4 to A6, R25, R26).


def registry() -> list[dict[str, str]]:
    text = (SKINS / "skins.js").read_text(encoding="utf-8")
    return [
        {"id": i, "name": n, "description": d}
        for i, n, d in re.findall(r'\{ id: "([a-z0-9]+)", name: "([^"]+)", description: "([^"]+)" \}', text)
    ]


SHIPPED = sorted(p.parent.name for p in SKINS.glob("*/skin.css") if not p.parent.name.startswith("_"))


def test_the_registry_the_folders_and_the_imports_agree() -> None:
    ids = [s["id"] for s in registry()]
    assert ids[0] == "woodshed" and len(set(ids)) == len(ids)  # the base first, each once
    assert sorted(ids[1:]) == SHIPPED
    imports = re.findall(r'@import url\("([a-z0-9]+)/skin\.css"\) screen;', (SKINS / "skins.css").read_text("utf-8"))
    assert sorted(imports) == SHIPPED  # each for the screen only: paper never sees a skin


@pytest.mark.parametrize("skin", SHIPPED)
def test_a_shipped_skin_keeps_the_contract(skin: str) -> None:
    assert skin_problems(skin, (SKINS / skin / "skin.css").read_text(encoding="utf-8")) == []


@pytest.mark.parametrize("skin", SHIPPED)
def test_a_shipped_skin_is_legible_and_its_colours_keep_their_meaning(skin: str) -> None:
    tokens = skin_tokens((SKINS / skin / "skin.css").read_text(encoding="utf-8"), skin)
    base = base_tokens()
    assert {t: palette_problems(skin, tokens[t], base[t]) for t in ("light", "dark")} == {"light": [], "dark": []}


def test_every_skin_says_its_name_in_french() -> None:
    french = (ASSETS / "js" / "core" / "i18n-fr.js").read_text(encoding="utf-8")
    said = [s[k] for s in registry() for k in ("name", "description") if s["id"] != "woodshed" or k == "description"]
    assert [t for t in said if f'"{t}":' not in french] == []


FONT_LICENCES = ("OFL", "Apache License")


def test_every_skin_font_is_licensed_and_pinned() -> None:
    pinned = (Path(__file__).parents[1] / "scripts" / "vendored.sha256").read_text(encoding="utf-8")
    fonts = sorted((SKINS / "_fonts").glob("*.woff2"))
    for font in fonts:
        licence = SKINS / "_fonts" / f"LICENSE-{font.stem}.txt"
        assert licence.is_file(), font.name
        assert any(word in licence.read_text(encoding="utf-8") for word in FONT_LICENCES), licence.name
        assert f"src/woodshed/page/assets/skins/_fonts/{font.name}" in pinned
    used = set()
    for css in SKINS.glob("*/skin.css"):
        used |= set(re.findall(r'url\("\.\./_fonts/([^"]+)"\)', css.read_text(encoding="utf-8")))
    assert used == {f.name for f in fonts}  # no font shipped for nothing, none missing


def test_the_skins_stay_light() -> None:
    """Every page folder carries a copy (R26)."""
    size = lambda folder: sum(p.stat().st_size for p in folder.rglob("*") if p.is_file())  # noqa: E731
    for folder in SKINS.iterdir():
        if folder.is_dir() and folder.name != "_fonts":
            assert size(folder) <= 60 * 1024, folder.name
    if (SKINS / "_fonts").is_dir():
        assert size(SKINS / "_fonts") <= 200 * 1024
    assert size(SKINS) <= 450 * 1024


def test_every_page_loads_the_skins() -> None:
    for name, prefix in (("template.html", "assets/"), ("home.html", "/app/assets/")):
        text = (PAGE / name).read_text(encoding="utf-8")
        app_css = text.index(f'href="{prefix}app.css"')
        assert text.index(f'href="{prefix}skins/skins.css"') > app_css  # after the base: a skin's tokens win
        assert text.index(f'src="{prefix}skins/skins.js"') < text.index(f'src="{prefix}js/core/prefs.js"')
