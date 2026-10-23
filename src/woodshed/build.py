"""Build the practice page: one folder that opens from disk, with nothing loaded from the network."""

from __future__ import annotations

import contextlib
import functools
import hashlib
import html
import json
import math
import os
import re
import shutil
import tempfile
import time
from importlib import resources
from pathlib import Path
from typing import Any

from woodshed import exports, theory
from woodshed import song as song_json
from woodshed import tracks as track_files
from woodshed.errors import WoodshedError
from woodshed.model import KeyRegion, Song
from woodshed.stems import Stems
from woodshed.view import VIEW_VERSION, view, view_region

FOLDER_SUFFIX = ".woodshed"
# Characters that are not allowed in file names on Windows, macOS or Linux, and control characters.
UNSAFE_NAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
# In a <script> element, "</script>" or "<!--" in a string would end or change the element: escaped
# as JSON unicode escapes, which JSON.parse reads back unchanged. U+2028 and U+2029 are escaped too.
PLACEHOLDER = re.compile(r"\{\{(TITLE|DATA|BODY)\}\}")
SCRIPT_ESCAPES = {"<": "\\u003c", ">": "\\u003e", "&": "\\u0026", "\u2028": "\\u2028", "\u2029": "\\u2029"}
DATA_BLOCK = re.compile(r'<script type="application/json" id="woodshed-data">(.*?)</script>', re.S)


