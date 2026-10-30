"""Two sweeps over the real pages in every skin (spec 030, R24, A18): nothing on screen escapes the tokens, and every
text reads against what is really behind it (textures included)."""

from __future__ import annotations

import re
import struct
import zlib

import numpy as np
import pytest
from playwright.sync_api import Browser, Page

from tests.page.conftest import built
from tests.page.test_set_name_page import library, server  # noqa: F401  (the fixtures)
from tests.test_skins import COLOUR_TOKENS, SHIPPED, contrast
from woodshed import app

THEMES = ("light", "dark")


def song_page(browser: Browser, root: str, theme: str, skin: str | None = None) -> Page:
    context = browser.new_context(locale="en-US", viewport={"width": 1440, "height": 900}, reduced_motion="reduce")
    context.add_init_script(
        f"localStorage.setItem('woodshed:theme', '{theme}');"
        + (f"localStorage.setItem('woodshed:skin', '{skin}');" if skin else "")
    )
    page = context.new_page()
    page.goto((built("pop", True, root) / "index.html").as_uri())
    page.wait_for_function("window.Woodshed && window.Woodshed.ready === true")
    page.evaluate("document.fonts.ready")
    return page


# 1. The sentinel sweep: two palettes of distinct colours for the tokens; a colour on screen that stays the same in
# both comes from no token, so no skin can reach it.

COLOURS_SEEN = """() => {
  const out = {};
  const seen = (c) => c && c !== 'transparent' && !/^rgba\\(.*, 0\\)$/.test(c);
  for (const e of document.querySelectorAll('body *')) {
    if (e.closest('.decor, svg.qr, canvas, .dots, .swatch') || !e.checkVisibility({ visibilityProperty: true })) continue;
    const s = getComputedStyle(e);
    if (s.visibility === 'hidden' || s.display === 'none') continue;
    const key = e.tagName + '#' + e.id + '.' + String(e.className).trim().replace(/\\s+/g, '.')
      + '[' + [...e.parentNode.children].indexOf(e) + ']';
    const text = [...e.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim());
    if (text && seen(s.color)) out[key + ' color'] = s.color;
    if (seen(s.backgroundColor)) out[key + ' background'] = s.backgroundColor;
    for (const side of ['Top', 'Right', 'Bottom', 'Left']) {
      if (s['border' + side + 'Style'] !== 'none' && parseFloat(s['border' + side + 'Width']) > 0
          && seen(s['border' + side + 'Color'])) out[key + ' border'] = s['border' + side + 'Color'];
    }
  }
  return out;
}"""


def sentinel(k: int, shift: int) -> str:
    return f"rgb({(37 * k + shift) % 256}, {(91 * k + 3 * shift) % 256}, {(53 * k + 7 * shift) % 256})"


def palette(shift: int) -> str:
    tokens = "".join(f"--{t}: {sentinel(k + 1, shift)};" for k, t in enumerate(COLOUR_TOKENS))
    return f":root, :root[data-theme], :root[data-skin][data-theme] {{ {tokens} --shadow-color: {shift} 0 {shift}; }}"


def fixed_colours(page: Page) -> dict[str, str]:
    """What stays the same under two palettes: colours that do not come from a token."""
    seen = []
    for shift in (11, 151):
        handle = page.add_style_tag(content=palette(shift))
        seen.append(page.evaluate(COLOURS_SEEN))
        handle.evaluate("s => s.remove()")
    a, b = seen
    return {k: v for k, v in a.items() if b.get(k) == v}


# What may keep a colour of its own, and why.
FIXED_ALLOWED = [
    r"^INPUT#.*background",  # a range slider's track: the browser's (its thumb follows the accent)
]
SWATCH = ".dots, .swatch"  # the style menu's swatches: each shows its own skin's colours, on purpose


def leaks(found: dict[str, str]) -> list[str]:
    return [f"{k}: {v}" for k, v in found.items() if not any(re.search(a, k) for a in FIXED_ALLOWED)]


def test_everything_on_a_song_page_and_on_stage_follows_the_tokens(browser: Browser, pages_root: str) -> None:
    page = song_page(browser, pages_root, "dark")
    assert leaks(fixed_colours(page)) == []
    page.get_by_test_id("stage-open").click()
    assert leaks(fixed_colours(page)) == []


