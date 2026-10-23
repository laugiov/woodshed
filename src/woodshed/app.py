"""`woodshed app`: a home page for a library of songs, and an upload that runs the processing.

A small HTTP server on this computer (standard library only). The song pages are the same as the
command line makes; the app lists them, serves them, and turns uploaded files into new pages.

Security: the server answers any page the browser opens, so it trusts nothing it did not give
out itself. It binds 127.0.0.1 by default, refuses a Host header that is not its own (DNS
rebinding), needs a per-run token in a custom header for every upload (a cross-site form or
fetch cannot send it, and preflights are refused), and never reads or writes outside the library.
The band's phones reach it only when this computer opens the door: `--host 0.0.0.0`, or the switch
on the library page, which only this computer may use and which adds a listener on this computer's
network address (closed again, it drops the phones still connected).
"""

from __future__ import annotations

import contextlib
import errno
import http.client
import ipaddress
import json
import math
import mimetypes
import os
import queue
import re
import secrets
import shutil
import signal
import socket
import socketserver
import ssl
import sys
import threading
import time
import traceback
from collections.abc import Callable
from dataclasses import asdict, dataclass, field, replace
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

from woodshed import __version__, audio, build, lyrics, pitch, stems
from woodshed import chords as chord_grammar
from woodshed.build import DATA_BLOCK, folder_name, page_revision
from woodshed.cache import cache_dir
from woodshed.errors import WoodshedError
from woodshed.run import (
    EXTRA_HINT,
    MANIFEST,
    Options,
    Reporter,
    first_pass,
    media_files,
    new_page_model,
    second_pass,
    stems_extra_installed,
    update_page_code,
)
from woodshed.tls import Tls

MAX_UPLOAD = 2 * 1024**3  # 2 GB: a long video
FREE_MARGIN = 2 * 1024**3  # room left for the page's tracks after an upload
CHUNK = 1024 * 1024
TOKEN_HEADER = "X-Woodshed-Token"
LEADER_GONE = 10.0  # seconds without a word from a playing leader (it says where it is every second)
LOOPBACK = {"127.0.0.1", "localhost", "::1"}
SETLIST = "setlist.json"  # in the library: the order the band plays the songs in
SETLIST_MAX = 500
SETLIST_BYTES = 256 * 1024  # 500 long titles
CORRECTIONS_MAX = 2000  # chords picked by ear on one page: more than any song has doubts
CORRECTIONS_BYTES = 64 * 1024
WORDS_BYTES = 32 * 1024  # the pasted words of one song: a long song is 3 KB
DRAIN_MAX = 1024 * 1024  # a body a little too big is read before the refusal, a huge one is not
QUALITIES = ("", "m", "7", "m7")
CORRECTIONS_DIR = ".corrections"  # in the library: one file per page, never served
CORRECTIONS_KEYS = 8  # analyses of one song kept (each rebuild with a new analysis is one)
NOTE_MAX = 300  # the leader's note on a song: "capo 2, starts on the chorus"
DOUBT_ID = re.compile(r"[A-Za-z0-9_-]{1,32}")
# The band's typed chords and part names (core/edits.js), by the beat they start on.
EDITS_BARS_MAX = 1000
EDITS_PARTS_MAX = 200
EDIT_CHORDS_MAX = 64  # chords in one typed bar
LABEL_MAX = 24
PART_NAME_MAX = 40  # code points
BEAT_INDEX = re.compile(r"0|-?[1-9][0-9]{0,5}")  # one spelling a beat: no 007, no -0
UNSAFE = re.compile("[\x00-\x1f\x7f\u202a-\u202e\u2066-\u2069]")  # control and direction overrides
KEY_NAME = re.compile(r"[A-G][#b]?m?")  # a key as the page names it, written by the device that chose it
TYPES = {
    ".flac": "audio/flac",
    ".woff2": "font/woff2",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".html": "text/html; charset=utf-8",
    ".json": "application/json",
    ".mid": "audio/midi",
    ".musicxml": "application/vnd.recordare.musicxml+xml",
    ".cho": "text/plain; charset=utf-8",
    ".lab": "text/plain; charset=utf-8",
    ".mp4": "video/mp4",  # the tiny videos that keep a phone awake (core/awake.js)
    ".webm": "video/webm",
}


@dataclass
class Job:
    id: str
    name: str
    status: str = "queued"  # queued, analysing, separating, placing (the words), done, failed
    step: str = ""
    percent: int = 0
    message: str = ""
    page: str | None = None  # the page folder, as soon as a first page exists
    started: float = field(default_factory=time.time)
    # song (an analysis), words (lyrics placed on a page), bars (the bar lines moved), voice (spec 024, not listed)
    kind: str = "song"
    ended: float | None = None  # done or failed: shown a while after this, not after it started
    notes: list[str] = field(default_factory=list)  # what the user should know about the result


class JobReporter(Reporter):
    """Progress of one job, kept for the home page instead of printed."""

    def __init__(self, job: Job) -> None:
        super().__init__()
        self.job = job

    def say(self, text: str) -> None:
        self.job.message = text.strip()

    def progress(self, step: str, fraction: float) -> None:
        self.job.step = step

    def stems(self, fraction: float) -> None:
        self.job.status = "separating"
        self.job.percent = int(fraction * 100)


