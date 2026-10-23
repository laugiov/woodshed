"""The drawn first-install warnings in the install guide: safe, small, readable, with the system's labels."""

from __future__ import annotations

import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WARNINGS = ROOT / "docs" / "images" / "warnings"
SVG = "{http://www.w3.org/2000/svg}"

# Each picture and the labels it must show, as the system writes them (English).
LABELS = {
    "mac-1-not-opened": ["“Install woodshed” Not Opened", "Done", "Move to Trash", "macOS 15 Sequoia"],
    "mac-2-privacy-security": ["Privacy & Security", "Open Anyway", "was blocked to protect your Mac."],
    "mac-3-open-anyway": ["Open “Install woodshed”?", "Open Anyway", "Done", "Touch ID"],
    "win-1-edge-keep": ["…", "Keep", "isn't commonly downloaded.", "Windows 11 with Edge"],
    "win-2-keep-anyway": ["Make sure you trust", "Show more", "Keep anyway", "Delete", "Cancel"],
    "win-3-run": ["Open File - Security Warning", "Run", "Cancel"],
    "win-4-protected": ["Windows protected your PC", "More info", "Run anyway", "Don't run"],
}
# The French label goes in brackets for the button to click, where the guide's readers look first.
FRENCH = {
    "mac-1-not-opened": "Terminé",
    "mac-2-privacy-security": "Ouvrir quand même",
    "mac-3-open-anyway": "Ouvrir quand même",
    "win-1-edge-keep": "Conserver",
    "win-2-keep-anyway": "Conserver quand même",
    "win-3-run": "Exécuter",
    "win-4-protected": "Exécuter quand même",
}


def texts(root: ET.Element) -> list[str]:
    return ["".join(t.itertext()) for t in root.iter(f"{SVG}text")]


def test_one_picture_per_step_and_nothing_else() -> None:
    assert sorted(p.stem for p in WARNINGS.glob("*")) == sorted(LABELS)


@pytest.mark.parametrize("name", sorted(LABELS))
def test_each_picture_is_a_safe_small_readable_svg(name: str) -> None:
    path = WARNINGS / f"{name}.svg"
    raw = path.read_bytes()
    assert len(raw) < 20 * 1024
    source = raw.decode("utf-8")
    assert "\N{EM DASH}" not in source
    root = ET.fromstring(source)
    assert root.tag == f"{SVG}svg" and root.get("viewBox") and root.get("role") == "img"
    title, desc = root.find(f"{SVG}title"), root.find(f"{SVG}desc")
    assert title is not None and (title.text or "").strip() and "(drawn)" in (title.text or "")
    assert desc is not None and len((desc.text or "").strip()) > 40
    for el in root.iter():
        tag = el.tag.removeprefix(SVG)
        assert tag not in {"script", "image", "use", "foreignObject", "a", "style"}, tag
        for attr, value in el.attrib.items():
            assert not attr.startswith("on"), attr  # no event handler
            assert not attr.endswith("href"), attr  # nothing fetched, nothing linked
            assert "url(" not in value
    shown = texts(root)
    for label in LABELS[name]:
        assert any(label in t for t in shown), label  # real text, not paths
    assert FRENCH[name] in " ".join(shown) and FRENCH[name] in (desc.text or "")


def test_each_picture_outlines_the_button_to_click_with_its_step() -> None:
    for name in LABELS:
        root = ET.parse(WARNINGS / f"{name}.svg").getroot()
        step = name.split("-")[1]
        badges = [t for t in texts(root) if t.startswith(step) and len(t) <= 2]
        assert badges, name


def test_the_pictures_are_what_the_script_draws(tmp_path: Path) -> None:
    script = ROOT / "scripts" / "draw_warnings.py"
    subprocess.run([sys.executable, str(script), str(tmp_path)], check=True, capture_output=True)
    for name in LABELS:
        assert (tmp_path / f"{name}.svg").read_bytes() == (WARNINGS / f"{name}.svg").read_bytes(), name
