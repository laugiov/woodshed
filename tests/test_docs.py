"""The docs a musician reads before and after installing: the changelog and where it is linked."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from woodshed import __version__

ROOT = Path(__file__).resolve().parents[1]
CHANGELOG = ROOT / "CHANGELOG.md"
RELEASE = re.compile(r"^## \[(\d+\.\d+\.\d+)\] - (\d{4}-\d{2}-\d{2})$", re.M)


def releases() -> dict[str, str]:
    """The changelog's versions and their dates, as written."""
    return dict(RELEASE.findall(CHANGELOG.read_text(encoding="utf-8")))


def tags() -> dict[str, str]:
    """The release tags and their dates; none in a shallow clone (the CI's checkout)."""
    if shutil.which("git") is None:
        return {}
    out = subprocess.run(
        ["git", "for-each-ref", "--format=%(refname:short) %(creatordate:short)", "refs/tags/v*"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    pairs = (line.split() for line in out.splitlines())
    return {name[1:]: day for name, day in pairs if re.fullmatch(r"v\d+\.\d+\.\d+", name)}


def test_the_changelog_opens_on_what_is_coming_then_the_releases_newest_first() -> None:
    text = CHANGELOG.read_text(encoding="utf-8")
    assert text.startswith("# Changelog\n")
    headings = re.findall(r"^## (.+)$", text, re.M)
    assert headings[0] == "[Unreleased]"
    versions = [tuple(int(n) for n in v.split(".")) for v in releases()]
    assert len(versions) == len(headings) - 1 and versions == sorted(versions, reverse=True)
    assert __version__ in releases()  # the version the library page shows has its notes


def test_every_release_tag_has_its_section_with_the_tag_s_date() -> None:
    tagged = tags()
    if not tagged:
        pytest.skip("no release tags in this clone")
    written = releases()
    assert {v: written.get(v) for v in tagged} == tagged


def test_the_changelog_speaks_to_musicians() -> None:
    text = CHANGELOG.read_text(encoding="utf-8")
    assert "\N{EM DASH}" not in text
    # No internal references: spec or lot numbers, pull requests, issues.
    assert re.findall(r"\b(?:spec|lot|PR) ?\d+|#\d+", text, re.I) == []
    for body in re.split(r"^## .+$", text, flags=re.M)[1:]:
        assert re.search(r"^- ", body, re.M), "each section says what changed, in bullets"


def test_the_readme_links_the_changelog_next_to_install() -> None:
    readme = ROOT / "README.md"
    install = readme.read_text(encoding="utf-8").split("\n## Install\n", 1)[1].split("\n## ", 1)[0]
    assert "](CHANGELOG.md)" in install


def test_contributing_asks_for_a_changelog_line() -> None:
    text = " ".join((ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8").split())
    assert "Unreleased" in text and "CHANGELOG.md" in text