class Library:
    """A folder of songs: uploads in `songs/`, one page folder per song next to it."""

    def __init__(self, root: Path, opts: Options) -> None:
        self.root = root.expanduser().resolve()
        self.songs = self.root / "songs"
        self.songs.mkdir(parents=True, exist_ok=True)
        self.opts = opts
        self.jobs: dict[str, Job] = {}
        self.reserved: set[str] = set()
        self.running: Path | None = None
        self.measuring: Path | None = None  # a page whose voice range per key is measured (spec 024)
        self.stopping = threading.Event()  # set by interrupted(): the worker takes no new job, records no failure
        # Analyses and words share one queue: one heavy job at a time. Words carry their text.
        self.queue: queue.Queue[tuple[Job, Path, Options, bool, str | None]] = queue.Queue()
        self.lock = threading.Lock()
        self.revisions: dict[str, int] = {}  # page folder -> how many times its corrections changed
        self.stale: set[str] = set()  # pages the start could not give this version's code (update_pages)
        self.page_songs: dict[str, tuple[int, dict[str, Any] | None]] = {}  # folder -> (index.html stamp, song)
        self.on_bars: Callable[[str], None] | None = None  # told when a page's bar lines moved (Live.bars_moved)
        self.on_band: Callable[[str, int], None] | None = None  # told when band choices changed (Live.corrected)
        self.on_reload: Callable[[str], None] | None = None  # told when a page's data changed (Live.page_updated)
        # The recording in another key (spec 007): rendered one track at a time, never during an analysis.
        self.renders = (
            pitch.Renders(self.root, busy=self.busy, free_margin=FREE_MARGIN)
            if opts.pitch and pitch.tool() is not None
            else None
        )
        threading.Thread(target=self._work, name="woodshed-jobs", daemon=True).start()

    def pages(self) -> list[dict[str, Any]]:
        out = []
        for manifest in sorted(self.root.glob(f"*.woodshed/{MANIFEST}")):
            if manifest.parent.is_symlink():  # served pages are real folders of the library
                continue
            try:
                data = json.loads(manifest.read_text(encoding="utf-8"))
                info = dict(data["summary"])
            except (OSError, ValueError, KeyError, TypeError):
                continue
            info["complete"] = data.get("complete") is True
            # Complete but still on older page code after the start's update: its data is in a format this
            # code does not read, so only a new analysis gives it this version's page.
            # Refused at the start, and still older now: a new analysis since clears it.
            info["stale"] = manifest.parent.name in self.stale and _older(manifest)
            info["folder"] = manifest.parent.name  # the real folder, never a name read from a file
            info["words"] = (manifest.parent / lyrics.LYRICS).is_file()
            band = self._stored(manifest.parent.name)["band"]
            if band:
                info["band"] = band
            left = self._left_to_check(manifest.parent)
            if left is not None:  # the band's corrections done: what is still to check by ear
                info["doubts"] = left
            out.append(info)
        return sorted(out, key=lambda s: str(s.get("title", "")).lower())

    def clear_cut_uploads(self) -> None:
        """Uploads cut short by a stop or a crash. Only once this app holds the port: an app already
        running on the library may be receiving one."""
        for leftover in self.songs.glob(".*.part"):
            leftover.unlink(missing_ok=True)

    def update_pages(self) -> list[str]:
        """Pages built by an older woodshed get this version's page code; their analysis is kept."""
        updated = []
        for manifest in sorted(self.root.glob(f"*.woodshed/{MANIFEST}")):
            if manifest.parent.is_symlink():
                continue
            name = manifest.parent.name
            try:
                if update_page_code(manifest.parent) is not None:
                    updated.append(name)
                    self.stale.discard(name)
                elif _older(manifest):  # complete, older page code, and refused: its data is another format
                    self.stale.add(name)
                    print(f"woodshed app: {name}: made by an older woodshed, analyse it again", flush=True)
            except (WoodshedError, OSError) as exc:  # one page held open or not writable: the others still are
                print(f"woodshed app: {manifest.parent.name}: not updated ({exc})", flush=True)
        return updated

    def busy(self) -> bool:
        """A heavy job runs (an analysis, words, a measure): the renders wait."""
        return self.running is not None or self.measuring is not None

    def measure_voices(self) -> list[str]:
        """Pages built before the voice's range per key region (spec 024) get it, measured on their own vocal
        track in the background: never during the start, and songs, words and the renders a page waits for go
        first. The page's own data says what is measured, not its page revision. A measure that fails is tried
        again at the next start, then only once the page or woodshed changed (a note beside the page)."""
        queued = []
        for manifest in sorted(self.root.glob(f"*.woodshed/{MANIFEST}")):
            page = manifest.parent
            if page.is_symlink() or not build.needs_vocal_regions(page) or self._gave_up(page):
                continue
            job = Job(secrets.token_hex(6), page.name, page=page.name, kind="voice")  # the library's own: not listed
            self.queue.put((job, page, self.opts, False, None))
            queued.append(page.name)
        return queued

    VOICE_TRIES = 2  # failed measures of one page, as it is, before the starts stop trying

    def _voice_note(self, page: Path) -> Path:
        return page.with_name(f".{page.name}.voice")

    def _page_stamp(self, page: Path) -> list[Any]:
        index = (page / "index.html").stat()
        return [__version__, index.st_mtime_ns, index.st_size]

    def _gave_up(self, page: Path) -> bool:
        try:
            note = json.loads(self._voice_note(page).read_text(encoding="utf-8"))
            return bool(note["page"] == self._page_stamp(page) and note["failures"] >= self.VOICE_TRIES)
        except (OSError, ValueError, KeyError, TypeError):
            return False

    def _voice_failed(self, page: Path, why: str) -> None:
        note = self._voice_note(page)
        try:
            stamp = self._page_stamp(page)
            try:
                before = json.loads(note.read_text(encoding="utf-8"))
                failures = int(before["failures"]) if before["page"] == stamp else 0
            except (OSError, ValueError, KeyError, TypeError):
                failures = 0
            note.write_text(json.dumps({"page": stamp, "failures": failures + 1, "error": why}), encoding="utf-8")
        except OSError:
            pass

    def _others_first(self, item: tuple[Job, Path, Options, bool, str | None]) -> bool:
        """Before a measure: a song or words queued go first (the measure goes back to the end of the queue,
        True), and a render a page waits for is let through (waited for here)."""
        while not self.stopping.is_set():
            with self.queue.mutex:
                others = any(queued[0].kind != "voice" for queued in self.queue.queue)
            if others:
                self.queue.put(item)
                self.queue.task_done()
                return True
            if self.renders is None or not self.renders.wanted():
                return False
            time.sleep(0.2)
        return False

    def _measure_voice(self, job: Job, page: Path) -> None:
        try:
            with self.lock:
                if self.stopping.is_set():
                    return
                self.measuring = page  # the renders wait, as for an analysis
            job.status = "measuring"
            if build.add_vocal_regions(page) and self.on_reload is not None:
                self.on_reload(page.name)
            self._voice_note(page).unlink(missing_ok=True)
            job.status = "done"
        except Exception as exc:  # the page stays as it was
            job.status, job.message = "failed", str(exc)
            if not self.stopping.is_set():
                self._voice_failed(page, str(exc))
            print(f"woodshed app: {page.name}: the voice range per key was not measured ({exc})", flush=True)
        finally:
            job.ended = time.time()
            with self.lock:
                self.measuring = None
            self.queue.task_done()

    def _page_song(self, page: Path) -> dict[str, Any] | None:
        """A page's song data, read once per build of the page (its doubts are counted every poll)."""
        index = page / "index.html"
        try:
            stamp = index.stat().st_mtime_ns
        except OSError:
            return None
        cached = self.page_songs.get(page.name)
        if cached is not None and cached[0] == stamp:
            return cached[1]
        song: dict[str, Any] | None
        try:
            found = DATA_BLOCK.search(index.read_text(encoding="utf-8"))
            if found is None:
                raise ValueError("not a woodshed page")
            song = json.loads(found.group(1))["song"]
            if not isinstance(song, dict):
                raise ValueError("not a song")
        except (OSError, ValueError, KeyError, TypeError):
            song = None
        self.page_songs[page.name] = (stamp, song)
        return song

    def _chords_to_check(self, page: Path) -> tuple[str, set[str]] | None:
        """A page's analysis key (as the page computes it) and the ids of its chords to check by ear."""
        song = self._page_song(page)
        try:
            ids = {
                str(c["doubt"]["id"])
                for b in song["bars"]  # type: ignore[index]
                for c in b["chords"]
                if c.get("doubt") and c["doubt"].get("kind") == "chord"
            }
            return analysis_key(song), ids  # type: ignore[arg-type]
        except (ValueError, KeyError, TypeError, AttributeError):
            return None

    def _left_to_check(self, page: Path) -> int | None:
        """Chords to check minus those the band corrected, in this analysis of the page (an older
        analysis's corrections number their doubts their own way)."""
        found = self._chords_to_check(page)
        if found is None:
            return None
        key, ids = found
        stored = self._stored(page.name)
        left = ids - set(stored["by_key"].get(key, {}))
        spans = self._doubt_beats(page)
        if spans is not None and left:
            grid, beats_of = spans
            typed = stored["edits"].get(grid, {}).get("bars", {})
            covered = {int(at) + k for at, e in typed.items() for k in range(sum(n for n, _ in e["chords"]))}
            left = {d for d in left if beats_of.get(d, set()).isdisjoint(covered)}
        return len(left)

    def _doubt_beats(self, page: Path) -> tuple[str, dict[str, set[int]]] | None:
        """A page's beat grid key and, per chord to check, the beats it covers (as song.beats counts them):
        a typed bar over any of them settles it."""
        song = self._page_song(page)
        try:
            per, first = song["beats_per_bar"], song["first_beat"]  # type: ignore[index]
            beats_of: dict[str, set[int]] = {}
            for u, bar in enumerate(song["bars"]):  # type: ignore[index]
                at = first + u * per
                for c in bar["chords"]:
                    if c.get("doubt") and c["doubt"].get("kind") == "chord":
                        beats_of[str(c["doubt"]["id"])] = set(range(at, at + c["beats"]))
                    at += c["beats"]
            return beats_key(song), beats_of  # type: ignore[arg-type]
        except (ValueError, KeyError, TypeError, AttributeError):
            return None

    def _set_names(self) -> list[str] | None:
        """The set as saved, pages removed since included: [] without a set list, None if it cannot be read
        (then nothing is cleared on its account)."""
        try:
            data = json.loads((self.root / SETLIST).read_text(encoding="utf-8"))
        except FileNotFoundError:
            return []
        except (OSError, ValueError):
            return None
        names = data.get("songs") if isinstance(data, dict) else None
        return [n for n in names if isinstance(n, str)] if isinstance(names, list) else None

    def setlist(self) -> list[str]:
        """The set, as page folders in order; songs removed since are left out."""
        pages = {p["folder"] for p in self.pages()}
        return list(dict.fromkeys(n for n in self._set_names() or [] if n in pages))

    def set_setlist(self, data: Any) -> list[str]:
        names = data.get("songs") if isinstance(data, dict) else None
        if not isinstance(names, list) or len(names) > SETLIST_MAX or not all(isinstance(n, str) for n in names):
            raise ValueError("songs: a list of page folders")
        pages = {p["folder"] for p in self.pages()}
        unknown = [n for n in names if n not in pages]
        if unknown or len(set(names)) != len(names):
            raise ValueError("songs: each page of the library once at most")
        with self.lock:
            left = [n for n in self._set_names() or [] if n not in names]
            tmp = self.root / f".{SETLIST}.{secrets.token_hex(4)}"
            try:
                tmp.write_text(json.dumps({"songs": names}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
                tmp.replace(self.root / SETLIST)
            finally:
                tmp.unlink(missing_ok=True)
            # A note is written from the set list: it is the set's note for that song, gone with it.
            cleared = {folder: rev for folder in left if (rev := self._clear_note(folder)) is not None}
        if self.on_band is not None:
            for folder, rev in cleared.items():
                self.on_band(folder, rev)  # the open pages read the song again
        return list(names)

    def _clear_note(self, folder: str) -> int | None:
        """Under the lock: the band's note on a song taken away; its new revision, or None if it had none."""
        stored = self._stored(folder)
        if "note" not in stored["band"]:
            return None
        stored["band"].pop("note")
        return self._write(folder, stored)

    def clear_notes_out_of_the_set(self) -> None:
        """At start, once the port is ours (serve): the notes 0.4.0 left on songs out of the set."""
        names = self._set_names()
        if names is None:  # a set list damaged by hand or unreadable: no note is lost on its account
            return
        with self.lock:
            for file in sorted((self.root / CORRECTIONS_DIR).glob("*.woodshed.json")):
                if file.stem in names:
                    continue
                try:
                    self._clear_note(file.stem)
                except OSError as exc:  # a library on a read-only disk still starts
                    print(f"woodshed app: the notes of songs out of the set were not cleared: {exc}", file=sys.stderr)
                    return

    # Corrections: the chords picked by ear, kept by the library so every device of the band reads
    # the same chart. Out of the page folders (a rebuild replaces them), per analysis of the song: a
    # page left open on an older analysis never hides the corrections of the current one.

    def _page(self, folder: Any) -> str:
        if not isinstance(folder, str) or folder not in {p["folder"] for p in self.pages()}:
            raise ValueError("page: a page folder of the library")
        return folder

    def _corrections_file(self, folder: str) -> Path:
        return self.root / CORRECTIONS_DIR / f"{folder}.json"

    def _stored(self, folder: str) -> dict[str, Any]:
        """What the library holds for a page; an entry damaged by hand is skipped, the others kept."""
        out: dict[str, Any] = {"rev": 0, "by_key": {}, "at": {}, "band": {}, "removed": {}, "edits": {}}
        try:
            data = json.loads(self._corrections_file(folder).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return out
        if not isinstance(data, dict):
            return out
        rev = data.get("rev")
        out["rev"] = rev if type(rev) is int and rev >= 0 else 0
        with contextlib.suppress(ValueError):
            out["band"] = _checked_band(data.get("band") or {})
        entries = data.get("by_key")
        for key, entry in entries.items() if isinstance(entries, dict) else []:
            try:
                out["by_key"][key] = _checked_corrections({"key": key, "fixes": entry["fixes"]})["fixes"]
                out["at"][key] = float(entry.get("at", 0))
                gone = entry.get("removed", {})
                out["removed"][key] = _checked_removed(gone)
            except (ValueError, KeyError, TypeError, AttributeError):
                continue
        kept = data.get("edits")
        for key, entry in kept.items() if isinstance(kept, dict) else []:
            try:
                checked = _checked_edits({"key": key, "bars": entry["bars"], "parts": entry["parts"]})
                gone = _checked_edits(
                    {"key": key, "bars": entry["removed_bars"], "parts": entry["removed_parts"]}, removals=True
                )
                out["edits"][key] = {
                    "bars": checked["bars"],
                    "parts": checked["parts"],
                    "removed_bars": gone["bars"],
                    "removed_parts": gone["parts"],
                    "at": float(entry.get("at", 0)),
                }
            except (ValueError, KeyError, TypeError, AttributeError):
                continue
        return out

    def corrections(self, folder: Any, key: Any, edits: Any = None) -> dict[str, Any]:
        folder = self._page(folder)
        if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9]{1,64}", key):
            raise ValueError("key: the analysis the corrections belong to")
        stored = self._stored(folder)
        rev = max(stored["rev"], self.revisions.get(folder, 0))
        removed = stored["removed"].get(key, {})
        answer = {
            "key": key,
            "fixes": stored["by_key"].get(key, {}),
            "rev": rev,
            "band": stored["band"],
            "removed": removed,
        }
        if edits is not None:  # the typed chords and parts of this beat grid (core/edits.js)
            if not isinstance(edits, str) or not re.fullmatch(r"[A-Za-z0-9]{1,64}", edits):
                raise ValueError("edits: the beat grid the edits belong to")
            entry = stored["edits"].get(edits, {})
            answer["edits"] = {k: entry.get(k, {}) for k in ("bars", "parts", "removed_bars", "removed_parts")}
        return answer

    def set_corrections(self, data: Any) -> dict[str, Any]:
        if not isinstance(data, dict):
            raise ValueError("corrections: a JSON object")
        folder = self._page(data.get("page"))
        checked = _checked_corrections(data, removals=True)
        key = checked["key"]
        with self.lock:
            stored = self._stored(folder)
            # Two devices correcting at once: both chords are kept; a later choice for a doubt wins.
            # A choice of null takes the doubt back to the analysis: it is remembered as removed, so a
            # device still holding the old fix drops it instead of sharing it again.
            # Each removal keeps the fix it removed: a device drops its copy only when it is that one,
            # so a newer correction made offline is not lost to an older removal.
            merged, removed = _merge_keyed(
                stored["by_key"].get(key, {}), stored["removed"].get(key, {}), checked["fixes"]
            )
            if len(removed) > CORRECTIONS_MAX:
                raise ValueError("fixes: chords by doubt id")
            if len(merged) > CORRECTIONS_MAX:
                raise ValueError("fixes: chords by doubt id")
            stored["by_key"][key] = merged
            stored["removed"][key] = removed
            stored["at"][key] = time.time()
            for old in sorted(stored["at"], key=stored["at"].get)[: max(0, len(stored["at"]) - CORRECTIONS_KEYS)]:
                stored["by_key"].pop(old, None)  # the analyses of long ago
                stored["removed"].pop(old, None)
                stored["at"].pop(old, None)
            rev = self._write(folder, stored)
            return {"key": key, "fixes": merged, "rev": rev, "band": stored["band"], "removed": removed}

    def set_edits(self, data: Any) -> dict[str, Any]:
        """The band's typed bars and part names for one beat grid, merged entry by entry like the picks."""
        if not isinstance(data, dict):
            raise ValueError("edits: a JSON object")
        folder = self._page(data.get("page"))
        checked = _checked_edits(data, removals=True)
        key = checked["key"]
        with self.lock:
            stored = self._stored(folder)
            entry = stored["edits"].get(key, {})
            bars, removed_bars = _merge_keyed(entry.get("bars", {}), entry.get("removed_bars", {}), checked["bars"])
            parts, removed_parts = _merge_keyed(
                entry.get("parts", {}), entry.get("removed_parts", {}), checked["parts"]
            )
            if (
                max(len(bars), len(removed_bars)) > EDITS_BARS_MAX
                or max(len(parts), len(removed_parts)) > EDITS_PARTS_MAX
            ):
                raise ValueError("edits: too many typed bars or parts")
            stored["edits"][key] = {
                "bars": bars,
                "parts": parts,
                "removed_bars": removed_bars,
                "removed_parts": removed_parts,
                "at": time.time(),
            }
            for old in sorted(stored["edits"], key=lambda k: stored["edits"][k]["at"])[:-CORRECTIONS_KEYS]:
                stored["edits"].pop(old)  # the beat grids of long ago
            rev = self._write(folder, stored)
            return {
                "key": key,
                **{k: stored["edits"][key][k] for k in ("bars", "parts", "removed_bars", "removed_parts")},
                "rev": rev,
            }

    def set_band(self, data: Any) -> dict[str, Any]:
        """The band's own choices for a song, from any device: the key it plays in, the leader's note."""
        if not isinstance(data, dict):
            raise ValueError("band: a JSON object")
        folder = self._page(data.get("page"))
        change = _checked_band({k: data[k] for k in ("transpose", "key", "note") if k in data})
        if ("transpose" in change) != ("key" in change):
            raise ValueError("transpose and key go together")
        with self.lock:
            stored = self._stored(folder)
            band = {**stored["band"], **change}
            if band.get("transpose") == 0:  # the recorded key again: nothing to say
                band.pop("transpose", None)
                band.pop("key", None)
            names = self._set_names()
            # A note is the set's: none for a song out of it (removed from the set while the note was written).
            if not band.get("note") or (names is not None and folder not in names):
                band.pop("note", None)
            stored["band"] = band
            rev = self._write(folder, stored)
        if self.renders is not None and "transpose" in change:  # the band's key, ready on every device
            audio_dir = self.root / folder / "audio"
            voice = [t for t in ("mix", "solo-vocals", "minus-vocals") if (audio_dir / f"{t}.flac").is_file()]
            self.renders.set_band_key(folder, int(band.get("transpose", 0)), voice)
        return {"band": band, "rev": rev}

    def _write(self, folder: str, stored: dict[str, Any]) -> int:
        """Under the lock: the page's corrections and band choices, with the next revision."""
        rev: int = max(stored["rev"], self.revisions.get(folder, 0)) + 1  # kept in the file: grows across restarts
        body: dict[str, Any] = {
            "rev": rev,
            "by_key": {
                k: {
                    "fixes": v,
                    "at": stored["at"][k],
                    **({"removed": r} if (r := stored["removed"].get(k)) else {}),
                }
                for k, v in stored["by_key"].items()
            },
        }
        if stored["band"]:
            body["band"] = stored["band"]
        if stored.get("edits"):
            body["edits"] = stored["edits"]
        target = self._corrections_file(folder)
        target.parent.mkdir(exist_ok=True)
        tmp = target.with_name(f".{target.name}.{secrets.token_hex(4)}")
        try:
            tmp.write_text(json.dumps(body, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
            tmp.replace(target)
        finally:
            tmp.unlink(missing_ok=True)
        self.revisions[folder] = rev
        return rev

    def state(self) -> dict[str, Any]:
        with self.lock:
            # Finished jobs stay visible a while (a failure for an hour), then are forgotten.
            now = time.time()
            for key in [
                k
                for k, j in self.jobs.items()
                if j.status in ("done", "failed")
                and now - (j.ended or j.started) > (3600 if j.status == "failed" else 60)
            ]:
                del self.jobs[key]
            jobs = [asdict(j) for j in self.jobs.values()]
        separates = self.opts.use_stems and stems_extra_installed()
        # What the library separates new songs with: the home page's "Guitar and keys apart" starts there.
        separation = new_page_model(self.opts).key
        return {"songs": self.pages(), "jobs": jobs, "separates": separates, "separation": separation}

    def reserve(self, name: str) -> Path:
        """Where an upload goes: a safe name, unique by its stem (one page per stem), reserved
        until the upload ends so two uploads of one name never share a file."""
        clean = re.sub(r'[<>:"/\\|?*#%\x00-\x1f]', "_", Path(name).name).strip(" .")
        stem, suffix = Path(clean).stem or "song", Path(clean).suffix.lower()
        if suffix not in audio.MEDIA:
            raise WoodshedError(f"{name}: not an audio or video file")
        with self.lock:
            taken = {p.stem.lower() for p in self.songs.iterdir() if not p.name.startswith(".")} | self.reserved
            candidate, n = stem, 1
            while candidate.lower() in taken:
                n += 1
                candidate = f"{stem} ({n})"
            self.reserved.add(candidate.lower())
        return self.songs / f"{candidate}{suffix}"

    def release(self, path: Path) -> None:
        with self.lock:
            self.reserved.discard(path.stem.lower())

    def options(
        self, beats_per_bar: int = 4, sevenths: bool = False, bpm: float | None = None, separation: str | None = None
    ) -> Options:
        """The options of one song: the library's, with the ones given at upload."""
        if not 2 <= beats_per_bar <= 12 or (bpm is not None and not 30 <= bpm <= 300):
            raise ValueError("beats per bar 2 to 12, tempo 30 to 300 BPM")
        if separation is not None and separation not in stems.MODELS:
            raise ValueError("separation: four or six")
        return replace(
            self.opts, out=None, open_page=False, title=None, beats_per_bar=beats_per_bar, sevenths=sevenths, bpm=bpm,
            separation=separation or self.opts.separation,
        )  # fmt: skip

    @staticmethod
    def attempt(src: Path) -> Path:
        """A hidden note next to a song while it is processed, kept with the error if it fails: a
        song that failed, or killed the app, is not tried again at every start."""
        return src.with_name(f".{src.name}.attempt")

    def resume(self) -> list[Job]:
        """Queue again the songs a stop left unfinished: no page yet, or a page still waiting for
        its stems. A page keeps the options it was uploaded with. A song that failed is listed as
        failed, not tried again."""
        jobs: list[Job] = []
        seen: set[str] = set()
        for src in media_files(self.songs):
            try:
                job = self._resume(src, seen)
            except Exception as exc:  # one odd song must not stop the app from starting
                job = self._failed(src, f"not resumed: {exc}")
            if job is not None:
                jobs.append(job)
        return jobs

    def _resume(self, src: Path, seen: set[str]) -> Job | None:
        folder = folder_name(src.stem)
        page = self.root / folder
        if page.is_symlink():
            return None
        try:
            manifest = json.loads((page / MANIFEST).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            manifest = None
        manifest = manifest if isinstance(manifest, dict) else {}
        if manifest.get("complete") is True:
            return None
        note = self.attempt(src)
        if note.exists():
            # Also after a power cut or a kill -9: the song is not tried again until it is added again.
            error = note.read_text(encoding="utf-8", errors="replace").strip() or "the app stopped during it"
            where = src.relative_to(self.root)
            return self._failed(src, f"failed last time ({error}); to retry, remove {where} and add it again")
        if folder.lower() in seen:  # pop.wav and pop.mp3 copied in by hand: one page
            return self._failed(src, f"not resumed: another file already makes {folder}")
        seen.add(folder.lower())
        given = manifest.get("settings")
        return self.add(src, self._options_of(given if isinstance(given, dict) else {}), uploaded=False)

    def _options_of(self, given: dict[str, Any]) -> Options:
        """A page's options as its manifest keeps them; each field checked on its own: a page edited by
        hand keeps its good fields."""
        beats, bpm, phase = given.get("beats_per_bar"), given.get("bpm"), given.get("bar_phase")
        per = beats if isinstance(beats, int) and not isinstance(beats, bool) and 2 <= beats <= 12 else 4
        opts = self.options(
            per,
            given.get("sevenths") is True,
            float(bpm) if isinstance(bpm, (int, float)) and not isinstance(bpm, bool) and 30 <= bpm <= 300 else None,
        )
        # The separation of a page that has its instruments' tracks (absent: four, as every page built before six
        # stems); a page without them is separated as a new one.
        if given.get("stems") is True:
            opts = replace(opts, separation=stems.model_of(given).key)
        return replace(opts, bar_phase=phase if type(phase) is int and 0 <= phase < per else None)

    def move_bars(self, data: Any, playing: Callable[[str], bool] | None = None) -> Job:
        """The band's bar lines for a page, {"page", "bar_phase"}: the song analysed again from its file
        in the library and its separated tracks in the cache. The beats do not move, so the chords and
        parts the band typed stay where they were; the picks among candidates start over. The errors are
        fixed sentences: the page says them in the band's language."""
        if not isinstance(data, dict):
            raise ValueError("an object with page and bar_phase")
        folder = self._page(data.get("page"))
        try:
            manifest = json.loads((self.root / folder / MANIFEST).read_text(encoding="utf-8"))
            given = manifest["settings"] if isinstance(manifest["settings"], dict) else {}
        except (OSError, ValueError, KeyError, TypeError):
            raise ValueError("this page has no settings to analyse it again with") from None
        opts = self._options_of(given)
        phase = data.get("bar_phase")
        if type(phase) is not int or not 0 <= phase < opts.beats_per_bar:
            raise ValueError("the bar phase is out of range")
        if playing is not None and playing(folder):
            raise PermissionError("the band is playing this song: stop it first")
        src = next(
            (
                s
                for s in media_files(self.songs)
                if folder_name(s.stem) == folder and stems.fingerprint(s) == given.get("source")
            ),
            None,
        )
        if src is None:
            raise ValueError("the recording is no longer in the library: the command line moves them")
        with_stems = given.get("stems") is True  # a page with parts keeps them, whatever the library runs with
        if with_stems and not stems_extra_installed():
            raise ValueError("the bar lines of this song need the stems extra")
        if with_stems and stems.cached(src, stems.model_of(given)) is None:
            raise ValueError("the separated tracks are no longer in the cache: add the song again")
        with self.lock:
            if any(j.page == folder and j.status not in ("done", "failed") for j in self.jobs.values()):
                raise PermissionError("this song is already being worked on: try again when it is done")
            job = Job(secrets.token_hex(6), folder, page=folder, kind="bars")
            self.jobs[job.id] = job
        self.queue.put((job, src, replace(opts, bar_phase=phase, use_stems=with_stems), False, None))
        return job

    def _failed(self, src: Path, message: str) -> Job:
        job = Job(secrets.token_hex(6), src.name, status="failed", message=message)
        with self.lock:
            self.jobs[job.id] = job
        return job

    def add(self, path: Path, opts: Options, uploaded: bool = True) -> Job:
        job = Job(secrets.token_hex(6), path.name)
        with self.lock:
            self.jobs[job.id] = job
        self.queue.put((job, path, opts, uploaded, None))
        return job

    def add_words(self, data: Any) -> Job:
        """Words pasted on a song page, placed in the background: {"page": folder, "text": words}."""
        if not isinstance(data, dict):
            raise ValueError("an object with page and text")
        folder = self._page(data.get("page"))
        text = data.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("text: the words of the song")
        if len(text.encode("utf-8")) > WORDS_BYTES:
            raise ValueError("text: the words of one song, 32 KB at most")
        with self.lock:
            if any(j.page == folder and j.status not in ("done", "failed") for j in self.jobs.values()):
                raise PermissionError("this song is already being worked on: try again when it is done")
            job = Job(secrets.token_hex(6), folder, page=folder, kind="words")
            self.jobs[job.id] = job
        self.queue.put((job, self.root / folder, self.opts, False, text))
        return job

    def _work(self) -> None:
        while True:
            job, path, opts, uploaded, words = self.queue.get()
            if job.kind == "voice":
                if not self._others_first((job, path, opts, uploaded, words)):
                    self._measure_voice(job, path)
                continue
            if words is not None:
                self._place_words(job, path, words, opts)
                continue
            report = JobReporter(job)
            note = self.attempt(path)
            if self.renders is not None:  # the page's files are rebuilt: its renders are of the old ones
                self.renders.cancel_page(job.page or folder_name(path.stem))
            with self.lock:
                if self.stopping.is_set():
                    return
                self.running = path
                with contextlib.suppress(OSError):  # under the lock: a stop never misses it
                    note.write_text("", encoding="utf-8")
            try:
                job.status = "analysing"
                done = first_pass(path, opts, report, self.root)
                job.page = done.page.name
                if done.stems_to_come:
                    job.status = "separating"
                    done = second_pass(done, report)
                if job.kind == "bars" and self.on_bars is not None:
                    self.on_bars(job.page)  # before "done": the page that asked reloads with the count already told
                job.status, job.message = "done", "Ready"
                note.unlink(missing_ok=True)
            except (WoodshedError, OSError) as exc:
                job.status, job.message = "failed", str(exc)
                with self.lock:  # one order with interrupted(): a stop never leaves a failure behind
                    if self.stopping.is_set():  # Ctrl-C also stops ffmpeg: not the song's fault
                        continue
                    if job.kind == "bars":
                        self._bars_failed(note, job)
                        continue
                    self._keep_failure(note, job)
                    if uploaded and job.page is None:  # nothing came of it: the file does not keep its name taken
                        path.unlink(missing_ok=True)
                        note.unlink(missing_ok=True)
            except Exception as exc:  # a bug must not stop the queue
                job.status, job.message = "failed", f"unexpected error: {exc}"
                with self.lock:
                    if job.kind == "bars":
                        self._bars_failed(note, job)
                    elif not self.stopping.is_set():
                        self._keep_failure(note, job)
                traceback.print_exc()
            finally:
                job.ended = time.time()
                with self.lock:
                    self.running = None
                self.queue.task_done()

    def _place_words(self, job: Job, page: Path, text: str, opts: Options) -> None:
        try:
            if self.stopping.is_set():
                return
            job.status = "placing"
            data = lyrics.add_to_page(
                page,
                text,
                opts.offline,
                say=lambda line: setattr(job, "message", line),
                progress=lambda f: setattr(job, "percent", int(f * 100)),
            )
            sung = sum(ln["sung"] for ln in data["lines"])
            job.notes = [str(n) for n in data.get("notes") or []]
            job.status, job.message = "done", f"{sung} of {len(data['lines'])} lines placed on the voice"
        except (WoodshedError, OSError) as exc:
            # Read by every phone of the band: the song's folder, never where the library is.
            job.status, job.message = (
                "failed",
                str(exc)
                .replace(str(page), page.name)
                .replace(str(cache_dir()), "the cache")
                .replace(str(self.root), "the library"),
            )
        except ImportError:
            job.status, job.message = "failed", "the words need the stems extra: " + EXTRA_HINT.split(": ", 1)[1]
        except Exception as exc:  # a bug must not stop the queue
            job.status, job.message = "failed", f"unexpected error: {type(exc).__name__}"
            traceback.print_exc()
        finally:
            job.ended = time.time()
            self.queue.task_done()

    def _bars_failed(self, note: Path, job: Job) -> None:
        """The bar lines did not move: the page is as it was, nothing to try again at the next start, and
        the reason told to the phones without this computer's paths."""
        note.unlink(missing_ok=True)
        job.message = job.message.replace(str(cache_dir()), "the cache").replace(str(self.root), "the library")

    @staticmethod
    def _keep_failure(note: Path, job: Job) -> None:
        with contextlib.suppress(OSError):
            note.write_text(job.message, encoding="utf-8")

    def _page_quick(self, folder: Any) -> str:
        """A page folder of the library, checked without reading every page (polled by phones)."""
        if not isinstance(folder, str):
            raise ValueError("page: a page folder of the library")
        ok = folder.endswith(".woodshed") and "/" not in folder and "\\" not in folder and not folder.startswith(".")
        if not ok or not (self.root / folder / MANIFEST).is_file():
            raise ValueError("page: a page folder of the library")
        return folder

    def pitch_state(self, page: Any) -> dict[str, Any]:
        """For a song page: can this library change the recording's key, and where its renders are."""
        folder = self._page_quick(page)
        # The system names the one step that adds the key when it cannot (the installer, or the package).
        system = {"darwin": "mac", "win32": "windows"}.get(sys.platform, "linux")
        state: dict[str, Any] = {"can": self.renders is not None, "off": not self.opts.pitch, "system": system}
        # What stands in the way when it cannot: an ffmpeg without the filter, the program there but blocked.
        state |= {"ffmpeg": pitch.has_ffmpeg(), "blocked": pitch.blocked()}
        return state | (
            self.renders.state(folder)
            if self.renders is not None
            else {"keys": {}, "versions": {}, "failed": {}, "eta": {}}
        )

    def ask_pitch(self, data: Any) -> dict[str, Any]:
        """{page, track, semitones}: one of the page's tracks in another key, queued for rendering."""
        if not isinstance(data, dict):
            raise ValueError("an object with page, track and semitones")
        folder = self._page_quick(data.get("page"))
        track, semitones = data.get("track"), data.get("semitones")
        if type(semitones) is not int or not -6 <= semitones <= 6 or semitones == 0:
            raise ValueError("semitones: -6 to 6, not 0")
        audio_dir = self.root / folder / "audio"
        known = isinstance(track, str) and re.fullmatch(r"mix|(solo|minus)-[a-z]{1,16}", track) is not None
        if not known or track in pitch.UNPITCHED or not (audio_dir / f"{track}.flac").is_file():
            raise ValueError("track: one of the page's pitched tracks")
        if self.renders is None:
            raise PermissionError("this library cannot change the key")
        band = self._stored(folder)["band"].get("transpose")
        if type(band) is int and band and folder not in self.renders.band:
            # After a restart: the band's key known again before any pruning, and its tracks prepared again.
            voice = [t for t in ("mix", "solo-vocals", "minus-vocals") if (audio_dir / f"{t}.flac").is_file()]
            self.renders.set_band_key(folder, band, voice)
        waited = data.get("wait") is True  # the track the page plays: ahead of the role's others
        priority = pitch.WAITED if waited else pitch.ROLE
        return {"state": self.renders.ask(folder, str(track), semitones, priority, force=data.get("force") is True)}

    def interrupted(self) -> None:
        """The app is stopping: the song in progress did not fail, it is resumed next time."""
        if self.renders is not None:
            self.renders.stop()  # a render's ffmpeg child stops with the app
        with self.lock:
            self.stopping.set()
            if self.running is not None:
                self.attempt(self.running).unlink(missing_ok=True)


LIVE_MAX = 4096  # bytes of one live update
LIVE_FOLLOWERS = 32  # open streams at most: a band, not an audience
LIVE_PING = 15.0  # seconds between keep-alive comments on a quiet stream


def _as_js(value: Any) -> Any:
    """Numbers as JSON.stringify writes them: a whole float without its ".0"."""
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, list):
        return [_as_js(v) for v in value]
    return value


def _fnv1a(text: str) -> str:
    """fnv1a in app.js, over UTF-16 code units as charCodeAt reads them."""
    h = 0x811C9DC5
    units = text.encode("utf-16-le")
    for i in range(0, len(units), 2):
        h = ((h ^ int.from_bytes(units[i : i + 2], "little")) * 0x01000193) & 0xFFFFFFFF
    return format(h, "x")


def analysis_key(song: dict[str, Any]) -> str:
    """The key the page keeps its corrections under (fnv1a in app.js): what a correction depends on,
    the chords, their doubts and the beats."""
    chords = [
        [[c["pc"], c["quality"], c["beats"], c["doubt"]["id"] if c.get("doubt") else None] for c in b["chords"]]
        for b in song["bars"]
    ]
    return _fnv1a(json.dumps(_as_js([chords, song["beats"]]), separators=(",", ":"), ensure_ascii=False))


def beats_key(song: dict[str, Any]) -> str:
    """The key the page keeps typed chords and parts under (core/edits.js): the beats alone, in whole
    milliseconds, so a new analysis on the same beats (the bar lines moved) keeps them."""
    return _fnv1a(json.dumps([math.floor(t * 1000 + 0.5) for t in song["beats"]], separators=(",", ":")))


def _merge_keyed(
    current: dict[str, Any], removed: dict[str, Any], changes: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Two devices changing one store at once: both kept, the later value of an entry wins. None takes
    an entry back and remembers what it took back (said again, the first removal is kept), so a device
    still holding that value drops it instead of sharing it again, and keeps a newer one of its own."""
    merged, gone = dict(current), dict(removed)
    for k, value in changes.items():
        if value is None:
            gone[k] = merged.pop(k, gone.get(k))
        else:
            merged[k] = value
            gone.pop(k, None)
    return merged, gone


def _checked_edits(data: Any, removals: bool = False) -> dict[str, Any]:
    """{"key", "bars", "parts"} as core/edits.js writes them; with `removals`, null takes an entry back."""
    key = data.get("key")
    if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9]{1,64}", key):
        raise ValueError("key: the beat grid the edits belong to")
    bars, parts = data.get("bars", {}), data.get("parts", {})
    if (
        not isinstance(bars, dict)
        or len(bars) > EDITS_BARS_MAX
        or not isinstance(parts, dict)
        or len(parts) > EDITS_PARTS_MAX
    ):
        raise ValueError("edits: typed bars and parts by beat")
    out: dict[str, Any] = {"key": key, "bars": {}, "parts": {}}
    for at, bar in bars.items():
        if not BEAT_INDEX.fullmatch(at):
            raise ValueError("bars: by the beat they start on")
        if bar is None and removals:
            out["bars"][at] = None
            continue
        chords = bar.get("chords") if isinstance(bar, dict) else None
        t = bar.get("t") if isinstance(bar, dict) else None
        if not isinstance(chords, list) or not 0 < len(chords) <= EDIT_CHORDS_MAX:
            raise ValueError("bars: chords as [beats, label]")
        if not isinstance(t, (int, float)) or isinstance(t, bool) or not 0 <= t < 86400:
            raise ValueError("bars: the time of the bar")
        kept: list[list[Any]] = []
        total = 0
        for chord in chords:
            n, label = chord if isinstance(chord, list) and len(chord) == 2 else (None, None)
            if type(n) is not int or not 0 < n <= EDIT_CHORDS_MAX:
                raise ValueError("bars: chords as [beats, label]")
            if (
                not isinstance(label, str)
                or len(label) > LABEL_MAX
                or isinstance(chord_grammar.parse(label), chord_grammar.Refusal)
            ):
                raise ValueError("bars: chords as written on a chart")
            kept.append([n, label])
            total += n
        if total > EDIT_CHORDS_MAX:
            raise ValueError("bars: one bar's beats at most")
        out["bars"][at] = {"chords": kept, "t": float(t)}
    for at, part in parts.items():
        if not BEAT_INDEX.fullmatch(at):
            raise ValueError("parts: by the beat they start on")
        if part is None and removals:
            out["parts"][at] = None
        elif part == {"join": True}:
            out["parts"][at] = {"join": True}
        elif isinstance(part, dict) and set(part) == {"name"} and isinstance(part["name"], str):
            name = UNSAFE.sub("", part["name"]).strip()
            if not name or len(part["name"]) > PART_NAME_MAX:
                raise ValueError("parts: a name of 1 to 40 characters")
            out["parts"][at] = {"name": name}
        else:
            raise ValueError("parts: a name or a join")
    return out


def _checked_band(data: Any) -> dict[str, Any]:
    """{"transpose", "key", "note"}, each optional: the band's key for a song and the leader's note."""
    if not isinstance(data, dict):
        raise ValueError("band: a JSON object")
    out: dict[str, Any] = {}
    if "transpose" in data:
        t = data["transpose"]
        if type(t) is not int or not -6 <= t <= 6:
            raise ValueError("transpose: -6 to 6 semitones")
        out["transpose"] = t
    if "key" in data:
        if not isinstance(data["key"], str) or not KEY_NAME.fullmatch(data["key"]):
            raise ValueError("key: a key name such as Eb or F#m")
        out["key"] = data["key"]
    if "note" in data:
        note = data["note"]
        if not isinstance(note, str) or len(note) > NOTE_MAX:
            raise ValueError(f"note: text, {NOTE_MAX} characters at most")
        out["note"] = " ".join(note.split())  # one line in the set list
    return out


def _checked_removed(data: Any) -> dict[str, list[Any] | None]:
    """Removals as kept in the file: the fix each doubt had when it went back to the analysis."""
    out: dict[str, list[Any] | None] = {}
    if isinstance(data, list):  # an early form: ids only
        data = dict.fromkeys(data)
    for doubt, fix in data.items() if isinstance(data, dict) else []:
        if not isinstance(doubt, str) or not DOUBT_ID.fullmatch(doubt):
            continue
        valid = (
            isinstance(fix, list)
            and len(fix) == 2
            and type(fix[0]) is int
            and 0 <= fix[0] <= 11
            and fix[1] in QUALITIES
        )
        out[doubt] = list(fix) if valid else None
    return out


def _checked_corrections(data: Any, removals: bool = False) -> dict[str, Any]:
    """{"key", "fixes"} as a page writes them: chords (pitch class, quality) by doubt id; with
    `removals`, null for a doubt taken back to the analysis."""
    key, fixes = data.get("key"), data.get("fixes")
    if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9]{1,64}", key):
        raise ValueError("key: the analysis the corrections belong to")
    if not isinstance(fixes, dict) or len(fixes) > CORRECTIONS_MAX:
        raise ValueError("fixes: chords by doubt id")
    for doubt, fix in fixes.items():
        if removals and fix is None and DOUBT_ID.fullmatch(doubt):
            continue
        if not DOUBT_ID.fullmatch(doubt) or not isinstance(fix, list) or len(fix) != 2:
            raise ValueError("fixes: [pitch class, quality] by doubt id")
        pc, quality = fix
        if type(pc) is not int or not 0 <= pc <= 11 or quality not in QUALITIES:
            raise ValueError("fixes: [pitch class, quality] by doubt id")
    return {"key": key, "fixes": {k: None if v is None else list(v) for k, v in fixes.items()}}


class NotLeader(PermissionError):
    """An update refused because the device does not lead: the answer carries the band as it is now,
    so the device follows it (or, when nobody leads after the app restarted, claims again)."""

    def __init__(self, message: str, state: dict[str, Any]) -> None:
        super().__init__(message)
        self.state = state


class Live:
    """Where the band is: the leader's song and position, kept in memory and sent to followers.

    One leader at a time: a device that claims the lead over the leader it heard (or over nobody)
    gets it, the previous leader sees on the stream that it now follows; a second claim over the same
    leader is refused. Updates from a device that is not the leader are refused. Every state is
    numbered (`v`), under a `boot` id that changes when the app restarts and counts from 0 again.
    """

    def __init__(self) -> None:
        self.cond = threading.Condition()
        self.state: dict[str, Any] = {"leader": None}
        self.version = 0
        self.boot = secrets.token_hex(6)
        self.followers = 0
        self.closed = False
        self.fixes: dict[str, int] = {}  # page folder -> revision of its corrections, told to followers
        self.moved: dict[str, int] = {}  # page folder -> how many times its bar lines moved: open pages reload
        self.updated: dict[str, int] = {}  # page folder -> how many times the library rewrote its data: pages reload

    def corrected(self, folder: str, rev: int) -> None:
        """The chart of a page was corrected: the followers hear it and read it again."""
        with self.cond:
            self.fixes[folder] = max(self.fixes.get(folder, 0), rev)  # answers can cross: never back
            self._changed()

    def bars_moved(self, folder: str) -> None:
        """A page's bar lines moved: the devices that have it open load it again."""
        with self.cond:
            self.moved[folder] = self.moved.get(folder, 0) + 1
            self._changed()

    def page_updated(self, folder: str) -> None:
        """The library rewrote a page's data (the voice range per key, spec 024): the open pages load it again."""
        with self.cond:
            self.updated[folder] = self.updated.get(folder, 0) + 1
            self._changed()

    def playing(self, folder: str) -> bool:
        """The band is playing this song now (a new analysis would pull the page from under it). A
        leader silent for longer than its heartbeat is gone (the phone closed while playing)."""
        with self.cond:
            s = self.state
            return s.get("song") == folder and s.get("playing") is True and time.time() - s.get("at", 0) < LEADER_GONE

    def payload(self) -> dict[str, Any]:
        """The state as the stream sends it."""
        with self.cond:
            return {
                **self._numbered(),
                **({"fixes": dict(self.fixes)} if self.fixes else {}),
                **({"moved": dict(self.moved)} if self.moved else {}),
                **({"updated": dict(self.updated)} if self.updated else {}),
            }

    def _numbered(self) -> dict[str, Any]:
        return {**self.state, "v": self.version, "boot": self.boot}

    def update(self, data: Any, library_root: Path) -> dict[str, Any]:
        if not isinstance(data, dict):
            raise ValueError("a live update is a JSON object")
        who = data.get("id")
        if not isinstance(who, str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,64}", who):
            raise ValueError("a live update needs the device id")
        with self.cond:
            leader = self.state.get("leader")
            if data.get("release") is True:
                if leader == who:
                    self.state = {"leader": None}
                    self._changed()
                return self._numbered()
            claim = data.get("lead") is True
            if not claim and leader != who:
                raise NotLeader("another device leads the band", {**self._numbered(), "now": time.time()})
            over = data.get("over")
            if over is not None and not (isinstance(over, str) and re.fullmatch(r"[A-Za-z0-9_-]{8,64}", over)):
                raise ValueError("over: the id of the device that led, or null")
            song = data.get("song")
            if not isinstance(song, str) or not song.endswith(".woodshed") or "/" in song or song.startswith("."):
                raise ValueError("song: a page folder of the library")
            if not (library_root / song / "index.html").is_file():
                raise ValueError("song: no such page in the library")
            time_, rate = data.get("time"), data.get("rate", 1.0)
            for value, low, high in ((time_, 0.0, 86400.0), (rate, 0.25, 2.0)):
                if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
                    raise ValueError("time and rate are numbers")
                if not low <= value <= high:
                    raise ValueError("time or rate out of range")
            loop = data.get("loop")
            if loop is not None and not (
                isinstance(loop, list) and len(loop) == 2 and all(type(x) is int and 0 <= x < 100_000 for x in loop)
            ):
                raise ValueError("loop: two bar numbers, or null")
            # A claim names the leader it heard: two devices tapping Lead at once over the same leader,
            # the first wins. A claim without `over` (a page older than 0.5.1) takes the lead as before.
            gone = self.state.get("playing") is True and time.time() - self.state.get("at", 0) > LEADER_GONE
            if claim and "over" in data and leader not in (None, who, over) and not gone:
                raise NotLeader("another device took the lead first", {**self._numbered(), "now": time.time()})
            self.state = {
                "leader": who,
                "song": song,
                "playing": data.get("playing") is True,
                "time": float(data["time"]),
                "rate": float(data.get("rate", 1.0)),
                "loop": loop,
                "at": time.time(),  # the server clock when `time` was true
            }
            self._changed()
            return self._numbered()

    def _changed(self) -> None:
        self.version += 1
        self.cond.notify_all()

    def wait(self, seen: int, timeout: float) -> tuple[int, dict[str, Any] | None]:
        """The next state after version `seen`, or None on a quiet `timeout`."""
        with self.cond:
            self.cond.wait_for(lambda: self.version != seen or self.closed, timeout)
            if self.closed or self.version == seen:
                return seen, None
            return self.version, self.payload()

    def close(self) -> None:
        with self.cond:
            self.closed = True
            self.cond.notify_all()


def lan_addresses() -> list[str]:
    """This computer's addresses on the local network, for the phones of the band."""
    found: set[str] = set()
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))  # a documentation address: no packet is sent
            found.add(s.getsockname()[0])
    except OSError:
        pass
    if not found:  # no route out: ask the name of this computer (on a Mac it can take seconds)
        with contextlib.suppress(OSError):
            found |= set(socket.gethostbyname_ex(socket.gethostname())[2])
    return sorted(a for a in found if not ipaddress.ip_address(a).is_loopback)


def _older(manifest: Path) -> bool:
    """A complete page built by other page code (a manifest without it is older still)."""
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    settings = data.get("settings") if isinstance(data, dict) else None
    built_by = settings.get("page") if isinstance(settings, dict) else None
    return data.get("complete") is True and built_by != page_revision()


def _home_network(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    return ip.is_private and not ip.is_link_local


def in_container() -> bool:
    """In the Docker image: its own address is on Docker's bridge, the phones cannot reach it."""
    return os.environ.get("WOODSHED_CONTAINER") == "1"


def public_urls() -> list[str]:
    """WOODSHED_PUBLIC_URL: the addresses the phones type, when the app cannot know them (Docker)."""
    out = []
    for raw in os.environ.get("WOODSHED_PUBLIC_URL", "").split(","):
        url = raw.strip()
        if re.fullmatch(r"https?://[A-Za-z0-9.\-\[\]:]+(:\d+)?/?", url):
            out.append(url if url.endswith("/") else url + "/")
    return out


# The library page's footer: what changed (on main on purpose: the newest notes, whatever the version
# installed) and how to update. Plain links, filled in by the library with its version: the page
# itself asks nothing of the network.
CHANGELOG_URL = "https://github.com/laugiov/woodshed/blob/main/CHANGELOG.md"
UPDATE_URL = "https://github.com/laugiov/woodshed/blob/main/docs/guide/install.md#updating"


def home_html(token: str) -> str:
    page = resources.files("woodshed").joinpath("page").joinpath("home.html").read_text(encoding="utf-8")
    filled = {"TOKEN": token, "VERSION": __version__, "CHANGELOG_URL": CHANGELOG_URL, "UPDATE_URL": UPDATE_URL}
    return re.sub(r"\{\{([A-Z_]+)\}\}", lambda m: filled[m.group(1)], page)


class Handler(BaseHTTPRequestHandler):
    server: AppServer
    protocol_version = "HTTP/1.1"
    timeout = 30  # seconds without a byte from the client: a stalled upload frees its thread

    def log_message(self, format: str, *args: Any) -> None:  # quiet: progress is on the page
        pass

    # Checks shared by every request.

    def _may_upload(self) -> bool:
        return self.server.uploads_from_network or self._from_this_computer()

    def _from_this_computer(self) -> bool:
        try:
            return ipaddress.ip_address(self.client_address[0]).is_loopback
        except ValueError:
            return False

    def _host_ok(self) -> bool:
        """DNS rebinding: a site whose name now points here still sends its own name. This computer's
        names and, on the network, address literals are accepted, on any port: a port published by
        Docker or a proxy differs from the app's own, and a port proves nothing against rebinding."""
        name, _, port = self.headers.get("Host", "").rpartition(":")
        if not name or not port.isdigit():
            return False
        if name in self.server.names:
            return True
        if not self.server.network:
            return False
        try:
            ipaddress.ip_address(name.strip("[]"))
        except ValueError:
            return False
        return True

    def _send(self, status: int, body: bytes, kind: str, extra: dict[str, str] | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status: int, data: Any) -> None:
        self._send(status, json.dumps(data, ensure_ascii=False).encode(), "application/json")

    def _error(self, status: int, message: str) -> None:
        # The request body may be unread: the connection must end, or the rest of the body would be
        # read as the next request.
        self.close_connection = True
        self._send(status, json.dumps({"error": message}).encode(), "application/json", {"Connection": "close"})

    # Routes.

    def do_OPTIONS(self) -> None:
        self._error(HTTPStatus.METHOD_NOT_ALLOWED, "cross-origin requests are not accepted")

    def do_HEAD(self) -> None:
        self.do_GET()

    def _shut(self) -> bool:
        """A request on a connection kept open through the door after it was closed."""
        if self.server.accepting:
            return False
        self.close_connection = True
        return True

    def do_GET(self) -> None:
        if self._shut():
            return
        if not self._host_ok():
            self._error(HTTPStatus.MISDIRECTED_REQUEST, "unknown host")
            return
        path = unquote(urlsplit(self.path).path)
        if "\x00" in path:
            self._error(HTTPStatus.NOT_FOUND, "not found")
            return
        if path in ("/", "/index.html"):
            self._send(
                HTTPStatus.OK,
                home_html(self.server.token).encode(),
                TYPES[".html"],
                {"Content-Security-Policy": HOME_CSP},
            )
        elif path == "/api/songs":
            state = self.server.library.state()
            state["addresses"] = self.server.lan_urls()
            state["container"] = in_container()
            state["can_upload"] = self._may_upload()
            state["network"] = {**self.server.main.network_state(), "can_switch": self._from_this_computer()}
            self._json(HTTPStatus.OK, state)
        elif path == "/api/token":
            # Read by the song pages of this server only: no CORS header, so another site's page
            # cannot read the answer, and the Host check stops DNS rebinding.
            self._json(HTTPStatus.OK, {"token": self.server.token, "boot": self.server.live.boot})
        elif path == "/api/setlist":
            self._json(HTTPStatus.OK, {"songs": self.server.library.setlist()})
        elif path == "/api/pitch":
            try:
                page = parse_qs(urlsplit(self.path).query).get("page", [""])[0]
                self._json(HTTPStatus.OK, self.server.library.pitch_state(page))
            except ValueError as exc:
                self._error(HTTPStatus.BAD_REQUEST, str(exc))
        elif path == "/api/corrections":
            query = parse_qs(urlsplit(self.path).query)
            try:
                page, key = query.get("page", [""])[0], query.get("key", [""])[0]
                grid = query.get("edits", [None])[0]
                self._json(HTTPStatus.OK, self.server.library.corrections(page, key, grid))
            except ValueError as exc:
                self._error(HTTPStatus.BAD_REQUEST, str(exc))
        elif path == "/api/live":
            given = parse_qs(urlsplit(self.path).query).get("t", [""])[0].encode("utf-8", "surrogateescape")
            site = self.headers.get("Sec-Fetch-Site", "same-origin")
            # Without the token (in the query: EventSource sends no headers), another site's page
            # could still hold the stream slots open, even though it cannot read them.
            if site not in ("same-origin", "none") or not secrets.compare_digest(given, self.server.token.encode()):
                self._error(HTTPStatus.FORBIDDEN, "missing or wrong token")
                return
            self._live_stream()
        elif path.startswith("/app/"):
            self._static(self.server.assets, path[len("/app/") :])
        else:
            self._static(self.server.library.root, path.lstrip("/"))

    def do_POST(self) -> None:
        if self._shut():
            return
        if not self._host_ok():
            self._error(HTTPStatus.MISDIRECTED_REQUEST, "unknown host")
            return
        given = self.headers.get(TOKEN_HEADER, "").encode("utf-8", "surrogateescape")
        if not secrets.compare_digest(given, self.server.token.encode()):
            self._error(HTTPStatus.FORBIDDEN, "missing or wrong token")
            return
        url = urlsplit(self.path)
        if url.path in ("/api/live", "/api/setlist", "/api/corrections", "/api/edits", "/api/band", "/api/pitch"):
            self._small_json_post(url.path)
            return
        if url.path == "/api/network":
            if not self._from_this_computer():  # a phone let in cannot let others in, or shut them out
                self._error(HTTPStatus.FORBIDDEN, "the band's network is opened from the computer that runs the app")
                return
            self._small_json_post(url.path)
            return
        if url.path == "/api/lyrics":
            if not self._may_upload():  # a minute of the speech model: like adding a song
                self._error(HTTPStatus.FORBIDDEN, "words are added from the computer that runs the app")
                return
            self._small_json_post(url.path)
            return
        if url.path == "/api/bars":
            if not self._may_upload():  # a new analysis: like adding a song
                self._error(HTTPStatus.FORBIDDEN, "the bar lines are moved from the computer that runs the app")
                return
            self._small_json_post(url.path)
            return
        if url.path != "/api/songs":
            self._error(HTTPStatus.NOT_FOUND, "no such endpoint")
            return
        if not self._may_upload():
            # On the network the band's phones lead and follow; adding songs (files up to 2 GB that
            # run the analysis) stays with the computer that runs the app.
            self._error(HTTPStatus.FORBIDDEN, "songs are added from the computer that runs the app")
            return
        query = parse_qs(url.query)
        if "chunked" in self.headers.get("Transfer-Encoding", "").lower():
            self._error(HTTPStatus.LENGTH_REQUIRED, "send the file with a Content-Length")
            return
        declared = self.headers.get("Content-Length", "")
        length = int(declared) if declared.isdigit() and len(declared) < 16 else -1
        if not 0 < length <= MAX_UPLOAD:
            self._error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "a song file must be between 1 byte and 2 GB")
            return
        if shutil.disk_usage(self.server.library.root).free < length + FREE_MARGIN:
            self._error(HTTPStatus.INSUFFICIENT_STORAGE, "not enough free disk space for this file and its tracks")
            return
        try:
            opts = self._options(query)
            target = self.server.library.reserve(query.get("name", [""])[0])
        except (WoodshedError, ValueError) as exc:
            self._error(HTTPStatus.BAD_REQUEST, str(exc))
            return
        partial = target.with_name(f".{target.name}.{secrets.token_hex(4)}.part")
        try:
            with partial.open("wb") as out:
                left = length
                while left:
                    chunk = self.rfile.read(min(CHUNK, left))
                    if not chunk:
                        raise OSError("the upload stopped early")
                    out.write(chunk)
                    left -= len(chunk)
            partial.replace(target)
        except (OSError, TimeoutError) as exc:  # a client that stops sending times out here
            partial.unlink(missing_ok=True)
            self.server.library.release(target)
            self._error(HTTPStatus.BAD_REQUEST, f"the upload did not complete ({exc})")
            return
        self.server.library.release(target)
        job = self.server.library.add(target, opts)
        self._json(HTTPStatus.ACCEPTED, asdict(job))

    def _small_json_post(self, path: str) -> None:
        declared = self.headers.get("Content-Length", "")
        length = int(declared) if declared.isdigit() and len(declared) < 8 else -1
        limits = {"/api/live": LIVE_MAX, "/api/corrections": CORRECTIONS_BYTES, "/api/lyrics": 2 * WORDS_BYTES}
        limits |= {"/api/edits": CORRECTIONS_BYTES, "/api/bars": 4096}
        limits |= {"/api/band": 4096, "/api/network": 4096, "/api/pitch": 4096}
        limit = limits.get(path, SETLIST_BYTES)
        chunked = "chunked" in self.headers.get("Transfer-Encoding", "").lower()
        if chunked or not 0 < length <= limit:
            if not chunked and limit < length <= DRAIN_MAX:
                # Read it first: closing on a client still sending resets the connection (macOS), and
                # the client never sees the answer. A few seconds at most, a piece at a time.
                left, deadline = length, time.monotonic() + 5
                with contextlib.suppress(OSError, TimeoutError):
                    while left > 0 and time.monotonic() < deadline:
                        piece = self.rfile.read1(min(left, 64 * 1024))
                        if not piece:
                            break
                        left -= len(piece)
            self._error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "a small JSON body with a Content-Length")
            return
        try:
            data = json.loads(self.rfile.read(length))
        except (ValueError, OSError, TimeoutError):
            self._error(HTTPStatus.BAD_REQUEST, "not JSON")
            return
        try:
            if path == "/api/live":
                self._json(HTTPStatus.OK, self.server.live.update(data, self.server.library.root))
            elif path == "/api/corrections":
                saved = self.server.library.set_corrections(data)
                self.server.live.corrected(data["page"], saved["rev"])
                self._json(HTTPStatus.OK, saved)
            elif path == "/api/edits":
                saved = self.server.library.set_edits(data)
                self.server.live.corrected(data["page"], saved["rev"])  # every device draws the chart again
                self._json(HTTPStatus.OK, saved)
            elif path == "/api/band":
                saved = self.server.library.set_band(data)
                self.server.live.corrected(data["page"], saved["rev"])  # every device reads the song again
                self._json(HTTPStatus.OK, saved)
            elif path == "/api/lyrics":
                self._json(HTTPStatus.ACCEPTED, asdict(self.server.library.add_words(data)))
            elif path == "/api/pitch":
                try:
                    self._json(HTTPStatus.ACCEPTED, self.server.library.ask_pitch(data))
                except pitch.Full as exc:
                    self._error(HTTPStatus.TOO_MANY_REQUESTS, str(exc))
            elif path == "/api/bars":
                self._json(HTTPStatus.ACCEPTED, asdict(self.server.library.move_bars(data, self.server.live.playing)))
            elif path == "/api/network":
                if not isinstance(data, dict) or not isinstance(data.get("on"), bool):
                    raise ValueError("on: true or false")
                self.server.main.set_door(data["on"])
                self._json(HTTPStatus.OK, self.server.main.network_state())
            else:
                self._json(HTTPStatus.OK, {"songs": self.server.library.set_setlist(data)})
        except NotLeader as exc:
            self._json(HTTPStatus.CONFLICT, {"error": str(exc), "state": exc.state})  # the body was read
        except (PermissionError, WoodshedError) as exc:
            self._error(HTTPStatus.CONFLICT, str(exc))
        except (ValueError, OSError) as exc:
            self._error(HTTPStatus.BAD_REQUEST, str(exc))

    def _live_stream(self) -> None:
        live = self.server.live
        with live.cond:
            if live.followers >= LIVE_FOLLOWERS:
                full = True
            else:
                full = False
                live.followers += 1
        if full:
            self._error(HTTPStatus.SERVICE_UNAVAILABLE, "too many devices follow the band")
            return
        self.close_connection = True  # a stream ends with its connection
        try:
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            seen = -1
            with live.cond:
                first = live.payload()
                current: tuple[int, dict[str, Any]] | None = (live.version, first)
            while not live.closed and self.server.accepting:
                if current is not None:
                    seen, shown = current
                    event = {**shown, "now": time.time()}  # the server clock, to measure the offset
                    self.wfile.write(b"data: " + json.dumps(event).encode() + b"\n\n")
                else:
                    self.wfile.write(b": ping\n\n")
                self.wfile.flush()
                version, state = live.wait(seen, LIVE_PING)
                current = None if state is None else (version, state)
        except (OSError, TimeoutError):
            pass  # the device left
        finally:
            with live.cond:
                live.followers -= 1

    def _options(self, query: dict[str, list[str]]) -> Options:
        def one(key: str) -> str | None:
            values = query.get(key)
            return values[0] if values and values[0] else None

        tempo = one("bpm")
        return self.server.library.options(
            int(one("beats_per_bar") or 4), one("sevenths") == "1", float(tempo) if tempo else None, one("separation")
        )

    def _static(self, root: Path, rel: str) -> None:
        target = (root / rel).resolve()
        if target.is_dir() and not self.path.split("?")[0].endswith("/") and target.is_relative_to(root):
            # Relative links in a page need its folder URL to end with a slash.
            self._send(HTTPStatus.MOVED_PERMANENTLY, b"", "text/plain", {"Location": urlsplit(self.path).path + "/"})
            return
        if target.is_dir():
            target = target / "index.html"
        hidden = any(part.startswith(".") for part in Path(rel).parts)
        if hidden or not target.is_relative_to(root) or not target.is_file():
            self._error(HTTPStatus.NOT_FOUND, "not found")
            return
        renders = self.server.library.renders
        if renders is not None and root == self.server.library.root:
            parts = Path(rel).parts
            if len(parts) > 4 and parts[1:3] == ("audio", pitch.KEY_DIR):
                renders.touch(parts[0], parts[3])  # a phone plays this key: never pruned under it
        kind = TYPES.get(target.suffix.lower()) or mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        size = target.stat().st_size
        start, end = 0, size - 1
        status = HTTPStatus.OK
        wanted = re.fullmatch(r"bytes=(\d{0,15})-(\d{0,15})", self.headers.get("Range", ""))
        if wanted and size and any(wanted.groups()):  # "bytes=-" and malformed ranges: the whole file
            # Audio seeking needs ranges: the browser asks for the part it plays from.
            a, b = wanted.groups()
            if a:
                start, end = int(a), min(int(b), size - 1) if b else size - 1
            elif b:
                start = max(0, size - int(b))
            if start >= size:  # starts after the end of the file
                self._send(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE, b"", kind, {"Content-Range": f"bytes */{size}"})
                return
            if start > end:  # an inverted range is ignored: the whole file
                start, end = 0, size - 1
            else:
                status = HTTPStatus.PARTIAL_CONTENT
        length = end - start + 1
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(length))
        self.send_header("Accept-Ranges", "bytes")
        if f"/audio/{pitch.KEY_DIR}/" in "/" + rel:  # a key rendered again keeps its name: never an old copy
            self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        if status == HTTPStatus.PARTIAL_CONTENT:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        if self.command == "HEAD":
            return
        with target.open("rb") as f:
            f.seek(start)
            left = length
            while left:
                chunk = f.read(min(CHUNK, left))
                if not chunk:  # the file shrank while being sent: this answer is short, end the connection
                    self.close_connection = True
                    break
                try:
                    self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError):  # the browser stopped reading
                    self.close_connection = True
                    return
                left -= len(chunk)


