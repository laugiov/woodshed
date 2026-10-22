"""Write page/assets/js/core/chord-table.js from src/woodshed/chords.json (the page reads no JSON file)."""

import json
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "woodshed"
HEAD = (
    "// Generated from src/woodshed/chords.json (tests/test_chords.py checks they agree): the chord qualities\n"
    "// a musician may type. Regenerate: python3 scripts/chord_table.py\n"
)


def render() -> str:
    table = json.loads((SRC / "chords.json").read_text(encoding="utf-8"))
    body = json.dumps(table, ensure_ascii=False, separators=(",", ":"))
    return HEAD + "window.Woodshed.CHORD_TABLE = " + body + ";\n"


if __name__ == "__main__":
    (SRC / "page" / "assets" / "js" / "core" / "chord-table.js").write_text(render(), encoding="utf-8")
