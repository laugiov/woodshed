# Making a skin

A skin changes how woodshed looks: colours, a display font, corners, textures and a few period objects (a
cassette, a CD, a mirror ball). It never changes the layout, the chords' or the words' fonts, the stage view or
the printout. The band picks one from the **Style** menu, per device.

How skins fit in the page: [architecture, section 9](architecture.md#skins).

## In five steps

1. Copy `src/woodshed/page/assets/skins/_template/` to `skins/<id>/` (`<id>`: lowercase letters and digits).
2. In `skin.css`, replace `example` by your id everywhere and set the 13 colours, for the light theme and again
   for the dark one.
3. Add a line to `skins/skins.js` (`{ id, name, description }`, in the menu's order) and one to `skins/skins.css`
   (`@import url("<id>/skin.css") screen;`).
4. Give the name and the description their French in `assets/js/core/i18n-fr.js`.
5. Run the checks; they say what is missing, too faint or out of place:

```bash
uv run pytest tests/test_skins.py                        # the contract, the palette, the fonts, the weight
uv run pytest tests/page/test_skin_sweeps.py -n 3        # every text against what is behind it, every view
uv run pytest tests/page/test_skins.py -n 3              # the menu, the slots, paper, motion
```

## What a skin may write

- **Tokens**, under `:root[data-skin="<id>"], [data-skin-probe="<id>"]` (light) and
  `:root[data-skin="<id>"][data-theme="dark"], :root[data-theme="dark"] [data-skin-probe="<id>"]` (dark). The
  probe selector lets the style menu show the skin's swatch.
- **Decor slots**: `:root[data-skin="<id>"] .decor[data-slot="<slot>"]`, with `[data-playing]`,
  `[data-set-title]`, ` i`, `i:first-child`, `i:last-child`, `::before`, `::after` as needed, and inside
  `@media` queries. Nothing on the page's own classes: the test refuses it.
- `@font-face` and `@keyframes`.

## The tokens

| Token | What it colours or sets |
|---|---|
| `--bg` | the page behind everything |
| `--panel` | panels: the set list, the desk, menus |
| `--sheet` | the chart, buttons, inputs |
| `--dock` | the player at the bottom |
| `--ink`, `--muted` | text, quieter text |
| `--line` | borders |
| `--accent`, `--accent-soft`, `--accent-ink` | the current bar, the choice made, links (also text); its tint; text on it |
| `--warn`, `--warn-soft` | "check by ear"; its tint |
| `--wave` | the waveform |
| `--radius`, `--radius-sm` | panels; buttons and inputs (every other corner is a fraction of these; 24px at most) |
| `--shadow-color`, `--shadow-panel` | shadows and scrims as `r g b`; a panel's shadow |
| `--dock-image`, `--dock-image-size` | the player's background: gradients only |
| `--font-display`, `--display-scale` | titles, section names, the set's name; their size factor (under 1 for a wide font) |
| `--digits`, `--digits-scale` | time and tempo (an LCD font, say); their size factor |

Colours are plain `#rrggbb`. Text must reach 4.5:1 on every surface (7:1 for Spotlight), the accent as well (it
is text too), the waveform no fainter than the base's, and the accent and the warn colour must stay at least 10
apart for colour-blind eyes (both kinds the test simulates). `tests/test_skins.py` computes all of it.

No `url()` in a token: a relative address in a custom property is resolved against the stylesheet that uses it
(`app.css`), not yours. Pictures go in decor slots.

## Decor slots

| Slot | Where | Data for `attr()` |
|---|---|---|
| `page` | the whole page, fixed behind everything: textures | |
| `library-head` | beside the library's title (hidden under 380px) | `data-set-title` |
| `set-head` | beside the set's name | `data-set-title` |
| `welcome` | the empty library's welcome | |
| `song-head` | under the song's title | `data-song-title` |
| `player` | beside the play button (hidden under 600px) | `data-set-title`, `data-song-title` |

Each slot has two empty `<i>` children: with `::before` and `::after`, six boxes to draw in (the cassette's two
reels turn on their own). A data attribute is absent when it would be empty: draw a name's decoration under
`[data-set-title]` only. A name in a slot is decoration (screen readers skip it), so it may be cut with an
ellipsis.

Slots never show on stage, on paper or where a phone has no room. Motion: under `:root[data-skin][data-playing]`
only, `transform` and `opacity` on an image or a flat box, never a gradient repainted each frame; nothing moves
when the system asks for less motion (the base stops it).

A texture in `page` sits behind the panels; keep it away from the controls on small screens (the contrast sweep
measures text against the real pixels, textures included).

## Fonts and pictures

- Fonts: a latin-subset `.woff2` in `skins/_fonts/`, OFL or Apache 2.0, its licence as `LICENSE-<Font>.txt`, its
  hash (and the licence's) in `scripts/vendored.sha256`; `font-display: block`, never a remote address.
- Pictures: SVG beside `skin.css`, drawn for woodshed or under a free licence.
- Weight: every page folder carries a copy of the skins, so one skin's folder stays under 60 KB, `_fonts/` under
  200 KB, all of `skins/` under 450 KB.

## Adding a feature (for every contributor)

Draw with the tokens: `var(--ink)`, `var(--radius-sm)`, `rgb(var(--shadow-color) / 0.2)`, `var(--font-display)`.
A new need is a new token in the base block of `app.css` with a default derived from the others
(`color-mix(in srgb, var(--accent) 30%, var(--panel))`), and a line in `_template/skin.css` (a test checks the
template lists every token). Then every skin, the ones to come included, reaches the feature untouched.