HOME_CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
    "connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
)


class AppServer(ThreadingHTTPServer):
    daemon_threads = True
    # On Windows SO_REUSEADDR lets a second server take a port in use, and Windows rebinds over
    # TIME_WAIT without it (as socket.create_server does).
    allow_reuse_address = os.name != "nt"

    def __init__(
        self,
        library: Library,
        host: str = "127.0.0.1",
        port: int = 0,
        uploads_from_network: bool = False,
        tls: Tls | None = None,
    ) -> None:
        # In a container every request comes through the bridge: uploads must then be allowed from
        # the network explicitly (docker run -p 127.0.0.1:8000:8000 keeps them to this computer).
        self.uploads_from_network = uploads_from_network
        # HTTPS where the phones come in: this listener when it is on the network, else the doors;
        # this computer's own 127.0.0.1 stays plain HTTP (a secure context already).
        self.tls = tls
        self.secure = tls is not None and host not in LOOPBACK
        self.untrusted_told = False
        self.live = Live()  # before binding: a taken port closes the server inside __init__
        self.doors: list[Door] = []
        self.doors_lock = threading.Lock()
        super().__init__((host, port), Handler)
        self.library = library
        library.on_bars = self.live.bars_moved
        library.on_band = self.live.corrected
        library.on_reload = self.live.page_updated
        self.network = host not in LOOPBACK
        self._addresses: list[str] | None = None
        self.token = secrets.token_urlsafe(24)
        with resources.as_file(resources.files("woodshed").joinpath("page")) as page:
            self.assets = Path(page).resolve()
        bound = self.server_address[1]
        self.port = int(bound)
        self.names = {"127.0.0.1", "localhost", "[::1]"} | ({host} if host not in ("0.0.0.0", "::") else set())
        self.names |= set(tls.names) if tls else set()  # a certificate made for mylaptop.local: that name too
        self.main = self  # the server a door belongs to: itself
        self.accepting = True

    def network_state(self) -> dict[str, Any]:
        """For the library page: are the phones let in, and can the switch change it."""
        fixed = self.network  # started on the network (--host 0.0.0.0, the Docker image): no switch
        return {"on": fixed or bool(self.doors), "fixed": fixed, "addresses": self.lan_urls()}

    def set_door(self, on: bool) -> None:
        """Let the band's phones in, on this computer's network address and the same port, or not."""
        if self.network or self.live.closed:  # on the network from the start, or stopping
            return
        with self.doors_lock:
            if on and not self.doors:
                # A home or rehearsal network: a VPN's or a tunnel's address is no way in for a phone.
                found = [a for a in lan_addresses() if _home_network(a)]
                if not found:
                    raise WoodshedError("no network found: is this computer on the band's Wi-Fi?")
                try:
                    for address in found:
                        self.doors.append(Door(self, address))
                except OSError as exc:
                    self._close_doors()
                    why = exc.strerror or exc
                    raise WoodshedError(f"the phones cannot be let in on port {self.port} ({why})") from exc
                for door in self.doors:
                    threading.Thread(target=door.serve_forever, name="woodshed-door", daemon=True).start()
                    door.started = True  # shutdown() then waits for this loop, which may not be running yet
                print(f"woodshed app: the band's phones can open {' or '.join(self.lan_urls())}", flush=True)
            elif not on and self.doors:
                self._close_doors()
                print("woodshed app: the band's phones are out", flush=True)

    def _close_doors(self) -> None:
        doors, self.doors = self.doors, []
        for door in doors:
            door.accepting = False
            if door.started:
                door.shutdown()
            door.server_close()
        if doors:
            with self.live.cond:  # the streams of the phones wake up, see the door closed and end
                self.live._changed()

    @property
    def url(self) -> str:
        return f"https://localhost:{self.port}/" if self.secure else f"http://127.0.0.1:{self.port}/"

    def get_request(self) -> tuple[socket.socket, Any]:
        sock, address = super().get_request()
        if self.secure and self.tls:
            # The handshake happens on the request's own thread, under the handler's timeout: a slow
            # or refusing phone never holds the accept loop.
            sock = self.tls.context.wrap_socket(sock, server_side=True, do_handshake_on_connect=False)
        return sock, address

    def finish_request(self, request: Any, client_address: Any) -> None:
        if isinstance(request, ssl.SSLSocket):
            # The handshake first, on this request's thread: only a refused one is a device that does not
            # trust the certificate (a phone leaving mid-request is not).
            request.settimeout(Handler.timeout)
            try:
                request.do_handshake()
            except ssl.SSLError as exc:
                if not isinstance(exc, (ssl.SSLEOFError, ssl.SSLZeroReturnError)):
                    self._untrusted()
                return
            except OSError:
                return  # gone before it said anything
        super().finish_request(request, client_address)

    def _untrusted(self) -> None:
        main = self.main
        if not main.untrusted_told:  # said once: the organiser has a phone to set up, not a log to read
            main.untrusted_told = True
            print(
                "woodshed app: a device does not trust the certificate yet, or opened an http:// address: "
                "install the certificate's root on it (docs/guide/phones.md: HTTPS for the phones)",
                file=sys.stderr,
                flush=True,
            )

    def handle_error(self, request: Any, client_address: Any) -> None:
        # A phone gone mid-request (reset, aborted on Windows, broken pipe, a TLS session cut): no traceback.
        if isinstance(sys.exc_info()[1], (ssl.SSLError, ConnectionError, TimeoutError)):
            return
        super().handle_error(request, client_address)

    def lan_urls(self) -> list[str]:
        """The addresses the phones type, looked up once (a name lookup can take seconds)."""
        scheme = "https" if self.tls else "http"
        if self.doors:
            return [f"{scheme}://{door.address}:{self.port}/" for door in self.doors]
        if not self.network:
            return []
        if self._addresses is None:
            self._addresses = (
                public_urls()
                if os.environ.get("WOODSHED_PUBLIC_URL")
                else ([] if in_container() else [f"{scheme}://{a}:{self.port}/" for a in lan_addresses()])
            )
        return self._addresses

    def server_close(self) -> None:
        with self.doors_lock:
            self._close_doors()
        self.live.close()  # open streams end
        super().server_close()


