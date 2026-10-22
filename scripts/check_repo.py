#!/usr/bin/env python3
"""Repository hygiene guard: nothing private, copyrighted or oversized may be tracked.

Usage: python scripts/check_repo.py [ROOT] [--pin-vendored]
Lists the files git would track (or, outside a git repository, the files not matched by .gitignore)
and exits with status 1 if any rule is broken.
"""

from __future__ import annotations

import fnmatch
import hashlib
import re
import subprocess
import sys
from pathlib import Path

MEDIA = {
    ".wav",
    ".mp3",
    ".flac",
    ".ogg",
    ".oga",
    ".opus",
    ".m4a",
    ".aac",
    ".aif",
    ".aiff",
    ".wma",
    ".mp4",
    ".m4v",
    ".mov",
    ".mkv",
    ".webm",
    ".avi",
}
MAX_BYTES = 1024 * 1024
# Vendored assets may exceed the size limit, but only inside these folders, which need a licence file.
FONTS_DIR = "src/woodshed/page/assets/fonts"
# The demo song (a free-licence recording, so that a clone has a song to try) is the one place audio
# may be tracked: like a vendored file, it needs its licence next to it and is pinned by hash.
DEMO_DIR = "demo"
# The two tiny videos that keep a phone awake (core/awake.js): black frames without sound, made here by
# scripts/awake_video.py; the only video the repository holds, by name, with its licence, pinned by hash.
AWAKE_DIR = "src/woodshed/page/assets/awake"
AWAKE_VIDEOS = {f"{AWAKE_DIR}/awake.mp4", f"{AWAKE_DIR}/awake.webm"}
VENDOR_DIRS = (
    AWAKE_DIR,
    "src/woodshed/page/assets/vendor",
    "src/woodshed/page/assets/fonts",
    "src/woodshed/page/assets/samples",
    "src/woodshed/page/library-vendor",
    DEMO_DIR,
)
HOME_PATH = re.compile(
    # /root/ only where a path starts ("src/root/" and "https://x/root/" are not home folders);
    # the others anywhere, URLs included (file:///home/alice/, ssh://host/home/bob/).
    r"(/home/[a-z_][a-z0-9_-]*/|/var/home/[a-z_][a-z0-9_-]*/|(?<![\w.-])/root/|/Users/[A-Za-z][^/\s]*/"
    r"|[A-Za-z]:[\\/]Users[\\/])"
)
SECRET = re.compile(
    r"(AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{22,}|xox[abprs]-[A-Za-z0-9-]{10,}"
    r"|hf_[A-Za-z0-9]{30,}|npm_[A-Za-z0-9]{36}|(?<![A-Za-z0-9-])sk-(?:proj-|ant-)?[A-Za-z0-9_-]{32,}"
    r"|eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"  # a JSON Web Token
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----)"
)
# Only these files may contain such patterns, as examples of what the guard rejects.
PATTERN_EXAMPLES = {"scripts/check_repo.py", "tests/test_check_repo.py"}
# The practice page works offline: its own code never loads anything from the network.
PAGE_DIR = "src/woodshed/page"
PAGE_CODE = {".js", ".html", ".css"}
URL = re.compile(
    r"(?:https?|wss?|ftp)://(?!www\.w3\.org/|www\.musicxml\.org/dtds/partwise\.dtd[\"'])"
    r"|(?<![:\w])//[a-z0-9.-]+\.[a-z]{2,}/",
    re.IGNORECASE,
)
# XML namespaces (SVG, XHTML) and the MusicXML DOCTYPE are identifiers, never fetched.
# Vendored files are pinned by hash: an update is a reviewed change, and nothing (audio hidden in
# base64, for one) can slip into these folders unnoticed.
VENDOR_MANIFEST = "scripts/vendored.sha256"
ALWAYS_SKIPPED = {
    ".git",
    ".venv",
    ".venvs",
    "__pycache__",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    "dist",
    "build",
}


