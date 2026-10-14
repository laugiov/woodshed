"""Build the practice page: one folder that opens from disk, with nothing loaded from the network."""

from __future__ import annotations

import html
import json
import os
import re
import shutil
import tempfile
from importlib import resources
from pathlib import Path
from typing import Any

from woodshed import exports
from woodshed import song as song_json
from woodshed import tracks as track_files
from woodshed.errors import WoodshedError
from woodshed.model import Song
from woodshed.stems import Stems
from woodshed.view import view

FOLDER_SUFFIX = ".woodshed"
# Characters that are not allowed in file names on Windows, macOS or Linux, and control characters.
UNSAFE_NAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
# In a <script> element, "</script>" or "<!--" in a string would end or change the element: escaped
# as JSON unicode escapes, which JSON.parse reads back unchanged. U+2028 and U+2029 are escaped too.
PLACEHOLDER = re.compile(r"\{\{(TITLE|DATA|BODY)\}\}")
SCRIPT_ESCAPES = {"<": "\\u003c", ">": "\\u003e", "&": "\\u0026", "\u2028": "\\u2028", "\u2029": "\\u2029"}


LONE_SURROGATE = re.compile("[\ud800-\udfff]")
MAX_NAME_BYTES = 200  # file names are limited to 255 bytes; room is left for the suffix and temp names
WINDOWS_DEVICES = re.compile(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(\..*)?$", re.IGNORECASE)


def _clean_text(text: str) -> str:
    """Lone surrogates (undecodable bytes in a file name) cannot be written as UTF-8: replaced."""
    return LONE_SURROGATE.sub("\ufffd", text)


def folder_name(title: str) -> str:
    """A file-system-safe folder name for a song title, on Windows, macOS and Linux."""
    name = UNSAFE_NAME.sub("_", _clean_text(title)).strip(" .")
    encoded = name.encode("utf-8")[:MAX_NAME_BYTES]
    name = encoded.decode("utf-8", "ignore").strip(" .")  # never cut a character in half
    if WINDOWS_DEVICES.match(name):
        name = "_" + name
    return (name or "song") + FOLDER_SUFFIX


def script_json(data: dict[str, Any]) -> str:
    """JSON that is safe to place inside a <script type="application/json"> element."""
    text = _clean_text(json.dumps(data, ensure_ascii=False, separators=(",", ":"), allow_nan=False))
    return re.sub("[<>&\u2028\u2029]", lambda m: SCRIPT_ESCAPES[m.group(0)], text)


def page_html(song: Song, data: dict[str, Any]) -> str:
    page = resources.files("woodshed").joinpath("page")
    template = page.joinpath("template.html").read_text(encoding="utf-8")
    body = page.joinpath("body.html").read_text(encoding="utf-8")
    values = {"TITLE": html.escape(_clean_text(song.title)), "DATA": script_json(data), "BODY": body}
    # One pass: a placeholder inside the song's own text (a title "{{BODY}}") is never expanded.
    return PLACEHOLDER.sub(lambda m: values[m.group(1)], template)


def _readable(folder: Path) -> None:
    """mkdtemp makes a private folder (0700): give the page the usual permissions, so it can be
    served (Docker, a web server) or opened by another user."""
    umask = os.umask(0)
    os.umask(umask)
    for path in [folder, *folder.rglob("*")]:
        path.chmod((0o777 if path.is_dir() else 0o666) & ~umask)


def build(
    song: Song,
    source: str | Path,
    out_dir: str | Path,
    stems: Stems | None = None,
    pending_seconds: float | None = None,
) -> Path:
    """Write the page folder for `song` into `out_dir` and return its path.

    The folder is assembled next to its final place and renamed in one step: an interrupted build
    never leaves a half-written page, and a rebuild replaces the previous one.
    """
    target = Path(out_dir) / folder_name(song.title)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix=f".{target.name}.", dir=target.parent))
    try:
        with resources.as_file(resources.files("woodshed").joinpath("page").joinpath("assets")) as assets:
            shutil.copytree(assets, tmp / "assets")
        tracks = track_files.write_tracks(Path(source), stems, tmp)
        # Cleaned once, at the source: the page and every export get valid UTF-8 text.
        song_data = json.loads(_clean_text(json.dumps(song_json.to_json(song), ensure_ascii=False)))
        written = [f"exports/{p.name}" for p in exports.write_all(song_data, tmp / "exports")]
        data = {"song": song_data, "view": view(song, tracks, pending_seconds, written)}
        (tmp / "index.html").write_text(page_html(song, data), encoding="utf-8")
        _readable(tmp)
        try:
            if target.exists():
                old = target.with_name(f".{target.name}.old")
                shutil.rmtree(old, ignore_errors=True)
                target.replace(old)
                shutil.rmtree(old, ignore_errors=True)
            tmp.replace(target)
        except OSError as exc:  # on Windows, a page open in a browser holds its audio files
            raise WoodshedError(
                f"could not replace {target}: close the page in your browser and try again ({exc})"
            ) from exc
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return target