class Door(AppServer):
    """The library on this computer's network address: the phones' way in, opened from the page.

    The same library, token and band as the server on 127.0.0.1, on the same port. Address
    literals are accepted as Host (the phones type one) and nothing is uploaded through it.
    """

    def __init__(self, main: AppServer, address: str) -> None:
        self.main = main
        self.address = address
        self.accepting = True
        self.started = False
        self.tls = main.tls
        self.secure = main.tls is not None
        ThreadingHTTPServer.__init__(self, (address, main.port), Handler)
        self.library, self.live, self.token, self.assets = main.library, main.live, main.token, main.assets
        self.uploads_from_network = False  # the phones play, lead and follow; songs come from this computer
        self.port = main.port
        self.names = main.names
        self.network = True
        self.doors = []

    def server_bind(self) -> None:
        # HTTPServer.server_bind asks the DNS for this address's name: seconds on some routers.
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = self.address, int(self.server_address[1])

    def lan_urls(self) -> list[str]:
        return self.main.lan_urls()

    def server_close(self) -> None:
        ThreadingHTTPServer.server_close(self)  # the band's stream belongs to the main server


def running_here(port: int) -> bool:
    """Is woodshed already answering on this port (opened twice from the menu or the Dock)?"""
    return running_url(port) is not None