LONE_SURROGATE = re.compile("[\ud800-\udfff]")
MAX_NAME_BYTES = 200  # file names are limited to 255 bytes; room is left for the suffix and temp names
WINDOWS_DEVICES = re.compile(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(\..*)?$", re.IGNORECASE)


def _shipped(rel: Path) -> bool:
    """A file of the page, not one a system or an editor leaves around (.DS_Store, backups, caches)."""
    return not any(part.startswith(".") or part == "__pycache__" for part in rel.parts) and not rel.name.endswith("~")


@functools.cache
def page_revision(folder: Path | None = None) -> str:
    """A fingerprint of the page's own code (template, scripts, styles, fonts, samples): a page built
    with other code is rebuilt, even when woodshed's version number is the same (an update from git)."""
    if folder is None:
        with resources.as_file(resources.files("woodshed").joinpath("page")) as page:
            return page_revision(Path(page))
    digest = hashlib.sha256()
    for path in sorted(p for p in folder.rglob("*") if p.is_file() and _shipped(p.relative_to(folder))):
        digest.update(path.relative_to(folder).as_posix().encode() + b"\0")
        digest.update(path.read_bytes())
    return digest.hexdigest()[:16]


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
    return _page_html(song.title, data)


def _page_html(title: str, data: dict[str, Any]) -> str:
    page = resources.files("woodshed").joinpath("page")
    template = page.joinpath("template.html").read_text(encoding="utf-8")
    body = page.joinpath("body.html").read_text(encoding="utf-8")
    values = {"TITLE": html.escape(_clean_text(title)), "DATA": script_json(data), "BODY": body}
    # One pass: a placeholder inside the song's own text (a title "{{BODY}}") is never expanded.
    return PLACEHOLDER.sub(lambda m: values[m.group(1)], template)


def _keep_lyrics(old: Path, new: Path, song_data: dict[str, Any], source: Path) -> None:
    """The words placed on a page survive a rebuild: the words keep their times, the chords of the
    new analysis are placed on them again. A page rebuilt from another recording (a remaster, a
    live take of the same title) keeps the text only, as lyrics.previous.json: its times belong to
    the other recording. Without words, an empty lyrics.js (the page loads it)."""
    from woodshed import lyrics, stems

    empty = "window.WOODSHED_LYRICS = null;\n"
    try:
        previous = old / "lyrics.previous.json"
        if not (old / lyrics.LYRICS).exists() and previous.exists():  # words set aside stay set aside
            shutil.copyfile(previous, new / previous.name)
        data = json.loads((old / lyrics.LYRICS).read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("version") != 1:
            raise ValueError("lyrics from another version")
        try:  # the manifest says which recording the old page was built from
            before = json.loads((old / "woodshed.json").read_text(encoding="utf-8"))["settings"]["source"]
        except (OSError, ValueError, KeyError, TypeError):
            before = None  # a page built without the command: taken as the same recording
        if before is not None and before != stems.fingerprint(source):
            (new / "lyrics.previous.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            (new / lyrics.LYRICS_JS).write_text(empty, encoding="utf-8")
            return

        def timed(w: dict[str, Any]) -> bool:  # as the page reads a word: a start and an end
            return isinstance(w.get("start"), (int, float)) and isinstance(w.get("end"), (int, float))

        words = {
            li: [(w["start"], w["end"]) if timed(w) else (math.nan, math.nan) for w in line["words"]]
            for li, line in enumerate(data["lines"])
            if line["sung"] and any(timed(w) for w in line["words"])
        }
        data["chords"] = lyrics.place_chords(
            lyrics.chord_changes(song_data), words, float(song_data["bpm"]), int(song_data["beats_per_bar"])
        )
        named = lyrics.sections_by_words(song_data, data)  # the new chart's parts, named by the words
        if named is None:
            data.pop("sections", None)
        else:
            data["sections"] = named
        lyrics.write(new, data)
    except (OSError, ValueError, KeyError, TypeError, AttributeError):  # none, damaged, edited by hand
        (new / lyrics.LYRICS).unlink(missing_ok=True)
        (new / lyrics.LYRICS_JS).write_text(empty, encoding="utf-8")
        return
    # The songbook file with the words; the words are kept whatever happens to it.
    with contextlib.suppress(OSError, ValueError, KeyError, TypeError, AttributeError):
        exports.write_chordpro(song_data, new / "exports", data)


def upgraded(data: dict[str, Any]) -> dict[str, Any]:
    """A page's data from the format before, brought to this one when nothing needs analysing again: a page made
    before key changes (song 2, view 1) is in one key, its own (spec 012)."""
    song, view = data["song"], data["view"]
    if song.get("schema_version") == 2 and view.get("view_version") == 1:
        key = theory.Key(int(song["key"]["pc"]), song["key"]["mode"])
        song = {**song, "schema_version": 3, "key_regions": [{"bar": 0, "pc": key.tonic, "mode": key.mode}]}
        view = {**view, "view_version": 2, "regions": [view_region(KeyRegion(0, key))]}
        return {**data, "song": song, "view": view}
    return data


def refresh_code(page: Path) -> bool:
    """This version's page code on a page's own data, in place: after an update of woodshed, a
    second instead of a new analysis. False when the data was written for another version of the
    page (its song or view format changed): then the page needs a rebuild. The words keep the chords
    placed when they were placed: a rebuild places them again, a refresh does not."""
    try:
        found = DATA_BLOCK.search((page / "index.html").read_text(encoding="utf-8"))
        data = json.loads(found.group(1)) if found else None
        if not isinstance(data, dict):
            return False
        title = str(data["song"]["title"])
        data = upgraded(data)
        if data["song"]["schema_version"] != song_json.SCHEMA_VERSION or data["view"]["view_version"] != VIEW_VERSION:
            return False
    except (OSError, ValueError, KeyError, TypeError):
        return False
    for leftover in page.glob(".refresh.*"):  # cut short by a crash, an hour ago or more
        with contextlib.suppress(OSError):
            if time.time() - leftover.stat().st_mtime > 3600:
                shutil.rmtree(leftover, ignore_errors=True)
    fresh: Path | None = None
    try:
        fresh = Path(tempfile.mkdtemp(prefix=".refresh.", dir=page))  # its own: two refreshes never mix
        old = fresh / "old-assets"
        with resources.as_file(resources.files("woodshed").joinpath("page").joinpath("assets")) as assets:
            shutil.copytree(assets, fresh / "assets")
        (fresh / "index.html").write_text(_page_html(title, data), encoding="utf-8")
        _readable(fresh)
        done = False
        try:
            if (page / "assets").exists():
                (page / "assets").replace(old)
            (fresh / "assets").replace(page / "assets")
            (fresh / "index.html").replace(page / "index.html")  # last, in one step: the data is in it
            done = True
        finally:
            if not done and old.exists():  # a failure or a Ctrl-C half way: its own code with its own index
                try:
                    if (page / "assets").exists():
                        (page / "assets").replace(fresh / "new-assets")
                    old.replace(page / "assets")
                except BaseException:
                    keep = fresh
                    fresh = None  # its old code stays in the temp folder, never deleted
                    raise WoodshedError(
                        f"{page.name}: its page code is in {keep.name}: rename it back to assets"
                    ) from None
    except OSError as exc:  # on Windows, a page open in a browser may hold its files
        raise WoodshedError(
            f"could not update {page.name}: close the page in your browser and try again ({exc})"
        ) from exc
    finally:
        if fresh is not None:
            shutil.rmtree(fresh, ignore_errors=True)
    return True


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
        _keep_lyrics(target, tmp, song_data, Path(source))
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
