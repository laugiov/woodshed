#!/usr/bin/env python3
"""Check that a built wheel ships exactly the package: code, schema, page and every licence.

Usage: python scripts/check_wheel.py dist/woodshed-*.whl
Compares the wheel with the files git tracks under src/woodshed, so a page asset or a licence
dropped by the build configuration (an over-broad ignore pattern, say) fails the build.
"""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_repo import list_files

PACKAGE = "src/"
REQUIRED = (
    "woodshed/song.schema.json",
    "woodshed/view.schema.json",
    "woodshed/shapes.json",
    "woodshed/chords.json",
    "woodshed/page/template.html",
    "woodshed/page/body.html",
    "woodshed/py.typed",
)


def expected(root: Path) -> set[str]:
    return {f.removeprefix(PACKAGE) for f in list_files(root) if f.startswith(PACKAGE + "woodshed/")}


def problems(wheel: Path, root: Path) -> list[str]:
    with zipfile.ZipFile(wheel) as zf:
        shipped = {n for n in zf.namelist() if not n.startswith("woodshed-") and not n.endswith("/")}
    want = expected(root)
    out = [f"{name}: missing from the wheel" for name in sorted(want - shipped)]
    out += [f"{name}: in the wheel but not in the source tree" for name in sorted(shipped - want)]
    out += [f"{name}: required file missing" for name in REQUIRED if name not in shipped]
    return out


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    root = Path(__file__).resolve().parents[1]
    found = problems(Path(argv[1]), root)
    for p in found:
        print(f"check_wheel: {p}", file=sys.stderr)
    if not found:
        print(f"check_wheel: {len(expected(root))} files, as in the source tree")
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