def running_url(port: int) -> str | None:
    """The address of the woodshed answering on this port, over HTTP or HTTPS (--cert), if one does."""
    import urllib.error
    import urllib.request

    this_computer = ssl.create_default_context()
    this_computer.check_hostname = False  # 127.0.0.1 asking itself: the certificate is for the phones
    this_computer.verify_mode = ssl.CERT_NONE

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args: Any, **kwargs: Any) -> None:
            return None  # woodshed answers itself: another service's redirect is not followed

    handlers = (urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=this_computer), NoRedirect())
    no_proxy = urllib.request.build_opener(*handlers)  # this computer, never a proxy
    # HTTPS first: a plain server answers a TLS hello with a quiet 400, while a plain request on a TLS
    # listener would count as a device that does not trust the certificate.
    for url in (f"https://localhost:{port}/", f"http://127.0.0.1:{port}/"):
        try:
            with no_proxy.open(url.replace("localhost", "127.0.0.1") + "api/token", timeout=1.5) as answer:
                if isinstance(json.loads(answer.read(4096)).get("token"), str):
                    return url
        except urllib.error.HTTPError as exc:  # another service answered: its answer is closed, not woodshed
            exc.close()
        except (OSError, ValueError, AttributeError, http.client.HTTPException):
            pass
    return None


