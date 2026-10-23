"""Draw the boxes a first install meets on a Mac and on Windows, for the install guide.

Drawn in woodshed's own colours, not copied from Apple or Microsoft: plain panels, the message text and the
button labels as the system shows them (English), the button to click outlined with its step number. Real SVG
text, a <title> and a <desc>, no script, no external reference.

    uv run python scripts/draw_warnings.py            # writes docs/images/warnings/*.svg
    uv run python scripts/draw_warnings.py OUT_DIR    # writes them elsewhere (the tests compare)
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from xml.sax.saxutils import escape

OUT = Path(__file__).resolve().parents[1] / "docs" / "images" / "warnings"
MAC = "macOS 15 Sequoia, drawn 2026-10"
WIN = "Windows 11 with Edge, drawn 2026-10"

# The page's dark theme (src/woodshed/page/assets/app.css): the picture carries its own background, so it
# reads the same on a light or a dark page.
BG, PANEL, SHEET, INK, MUTED, LINE = "#0d1210", "#151b18", "#19201d", "#e5ebe7", "#94a19a", "#2a342f"
ACCENT, ACCENT_INK, FRAME, BUTTON = "#3cc4a9", "#0a1210", "#6b7f77", "#222b27"  # FRAME: 3:1 on the panels
FONT = "Atkinson Hyperlegible, sans-serif"

WIDTH, PAD, BOX_PAD = 640, 20, 22
INNER = WIDTH - 2 * PAD - 2 * BOX_PAD


def wrap(text: str, size: float, width: float = INNER, glyph: float = 0.5) -> list[str]:
    """Greedy word wrap on an estimated glyph width (generous, so a wider fallback font still fits)."""
    per_line = max(10, int(width / (glyph * size)))
    lines: list[str] = []
    line = ""
    for word in text.split():
        if line and len(line) + 1 + len(word) > per_line:
            lines.append(line)
            line = word
        else:
            line = f"{line} {word}" if line else word
    return [*lines, line] if line else lines


def text_width(text: str, size: float) -> float:
    return len(text) * 0.6 * size


@dataclass
class Button:
    label: str
    step: str = ""  # the step number when this is the one to click
    link: bool = False  # drawn as a link (underlined text) rather than a button


@dataclass
class Box:
    """One box on screen, top to bottom: a small heading above it, then its parts."""

    above: str = ""
    parts: list[tuple[str, object]] = field(default_factory=list)


@dataclass
class Picture:
    name: str
    system: str
    step: str
    title: str
    desc: str
    caption: str
    boxes: list[Box]


class Canvas:
    def __init__(self) -> None:
        self.out: list[str] = []
        self.y = 0.0

    def text(
        self, x: float, y: float, s: str, size: float = 15, fill: str = INK, weight: str = "", anchor: str = ""
    ) -> None:
        attrs = f' font-weight="{weight}"' if weight else ""
        attrs += f' text-anchor="{anchor}"' if anchor else ""
        self.out.append(f'<text x="{x:g}" y="{y:g}" font-size="{size:g}" fill="{fill}"{attrs}>{escape(s)}</text>')

    def rect(self, x: float, y: float, w: float, h: float, r: float, fill: str, stroke: str, sw: float = 1) -> None:
        self.out.append(
            f'<rect x="{x:g}" y="{y:g}" width="{w:g}" height="{h:g}" rx="{r:g}" fill="{fill}" '
            f'stroke="{stroke}" stroke-width="{sw:g}"/>'
        )

    def badge(self, cx: float, cy: float, step: str) -> None:
        self.out.append(f'<circle cx="{cx:g}" cy="{cy:g}" r="13" fill="{ACCENT}"/>')
        self.text(cx, cy + 5, step, 14, ACCENT_INK, "700", "middle")

    def buttons(self, x0: float, right: float, row: list[Button], align: str) -> None:
        """A row of buttons; the one to click is outlined in the accent colour with its step badge."""
        size, h, gap = 15, 34, 14
        widths = [text_width(b.label, size) + (8 if b.link else 36) for b in row]
        total = sum(widths) + gap * (len(row) - 1)
        x = right - total if align == "right" else x0
        for b, w in zip(row, widths, strict=True):
            top = self.y
            if b.link:
                self.out.append(
                    f'<text x="{x + 4:g}" y="{top + 22:g}" font-size="{size}" fill="{ACCENT if b.step else INK}" '
                    f'font-weight="700" text-decoration="underline">{escape(b.label)}</text>'
                )
            else:
                self.rect(x, top, w, h, 7, BUTTON, FRAME)
                self.text(x + w / 2, top + 22, b.label, size, INK, "700" if b.step else "", "middle")
            if b.step:
                self.rect(x - 5, top - 5, w + 10, h + 10, 10, "none", ACCENT, 3)
                self.badge(x + w + 3, top - 3, b.step)
            x += w + gap
        self.y += h + 12

    def part(self, kind: str, value: object, x0: float, right: float) -> None:
        if kind == "title":
            for line in wrap(str(value), 18, right - x0, 0.58):
                self.y += 24
                self.text(x0, self.y, line, 18, INK, "700")
            self.y += 12
        elif kind in ("text", "muted"):
            for line in wrap(str(value), 14, right - x0):
                self.y += 20
                self.text(x0, self.y, line, 14, INK if kind == "text" else MUTED)
            self.y += 12
        elif kind == "fields":
            assert isinstance(value, list)
            for key, val in value:
                self.y += 21
                self.text(x0, self.y, f"{key}:", 14, MUTED)
                self.text(x0 + 92, self.y, val, 14, INK)
            self.y += 12
        elif kind == "check":
            self.rect(x0, self.y + 2, 14, 14, 3, "none", MUTED, 1.5)
            self.out.append(
                f'<path d="M{x0 + 3:g} {self.y + 9:g}l3 3l5-6" fill="none" stroke="{INK}" stroke-width="1.8"/>'
            )
            self.text(x0 + 24, self.y + 14, str(value), 14, INK)
            self.y += 30
        elif kind == "rule":
            self.out.append(f'<line x1="{x0:g}" y1="{self.y:g}" x2="{right:g}" y2="{self.y:g}" stroke="{LINE}"/>')
            self.y += 10
        elif kind in ("left", "right"):
            assert isinstance(value, list)
            self.y += 14
            self.buttons(x0, right, value, kind)
        elif kind == "menu":
            assert isinstance(value, list)
            for b in value:
                h = 32
                if b.step:
                    self.rect(x0, self.y, right - x0, h, 6, BUTTON, ACCENT, 3)
                    self.badge(right - 2, self.y + 2, b.step)
                self.text(x0 + 14, self.y + 21, b.label, 15, INK, "700" if b.step else "")
                self.y += h + 4
            self.y += 8
        else:
            raise ValueError(kind)


def draw(p: Picture) -> str:
    c = Canvas()
    c.y = PAD + 14
    c.text(PAD, c.y, p.step, 15, ACCENT, "700")
    c.text(WIDTH - PAD, c.y, p.system, 13, MUTED, "", "end")
    c.y += 14
    for box in p.boxes:
        if box.above:
            c.y += 22
            c.text(PAD, c.y, box.above, 13, MUTED)
            c.y += 4
        c.y += 10
        top, mark = c.y, len(c.out)
        c.y += BOX_PAD - 12
        for kind, value in box.parts:
            c.part(kind, value, PAD + BOX_PAD, WIDTH - PAD - BOX_PAD)
        c.y += BOX_PAD - 12
        c.out.insert(  # the box behind what was drawn in it, now that its height is known
            mark,
            f'<rect x="{PAD}" y="{top:g}" width="{WIDTH - 2 * PAD}" height="{c.y - top:g}" rx="12" '
            f'fill="{SHEET}" stroke="{FRAME}" stroke-width="1.5"/>',
        )
    c.y += 8
    for line in wrap(p.caption, 15, WIDTH - 2 * PAD, 0.58):
        c.y += 22
        c.text(PAD, c.y, line, 15, INK, "700")
    height = c.y + PAD
    head = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} {height:g}" width="{WIDTH}" '
        f'height="{height:g}" role="img" aria-labelledby="t d" font-family="{FONT}">\n'
        f'<title id="t">{escape(p.title)}</title>\n<desc id="d">{escape(p.desc)}</desc>\n'
        f'<rect width="{WIDTH}" height="{height:g}" rx="14" fill="{BG}"/>\n'
        f'<rect x="1" y="1" width="{WIDTH - 2}" height="{height - 2:g}" rx="13" fill="{PANEL}" stroke="{FRAME}"/>\n'
    )
    return head + "\n".join(c.out) + "\n</svg>\n"


APP = "“Install woodshed”"
FILE = "woodshed-installer-windows.cmd"

PICTURES = [
    Picture(
        "mac-1-not-opened",
        MAC,
        "Mac, step 1 of 3",
        "Mac, step 1: the “Install woodshed” Not Opened box (drawn)",
        f"A drawn box titled {APP} Not Opened, saying Apple could not verify it is free of malware, with two "
        "buttons, Move to Trash and Done. Done (Terminé) is outlined: click it.",
        "Click Done (Terminé)",
        [
            Box(
                parts=[
                    ("title", f"{APP} Not Opened"),
                    (
                        "text",
                        f"Apple could not verify {APP} is free of malware that may harm your Mac or "
                        "compromise your privacy.",
                    ),
                    ("right", [Button("Move to Trash"), Button("Done", "1")]),
                ]
            )
        ],
    ),
    Picture(
        "mac-2-privacy-security",
        MAC,
        "Mac, step 2 of 3",
        "Mac, step 2: Privacy & Security in System Settings, Open Anyway (drawn)",
        "A drawn settings panel: System Settings, Privacy & Security, scrolled down to Security, where a line "
        f"says {APP} was blocked to protect your Mac, with an Open Anyway (Ouvrir quand même) button, outlined: "
        "click it.",
        "In System Settings, Privacy & Security, scroll down: click Open Anyway (Ouvrir quand même)",
        [
            Box(
                above="System Settings, then Privacy & Security, scrolled down to Security",
                parts=[
                    ("title", "Security"),
                    ("rule", None),
                    ("text", f"{APP} was blocked to protect your Mac."),
                    ("right", [Button("Open Anyway", "2")]),
                ],
            )
        ],
    ),
    Picture(
        "mac-3-open-anyway",
        MAC,
        "Mac, step 3 of 3",
        "Mac, step 3: confirm with Open Anyway, then your password (drawn)",
        f"A drawn box asking whether to open {APP}, saying Apple is not able to verify that it is free from "
        "malware, with the buttons Done and Open Anyway (Ouvrir quand même); Open Anyway is outlined. Then the "
        "Mac asks for your password or Touch ID.",
        "Click Open Anyway (Ouvrir quand même), then type your Mac password or use Touch ID",
        [
            Box(
                parts=[
                    ("title", f"Open {APP}?"),
                    (
                        "text",
                        "Apple is not able to verify that it is free from malware that could harm your Mac or "
                        "compromise your privacy.",
                    ),
                    ("right", [Button("Done"), Button("Open Anyway", "3")]),
                ]
            ),
            Box(
                above="Then:",
                parts=[("muted", "Your Mac asks for your password, or for your finger on Touch ID.")],
            ),
        ],
    ),
    Picture(
        "win-1-edge-keep",
        WIN,
        "Windows, step 1 of 4",
        "Windows, step 1: Edge holds the download back; … then Keep (drawn)",
        f"A drawn Edge downloads list: {FILE} isn't commonly downloaded. The … button (More actions, Plus "
        "d'actions) is outlined as 1a; in the menu it opens, Keep (Conserver) is outlined as 1b.",
        "Click … next to the file (1a), then Keep (Conserver) (1b)",
        [
            Box(
                above="The downloads list, top right of Edge:",
                parts=[
                    ("title", FILE),
                    ("muted", f"{FILE} isn't commonly downloaded. Make sure you trust {FILE} before you open it."),
                    ("right", [Button("…", "1a")]),
                ],
            ),
            Box(
                above="The menu under …:",
                parts=[("menu", [Button("Delete"), Button("Keep", "1b"), Button("Report this file as safe")])],
            ),
        ],
    ),
    Picture(
        "win-2-keep-anyway",
        WIN,
        "Windows, step 2 of 4 (if it appears)",
        "Windows, step 2: Make sure you trust the file; Show more, then Keep anyway (drawn)",
        f"A drawn box: Make sure you trust {FILE} before you open it. Below, Show more (Afficher plus) is "
        "outlined as 2a; it reveals Keep anyway (Conserver quand même), outlined as 2b, and Report this app as "
        "safe. Delete and Cancel are left alone.",
        "Click Show more (Afficher plus) (2a), then Keep anyway (Conserver quand même) (2b)",
        [
            Box(
                parts=[
                    ("title", f"Make sure you trust {FILE} before you open it"),
                    (
                        "muted",
                        "Microsoft Defender SmartScreen couldn't verify if this file is safe because it isn't "
                        "commonly downloaded.",
                    ),
                    ("left", [Button("Show more ⌄", "2a", link=True)]),
                    ("menu", [Button("Keep anyway", "2b"), Button("Report this app as safe")]),
                    ("rule", None),
                    ("right", [Button("Delete"), Button("Cancel")]),
                ]
            )
        ],
    ),
    Picture(
        "win-3-run",
        WIN,
        "Windows, step 3 of 4",
        "Windows, step 3: Open File - Security Warning; Run (drawn)",
        f"A drawn box titled Open File - Security Warning: Do you want to run this file? Name {FILE}, "
        "Publisher Unknown Publisher. Run (Exécuter) is outlined: click it. Cancel is left alone.",
        "When you double-click the file: click Run (Exécuter)",
        [
            Box(
                parts=[
                    ("muted", "Open File - Security Warning"),
                    ("title", "Do you want to run this file?"),
                    (
                        "fields",
                        [
                            ("Name", FILE),
                            ("Publisher", "Unknown Publisher"),
                            ("Type", "Windows Command Script"),
                        ],
                    ),
                    ("right", [Button("Run", "3"), Button("Cancel")]),
                    ("check", "Always ask before opening this file"),
                ]
            )
        ],
    ),
    Picture(
        "win-4-protected",
        WIN,
        "Windows, step 4 of 4 (if it appears)",
        "Windows, step 4: Windows protected your PC; More info, then Run anyway (drawn)",
        "A drawn box titled Windows protected your PC, saying an unrecognized app was prevented from starting. "
        "More info (Informations complémentaires) is outlined as 4a; the box then shows the app and its "
        "publisher, with Run anyway (Exécuter quand même), outlined as 4b, and Don't run.",
        "If it appears: click More info (4a), then Run anyway (Exécuter quand même) (4b)",
        [
            Box(
                parts=[
                    ("title", "Windows protected your PC"),
                    (
                        "text",
                        "Microsoft Defender SmartScreen prevented an unrecognized app from starting. Running this "
                        "app might put your PC at risk.",
                    ),
                    ("left", [Button("More info", "4a", link=True)]),
                    ("right", [Button("Don't run")]),
                ]
            ),
            Box(
                above="After More info:",
                parts=[
                    ("fields", [("App", FILE), ("Publisher", "Unknown publisher")]),
                    ("right", [Button("Run anyway", "4b"), Button("Don't run")]),
                ],
            ),
        ],
    ),
]


def main(argv: list[str]) -> None:
    out = Path(argv[1]) if len(argv) > 1 else OUT
    out.mkdir(parents=True, exist_ok=True)
    for p in PICTURES:
        svg = draw(p)
        (out / f"{p.name}.svg").write_text(svg, encoding="utf-8")
        print(f"{p.name}.svg: {len(svg.encode())} bytes")


if __name__ == "__main__":
    main(sys.argv)
