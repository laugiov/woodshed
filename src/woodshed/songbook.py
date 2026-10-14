"""The songbook index: one page listing every song of a folder, with links to their pages."""

from __future__ import annotations

import html
from pathlib import Path
from typing import Any
from urllib.parse import quote

INDEX = "index.html"
STYLE = """
:root { --bg: #e6eae7; --panel: #f7f9f6; --ink: #14201b; --muted: #5d6b64; --line: #c9d2cc;
        --accent: #0f766e; --warn: #b45309; }
@media (prefers-color-scheme: dark) {
  :root { --bg: #111815; --panel: #18211d; --ink: #e7efe9; --muted: #9aa9a1; --line: #2c3a33;
          --accent: #5eead4; --warn: #fbbf24; }
}
body { margin: 0; background: var(--bg); color: var(--ink); font: 16px/1.5 system-ui, sans-serif; }
main { max-width: 900px; margin: 0 auto; padding: 32px 16px; }
h1 { margin: 0 0 4px; font-size: 32px; } p { color: var(--muted); margin: 0 0 20px; }
table { width: 100%; border-collapse: collapse; background: var(--panel); border-radius: 10px; overflow: hidden; }
th, td { text-align: left; padding: 10px 12px; border-bottom: 1px solid var(--line); }
th { font-size: 12px; text-transform: uppercase; letter-spacing: .06em; color: var(--muted); }
td.num { font-variant-numeric: tabular-nums; } a { color: var(--accent); font-weight: 600; }
.warn { color: var(--warn); } .muted { color: var(--muted); }
@media (max-width: 640px) { .wide { display: none; } }
"""


def _accidentals(name: str) -> str:
    """Ab -> A♭, F# -> F♯: the signs a chart uses."""
    return name[:1] + name[1:2].replace("b", "♭").replace("#", "♯") + name[2:]


def _fmt(seconds: int) -> str:
    return f"{seconds // 60}:{seconds % 60:02d}"


def index_html(title: str, songs: list[dict[str, Any]]) -> str:
    rows = []
    for s in songs:
        link = quote(s["folder"]) + "/index.html"
        doubts = (
            f'<span class="warn">{s["doubts"]} to check</span>' if s["doubts"] else '<span class="muted">none</span>'
        )
        parts = "yes" if s["stems"] else '<span class="muted">mix only</span>'
        rows.append(
            f'<tr><td><a href="{html.escape(link)}">{html.escape(s["title"])}</a></td>'
            f'<td>{html.escape(_accidentals(s["key"]))}</td><td class="num">{s["bpm"]}</td>'
            f'<td class="wide">{s["meter"]}</td>'
            f'<td class="num wide">{_fmt(s["duration"])}</td>'
            f'<td class="wide">{doubts}</td><td class="wide">{parts}</td></tr>'
        )
    count = f"{len(songs)} song" + ("s" if len(songs) != 1 else "")
    return (
        '<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        "<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; style-src 'unsafe-inline'\">"
        f"<title>{html.escape(title)} · woodshed</title><style>{STYLE}</style></head><body><main>"
        f"<h1>{html.escape(title)}</h1><p>{count}, analysed on this computer by woodshed.</p>"
        '<table><thead><tr><th>Song</th><th>Key</th><th>BPM</th><th class="wide">Meter</th>'
        '<th class="wide">Length</th><th class="wide">Chords to check</th>'
        '<th class="wide">Instrument parts</th></tr></thead>'
        f"<tbody>{''.join(rows)}</tbody></table></main></body></html>\n"
    )


def write_index(folder: Path, title: str, songs: list[dict[str, Any]]) -> Path:
    path = folder / INDEX
    path.write_text(index_html(title, songs), encoding="utf-8")
    return path
