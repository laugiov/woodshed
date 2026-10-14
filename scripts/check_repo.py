#!/usr/bin/env python3
"""Repository hygiene guard: nothing private, copyrighted or oversized may be tracked.

Usage: python scripts/check_repo.py [ROOT]
Lists the files git would track (or, outside a git repository, the files not matched by .gitignore)
and exits with status 1 if any rule is broken.
"""

from __future__ import annotations

import fnmatch
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
VENDOR_DIRS = ("src/woodshed/page/assets/vendor", "src/woodshed/page/assets/fonts", "src/woodshed/page/assets/samples")
HOME_PATH = re.compile(r"(/home/[a-z_][a-z0-9_-]*/|/Users/[A-Za-z][^/\s]*/|[A-Za-z]:\\Users\\)")
# Only these files may mention home paths, as examples of what the guard rejects.
HOME_PATH_EXAMPLES = {"scripts/check_repo.py", "tests/test_check_repo.py"}
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


def check(root: Path, files: list[str]) -> list[str]:
    problems: list[str] = []
    for rel in files:
        path = root / rel
        if Path(rel).suffix.lower() in MEDIA:
            problems.append(f"{rel}: audio or video files must not be tracked")
        if rel.split("/")[0] == "private":
            problems.append(f"{rel}: nothing under private/ may be tracked")
        in_vendor = any(rel.startswith(d + "/") for d in VENDOR_DIRS)
        if path.is_file() and path.stat().st_size > MAX_BYTES and not in_vendor:
            problems.append(f"{rel}: file larger than 1 MB")
        if path.is_file() and path.stat().st_size < 2 * MAX_BYTES and rel not in HOME_PATH_EXAMPLES:
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                text = ""
            if HOME_PATH.search(text):
                problems.append(f"{rel}: contains an absolute home path")
    for d in VENDOR_DIRS:
        if any(f.startswith(d + "/") for f in files) and not any(
            f.startswith(d + "/") and Path(f).name.upper().startswith(("LICENSE", "LICENCE", "COPYING", "OFL"))
            for f in files
        ):
            problems.append(f"{d}: vendored files need a licence file next to them")
    return problems


def main(argv: list[str]) -> int:
    root = Path(argv[1]).resolve() if len(argv) > 1 else Path(__file__).resolve().parents[1]
    problems = check(root, list_files(root))
    for p in problems:
        print(f"check_repo: {p}", file=sys.stderr)
    if not problems:
        print(f"check_repo: {len(list_files(root))} files checked, nothing to report")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