def test_the_sentinel_sweep_catches_a_planted_colour(browser: Browser, pages_root: str) -> None:
    page = song_page(browser, pages_root, "dark")
    page.add_style_tag(content="#songTitle { color: #123456 !important; }")
    assert any(k.startswith("H1#songTitle") for k in leaks(fixed_colours(page)))


# 2. The contrast sweep: each text against the pixels around it, as the screen shows them.


def png_pixels(data: bytes) -> np.ndarray:
    """An 8-bit RGB(A) PNG as an array (height, width, 3), without an imaging library."""
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    pos, idat, width, height, kind = 8, b"", 0, 0, 0
    while pos < len(data):
        (length,) = struct.unpack(">I", data[pos : pos + 4])
        tag, body = data[pos + 4 : pos + 8], data[pos + 8 : pos + 8 + length]
        if tag == b"IHDR":
            width, height, depth, kind = struct.unpack(">IIBB", body[:10])
            assert depth == 8 and kind in (2, 6)
        elif tag == b"IDAT":
            idat += body
        pos += 12 + length
    channels = 4 if kind == 6 else 3
    raw = np.frombuffer(zlib.decompress(idat), dtype=np.uint8).reshape(height, 1 + width * channels)
    out = np.zeros((height, width * channels), dtype=np.int32)
    prev = np.zeros(width * channels, dtype=np.int32)
    for y in range(height):
        f, line = raw[y, 0], raw[y, 1:].astype(np.int32)
        if f == 0:
            row = line
        elif f == 2:
            row = (line + prev) & 255
        else:  # 1 sub, 3 average, 4 Paeth: they need the bytes to the left, one by one
            row = np.zeros_like(line)
            for x in range(len(line)):
                a = row[x - channels] if x >= channels else 0
                b = prev[x]
                c = prev[x - channels] if x >= channels else 0
                if f == 1:
                    p = a
                elif f == 3:
                    p = (a + b) // 2
                else:
                    pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
                    p = a if pa <= pb and pa <= pc else b if pb <= pc else c
                row[x] = (line[x] + p) & 255
        out[y] = row
        prev = row
    return out.reshape(height, width, channels)[:, :, :3]


TEXTS = """() => {
  const rgba = (c) => {
    const m = /rgba?\\(([\\d.]+), ([\\d.]+), ([\\d.]+)(?:, ([\\d.]+))?\\)/.exec(c);
    return m ? [+m[1], +m[2], +m[3], m[4] === undefined ? 1 : +m[4]] : null;
  };
  // What is behind a text: its own and its ancestors' backgrounds, composited until one is opaque; null when it
  // sits on the page itself (where a skin's textures are), read from the screen instead.
  const behind = (e) => {
    const layers = [];
    for (let a = e; a && a !== document.body && a !== document.documentElement; a = a.parentElement) {
      const c = rgba(getComputedStyle(a).backgroundColor);
      if (c && c[3] > 0) {
        layers.push(c);
        if (c[3] >= 1) break;
      }
    }
    if (!layers.length || layers[layers.length - 1][3] < 1) return null;
    let out = layers.pop().slice(0, 3);
    while (layers.length) {
      const [r, g, b, a] = layers.pop();
      out = [r * a + out[0] * (1 - a), g * a + out[1] * (1 - a), b * a + out[2] * (1 - a)];
    }
    return out.map(Math.round);
  };
  return [...document.querySelectorAll('body *')].flatMap((e) => {
    if (e.closest('.decor, [hidden], .menu, .pop, .style-menu, svg') || e.matches('input, select, textarea, option')) return [];
    if (![...e.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim())) return [];
    const s = getComputedStyle(e);
    let o = 1;
    for (let a = e; a; a = a.parentElement) o *= parseFloat(getComputedStyle(a).opacity);
    if (o < 1 || e.closest(':disabled') || s.visibility === 'hidden') return []; // a control said off on purpose
    const r = e.getBoundingClientRect();
    if (r.width < 4 || r.height < 4 || r.bottom < 0 || r.top > innerHeight - 2 || r.right < 0 || r.left > innerWidth - 2) return [];
    const c = rgba(s.color);
    if (!c || c[3] < 1) return [];
    const large = parseFloat(s.fontSize) >= 24 || (parseFloat(s.fontSize) >= 18.66 && parseInt(s.fontWeight) >= 700);
    return [{ name: e.tagName + '#' + e.id + '.' + String(e.className).trim() + ' "' + e.textContent.trim().slice(0, 24) + '"',
      color: c.slice(0, 3), back: behind(e), large, box: [r.left, r.top, r.right, r.bottom] }];
  });
}"""