def serve(
    root: Path,
    opts: Options,
    host: str = "127.0.0.1",
    port: int = 8000,
    open_browser: bool = True,
    uploads_from_network: bool = False,
    tls: tuple[Path, Path] | None = None,
) -> None:
    import webbrowser

    from woodshed import tls as tls_files

    secure = tls_files.load(*tls, root) if tls else None  # before anything starts: a wrong file is said at once

    if host not in LOOPBACK:
        # The token stops other web sites, not other devices: anyone who can reach the port reads
        # the home page and its token. For the band's phones on the rehearsal Wi-Fi, or a container
        # published on 127.0.0.1 (with uploads allowed from the network: the bridge is not loopback).
        uploads = "anyone can add songs" if uploads_from_network else "songs are added from this computer only"
        if in_container():
            # The bridge address says nothing about who can reach the app: the published port does.
            print(
                f"woodshed app: listening inside the container; the port published in compose.yaml decides who "
                f"can reach it ({uploads})",
                flush=True,
            )
        else:
            print(
                f"woodshed app: listening on {host}: every device on this network can open the library, play it "
                f"and lead the band ({uploads})",
                flush=True,
            )

    def stop(signum: int, frame: Any) -> None:
        raise KeyboardInterrupt  # docker stop sends SIGTERM: stop as on Ctrl-C

    previous = signal.signal(signal.SIGTERM, stop)
    library: Library | None = None
    server: AppServer | None = None
    try:  # a stop at any point, start included, leaves the songs in progress to resume
        library = Library(root, opts)
        try:
            server = AppServer(library, host, port, uploads_from_network, tls=secure)
        except OSError as exc:
            if exc.errno not in (errno.EADDRINUSE, 10048) or not running_here(port):  # 10048: Windows
                raise
            # Started again while it runs (the menu, the Dock): the running one is shown, and this
            # one touches nothing of the library (`finally` below has no library to stop).
            library = None
            url = running_url(port) or f"http://127.0.0.1:{port}/"
            print(f"woodshed app: already running at {url}", flush=True)
            if open_browser:
                webbrowser.open(url)
            return
        library.clear_cut_uploads()
        library.clear_notes_out_of_the_set()
        updated = library.update_pages()
        if updated:
            print(f"woodshed app: {len(updated)} page(s) updated to this version's page", flush=True)
        for job in library.resume():
            print(f"woodshed app: {job.name}: {job.message or 'resumed'}", flush=True)
        measured = library.measure_voices()  # in the background, after the songs resumed
        if measured:
            print(f"woodshed app: {len(measured)} page(s) get the voice range per key, in the background", flush=True)
        print(f"woodshed app: {server.url}  (library: {library.root}; Ctrl-C to stop)", flush=True)
        if open_browser:
            webbrowser.open(server.url)
        server.serve_forever()
    finally:
        if library is not None:
            library.interrupted()
            shutil.rmtree(library.songs / ".tmp", ignore_errors=True)
        if server is not None:
            server.server_close()
        signal.signal(signal.SIGTERM, previous)