def _git_files(root: Path) -> list[str] | None:
    try:
        out = subprocess.run(
            ["git", "ls-files", "-co", "--exclude-standard"], cwd=root, capture_output=True, text=True, check=True
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return [line for line in out.stdout.splitlines() if line]


def _ignore_patterns(root: Path) -> list[str]:
    gi = root / ".gitignore"
    if not gi.exists():
        return []
    lines = (ln.strip() for ln in gi.read_text(encoding="utf-8").splitlines())
    return [ln for ln in lines if ln and not ln.startswith("#")]


def _ignored(rel: str, patterns: list[str]) -> bool:
    parts = rel.split("/")
    for pat in patterns:
        pat = pat.lstrip("/")
        if pat.endswith("/"):
            if pat.rstrip("/") in parts[:-1]:
                return True
        elif fnmatch.fnmatch(parts[-1], pat) or fnmatch.fnmatch(rel, pat):
            return True
    return False


def list_files(root: Path) -> list[str]:
    """Files that would be published: git's view when available, else .gitignore applied by hand."""
    if (root / ".git").exists():
        files = _git_files(root)
        if files is not None:
            return files
    patterns = _ignore_patterns(root)
    out = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if ALWAYS_SKIPPED.intersection(rel.split("/")[:-1]) or _ignored(rel, patterns):
            continue
        out.append(rel)
    return out


def _vendored(rel: str) -> bool:
    return any(rel.startswith(d + "/") for d in VENDOR_DIRS)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def vendor_manifest(root: Path, files: list[str]) -> str:
    return "".join(f"{sha256(root / rel)}  {rel}\n" for rel in sorted(files) if _vendored(rel))


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return ""


def _file_problems(root: Path, rel: str) -> list[str]:
    path, problems = root / rel, []
    if Path(rel).suffix.lower() in MEDIA and not rel.startswith(DEMO_DIR + "/") and rel not in AWAKE_VIDEOS:
        problems.append(f"{rel}: audio or video files must not be tracked")
    if rel.split("/")[0] == "private":
        problems.append(f"{rel}: nothing under private/ may be tracked")
    if not path.is_file():
        return problems
    size = path.stat().st_size
    if size > MAX_BYTES and not _vendored(rel):
        problems.append(f"{rel}: file larger than 1 MB")
    if size < 2 * MAX_BYTES and rel not in PATTERN_EXAMPLES:
        text = _read_text(path)
        if HOME_PATH.search(text):
            problems.append(f"{rel}: contains an absolute home path")
        if SECRET.search(text):
            problems.append(f"{rel}: contains what looks like a secret (token or private key)")
        if rel.startswith(PAGE_DIR + "/") and Path(rel).suffix in PAGE_CODE and not _vendored(rel) and URL.search(text):
            problems.append(f"{rel}: page code must not reference the network (the page works offline)")
    return problems


def _family(font: str) -> str:
    """'JetBrainsMono-latin.woff2' -> 'jetbrainsmono'; 'Inter.woff2' -> 'inter'."""
    return Path(font).stem.split("-")[0].lower()


def _font_licence_problems(files: list[str]) -> list[str]:
    """Each font family needs its own licence (OFL-<family>.txt), not just any licence in the folder."""
    fonts = [f for f in files if f.startswith(FONTS_DIR + "/") and f.endswith((".woff2", ".woff", ".ttf", ".otf"))]
    licences = {Path(f).stem.lower() for f in files if f.startswith(FONTS_DIR + "/OFL-")}
    return [
        f"{f}: no licence file OFL-{_family(f)}.txt for this font family"
        for f in fonts
        if f"ofl-{_family(f)}" not in licences
    ]


def _vendor_problems(root: Path, files: list[str]) -> list[str]:
    problems = []
    for d in VENDOR_DIRS:
        if any(f.startswith(d + "/") for f in files) and not any(
            f.startswith(d + "/") and Path(f).name.upper().startswith(("LICENSE", "LICENCE", "COPYING", "OFL"))
            for f in files
        ):
            problems.append(f"{d}: vendored files need a licence file next to them")
    problems += _font_licence_problems(files)
    manifest = root / VENDOR_MANIFEST
    pinned = {}
    if manifest.is_file():
        for line in manifest.read_text(encoding="utf-8").splitlines():
            digest, _, rel = line.partition("  ")
            pinned[rel] = digest
    for rel in sorted(f for f in files if _vendored(f)):
        if rel not in pinned:
            problems.append(f"{rel}: vendored file missing from {VENDOR_MANIFEST}")
        elif (root / rel).is_file() and sha256(root / rel) != pinned[rel]:
            problems.append(f"{rel}: content differs from its hash in {VENDOR_MANIFEST}")
    for rel in sorted(set(pinned) - set(files)):
        problems.append(f"{rel}: listed in {VENDOR_MANIFEST} but not present")
    return problems


def check(root: Path, files: list[str]) -> list[str]:
    problems = [p for rel in files for p in _file_problems(root, rel)]
    return problems + _vendor_problems(root, files)


def main(argv: list[str]) -> int:
    args = [a for a in argv[1:] if not a.startswith("--")]
    root = Path(args[0]).resolve() if args else Path(__file__).resolve().parents[1]
    if "--pin-vendored" in argv:  # after a reviewed update of a vendored file
        manifest = root / VENDOR_MANIFEST
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(vendor_manifest(root, list_files(root)), encoding="utf-8")
        print(f"check_repo: wrote {VENDOR_MANIFEST}")
    problems = check(root, list_files(root))
    for p in problems:
        print(f"check_repo: {p}", file=sys.stderr)
    if not problems:
        print(f"check_repo: {len(list_files(root))} files checked, nothing to report")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