def hex_of(c: list[int] | np.ndarray) -> str:
    return "#" + "".join(f"{int(v):02x}" for v in c)


def faint_texts(page: Page) -> list[str]:
    texts = page.evaluate(TEXTS)
    pixels = png_pixels(page.screenshot())
    height, width = pixels.shape[:2]
    bad = []
    for t in texts:
        colour = hex_of(t["color"])
        if t["back"] is not None:
            worst = contrast(colour, hex_of(t["back"]))
        else:  # on the page, over a skin's texture: the pixels around it, the median (a neighbour's letters aside)
            left, top, right, bottom = (int(round(v)) for v in t["box"])
            x0, y0 = max(0, left - 3), max(0, top - 3)
            x1, y1 = min(width - 1, right + 2), min(height - 1, bottom + 2)
            ring = np.concatenate([pixels[y0, x0:x1], pixels[y1, x0:x1], pixels[y0:y1, x0], pixels[y0:y1, x1]])
            if not len(ring):
                continue
            ratios = sorted(contrast(colour, hex_of(p)) for p in ring)
            worst = ratios[len(ratios) // 2]
        floor = 3.0 if t["large"] else 4.5
        if worst < floor - 0.005:
            bad.append(f"{t['name']}: {worst:.2f} < {floor}")
    return bad


# What reads below the floor on main already, in the base, kept as it was (R12): the accent as text on its own tint
# in the light theme, 4.2 (the current step's number, "Nothing to check by ear"). Skins are held to the floor.
FAINT_ALLOWED = {("woodshed", "light"): [r'^SPAN#\.n "Step \d"', r'^SPAN#\.okfact ']}


def accepted(found: list[str], skin: str, theme: str) -> list[str]:
    allowed = FAINT_ALLOWED.get((skin, theme), [])
    return [f for f in found if not any(re.search(a, f) for a in allowed)]


@pytest.mark.parametrize("skin", ["woodshed", *SHIPPED])
@pytest.mark.parametrize("theme", THEMES)
def test_every_text_reads_against_what_is_behind_it(browser: Browser, pages_root: str, skin: str, theme: str) -> None:
    page = song_page(browser, pages_root, theme, None if skin == "woodshed" else skin)
    assert accepted(faint_texts(page), skin, theme) == []
    page.get_by_test_id("stage-open").click()
    page.wait_for_timeout(200)
    assert accepted(faint_texts(page), skin, theme) == []


def test_the_contrast_sweep_catches_a_faint_text(browser: Browser, pages_root: str) -> None:
    page = song_page(browser, pages_root, "dark")
    page.add_style_tag(content="#songTitle { color: #2a3330 !important; }")
    assert any("songTitle" in f for f in faint_texts(page))


def test_the_png_reader_reads_what_the_browser_draws(browser: Browser, pages_root: str) -> None:
    page = song_page(browser, pages_root, "dark")
    page.add_style_tag(content="body::after { content: ''; position: fixed; inset: 0; z-index: 99; background: #12ab34; }")
    pixels = png_pixels(page.screenshot())
    assert hex_of(pixels[450, 720]) == "#12ab34" and pixels.shape == (900, 1440, 3)



@pytest.mark.parametrize("skin", ["woodshed", *SHIPPED])
def test_the_library_follows_the_tokens_and_reads_in_every_skin(
    browser: Browser,
    server: app.AppServer,  # noqa: F811
    skin: str,
) -> None:
    server.library.set_setlist({"title": "Les Imprévus · saison 2026-2027"})
    for theme in THEMES:
        context = browser.new_context(locale="en-US", viewport={"width": 1440, "height": 900}, reduced_motion="reduce")
        context.add_init_script(f"localStorage.setItem('woodshed:theme', '{theme}');")
        context.add_init_script(f"localStorage.setItem('woodshed:skin', '{skin}');")
        page = context.new_page()
        page.goto(server.url)
        page.wait_for_function("window.Woodshed && window.Woodshed.ready === true")
        page.get_by_test_id("set-name").wait_for()
        page.get_by_test_id("drop").locator("summary").click()  # the options for the next songs, open
        page.evaluate("document.fonts.ready")
        assert accepted(faint_texts(page), skin, theme) == []
        if skin == "woodshed":
            assert leaks(fixed_colours(page)) == []
        context.close()
