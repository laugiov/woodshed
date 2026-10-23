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


# The front page and the guide (spec 019 R1, R2, R7): short, in a musician's words, every link alive.

README = ROOT / "README.md"
GUIDE = ROOT / "docs" / "guide"
FRONT_PAGE_LINES = 180
# Tool names a musician deciding whether to install would not know: they live in the guide.
BANNED = ("Demucs", "MMS", "ffmpeg", "Rubber Band", "Homebrew", "mkcert", "PyTorch", "uv", "beat_this", "Wav2Vec")
FENCE = re.compile(r"^(`{3,}|~{3,}).*?^\1[ \t]*$", re.M | re.S)
INLINE_CODE = re.compile(r"(`+)(?:(?!\1).)+?\1", re.S)
MD_LINK = re.compile(r"!?\[(?:[^\[\]]|\[[^\]]*\])*\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
HTML_LINK = re.compile(r"\b(?:href|src|srcset)=\"([^\"]+)\"")
HEADING = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$", re.M)
HTML_ANCHOR = re.compile(r"<a\s+(?:id|name)=\"([^\"]+)\"")


def guide_pages() -> list[Path]:
    return sorted(GUIDE.glob("*.md"))


def prose(text: str) -> str:
    """The text as read: fenced and inline code taken out."""
    return INLINE_CODE.sub(" ", FENCE.sub("\n", text))


def slug(heading: str) -> str:
    """GitHub's anchor for a heading: the text as shown, lower case, letters, digits, `-` and `_` kept,
    each space a hyphen."""
    text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", heading)  # a link shows its text
    text = re.sub(r"<[^>]+>", "", text).replace("`", "")
    text = re.sub(r"(\*\*|__|\*)", "", text)
    return re.sub(r"[^\w\- ]", "", text.strip().lower()).replace(" ", "-")


def anchors(page: Path) -> set[str]:
    """Every #anchor a page answers to: its headings (a repeat gets -1, -2...) and its HTML ids."""
    text = page.read_text(encoding="utf-8")
    seen: dict[str, int] = {}
    found = set(HTML_ANCHOR.findall(text))
    for _, heading in HEADING.findall(FENCE.sub("\n", text)):
        base = slug(heading)
        n = seen.get(base, 0)
        seen[base] = n + 1
        found.add(base if n == 0 else f"{base}-{n}")
    return found


def links(page: Path) -> list[str]:
    """The relative links and images of a page (code is not a link)."""
    text = prose(page.read_text(encoding="utf-8"))
    targets = MD_LINK.findall(text) + [t.split()[0] for t in HTML_LINK.findall(text)]
    return [t for t in targets if not re.match(r"[a-z][a-z0-9+.-]*:", t, re.I)]


def broken(page: Path, target: str) -> str | None:
    """Why a link from `page` leads nowhere, or None."""
    path, _, anchor = target.partition("#")
    dest = (page.parent / path).resolve() if path else page
    if not dest.exists():
        return f"{page.relative_to(ROOT)}: {target}: no such file"
    if anchor and dest.suffix == ".md" and anchor not in anchors(dest):
        return f"{page.relative_to(ROOT)}: {target}: no such anchor"
    return None


def test_the_front_page_is_short() -> None:
    lines = README.read_text(encoding="utf-8").count("\n")
    assert lines <= FRONT_PAGE_LINES, f"README.md has {lines} lines: the details go to docs/guide/"


def test_the_front_page_speaks_to_musicians_not_tools() -> None:
    text = prose(README.read_text(encoding="utf-8"))
    found = {w for w in BANNED if re.search(rf"(?<![\w-]){re.escape(w)}(?![\w-])", text, re.I)}
    assert found == set(), f"say it in a musician's words on the front page, the tool in the guide: {found}"


def test_the_front_page_reads_in_the_order_of_a_musician_deciding() -> None:
    headings = re.findall(r"^## (.+)$", README.read_text(encoding="utf-8"), re.M)
    assert headings == [
        "What it does",
        "Install",
        "Find your part",
        "Use it",
        "Privacy",
        "Status",
        "Licence and credits",
        "Development",
    ]
    part = README.read_text(encoding="utf-8").split("\n## Find your part\n", 1)[1].split("\n## ", 1)[0]
    roles = re.findall(r"^\*\*(.+?)\*\*", part, re.M)
    assert roles == ["Singer", "Guitar", "Keys", "Bass", "Drums", "Band leader"]
    for role in ("Keys", "Bass", "Drums"):  # the rough parts say so where they are offered
        line = next(block for block in part.split("\n\n") if block.startswith(f"**{role}**"))
        assert "rough: check by ear" in line


def test_the_guide_has_a_page_for_each_need() -> None:
    names = {p.name for p in guide_pages()}
    assert names == {
        "README.md",
        "install.md",
        "phones.md",
        "singers.md",
        "parts.md",
        "editing.md",
        "exports.md",
        "how-it-works.md",
        "troubleshooting.md",
    }
    index = (GUIDE / "README.md").read_text(encoding="utf-8")
    assert all(f"]({name})" in index for name in names - {"README.md"})


def test_the_warnings_are_folded_per_system_with_a_place_for_each_picture() -> None:
    text = (GUIDE / "install.md").read_text(encoding="utf-8")
    summaries = re.findall(r"<summary>(.+?)</summary>", text)
    assert any("Mac" in s for s in summaries) and any("Windows" in s for s in summaries)
    assert "Open Anyway" in text and "Run anyway" in text and "Keep anyway" in text
    assert text.count("What you will see (drawn)") >= 4  # one spot per box, drawn in 019c


def test_every_link_and_anchor_of_the_front_page_and_the_guide_resolves() -> None:
    pages = [README, *guide_pages()]
    assert len(pages) > 1
    problems = [why for page in pages for target in links(page) if (why := broken(page, target))]
    assert problems == []


def test_the_code_links_into_the_guide_where_the_text_is() -> None:
    """The library footer, the installers and the app's messages point at a guide page that has the anchor."""
    blob = re.compile(r"https://github\.com/laugiov/woodshed(?:/blob/main/([\w./-]+))?#([\w-]+)")
    sources = [*(ROOT / "src").rglob("*.py"), *(ROOT / "scripts").rglob("*.sh"), *(ROOT / "scripts").rglob("*.ps1")]
    found = [(path, m) for path in sources for m in blob.finditer(path.read_text(encoding="utf-8"))]
    assert found, "the library's How to update links the guide"
    for path, m in found:
        target = ROOT / (m.group(1) or "README.md")
        assert m.group(2) in anchors(target), f"{path.relative_to(ROOT)}: {m.group(0)}"


def test_no_em_dash_on_the_front_page_or_in_the_guide() -> None:
    for page in (README, *guide_pages()):
        assert "\N{EM DASH}" not in page.read_text(encoding="utf-8"), page.name


def test_the_anchor_rules_are_github_s() -> None:
    assert slug("With Docker: Windows, macOS or Linux") == "with-docker-windows-macos-or-linux"
    assert slug("The first time: your computer's warnings") == "the-first-time-your-computers-warnings"
    assert slug("Bass (rough: check by ear)") == "bass-rough-check-by-ear"
    assert slug("Listen to: `your part` **alone**") == "listen-to-your-part-alone"
    assert slug("Où est l'été") == "où-est-lété"
