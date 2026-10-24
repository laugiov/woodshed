"""A page's corrections in a library (`.corrections/<page>.json`): the chords picked by ear, the typed bars and
parts, the band's key and note, and the words fixed on the sheet. Read, checked and written here, under a lock
shared by every woodshed on the library (the app, `woodshed lyrics`, a rebuild of the page)."""

from __future__ import annotations

import contextlib
import json
import math
import re
import secrets
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from woodshed import chords as chord_grammar
from woodshed.errors import WoodshedError

CORRECTIONS_MAX = 2000  # chords picked by ear on one page: more than any song has doubts
WORDS_BYTES = 32 * 1024  # the pasted words of one song: a long song is 3 KB
QUALITIES = ("", "m", "7", "m7")
CORRECTIONS_DIR = ".corrections"  # in the library: one file per page, never served
CORRECTIONS_KEYS = 8  # analyses of one song kept (each rebuild with a new analysis is one)
KNOWN_SECTIONS = {
    "rev",
    "by_key",
    "band",
    "edits",
    "words",
    "words_more",
}  # of a corrections file; any other is kept as it is
LOCK_WAIT = 10.0  # seconds a write waits for another woodshed (the app, `woodshed lyrics`) writing the same file
NOTE_MAX = 300  # the leader's note on a song: "capo 2, starts on the chorus"
DOUBT_ID = re.compile(r"[A-Za-z0-9_-]{1,32}")
EDITS_BARS_MAX = 1000
EDITS_PARTS_MAX = 200
EDIT_CHORDS_MAX = 64  # chords in one typed bar
LABEL_MAX = 24
PART_NAME_MAX = 40  # code points
BEAT_INDEX = re.compile(r"0|-?[1-9][0-9]{0,5}")  # one spelling a beat: no 007, no -0
UNSAFE = re.compile("[\x00-\x1f\x7f\u202a-\u202e\u2066-\u2069]")  # control and direction overrides
KEY_NAME = re.compile(r"[A-G][#b]?m?")  # a key as the page names it, written by the device that chose it
LINE_INDEX = re.compile(r"0|[1-9][0-9]{0,3}")
WORD_FIXES_MAX = 500  # lines fixed on one placement: more than any song has lines
WORD_TEXT_MAX = 200  # code points of one line
LINE_WORDS_MAX = 40
LINE_PIECES_MAX = 4  # a line split on the sheet: four lines at most, and as many lines joined into one


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


def read_corrections(path: Path) -> dict[str, Any]:
    """What the library holds for a page (`.corrections/<page>.json`); an entry damaged by hand is skipped, the
    others kept, and a section this version does not know (a newer woodshed's) kept as it is for the next write."""
    out: dict[str, Any] = {"rev": 0, "by_key": {}, "at": {}, "band": {}, "removed": {}, "edits": {}, "words": {}}
    out["other"] = {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return out
    if not isinstance(data, dict):
        return out
    out["other"] = {k: v for k, v in data.items() if k not in KNOWN_SECTIONS}
    # A known section in a shape this version cannot read is kept as it is too, not dropped by the next write.
    out["other"] |= {k: data[k] for k in ("by_key", "edits", "words") if k in data and not isinstance(data[k], dict)}
    rev = data.get("rev")
    out["rev"] = rev if type(rev) is int and rev >= 0 else 0
    try:
        out["band"] = _checked_band(data.get("band") or {})
    except ValueError:
        out["other"]["band"] = data["band"]
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
    out["words_raw"] = {}
    fixed = data.get("words")
    more: dict[str, Any] = data["words_more"] if isinstance(data.get("words_more"), dict) else {}
    for key, entry in fixed.items() if isinstance(fixed, dict) else []:
        if not isinstance(entry, dict) or not re.fullmatch(r"[A-Za-z0-9]{1,64}", str(key)):
            continue
        whole: dict[str, Any] = more[key] if isinstance(more.get(key), dict) else {}
        found: dict[str, dict[str, Any]] = {"lines": {}, "removed": {}}
        raw: dict[str, dict[str, Any]] = {"lines": {}, "removed": {}}
        for part in ("lines", "removed"):
            given: dict[str, Any] = entry[part] if isinstance(entry.get(part), dict) else {}
            fuller: dict[str, Any] = whole[part] if isinstance(whole.get(part), dict) else {}
            wanted = _whole(given, fuller, joins=part == "lines")
            for k, v in given.items():
                if not (isinstance(k, str) and LINE_INDEX.fullmatch(k)):
                    continue
                if part == "removed" and v is None:
                    found[part][k] = None
                    continue
                if k not in wanted:
                    continue  # a joined line's "not sung", let go with the join (_whole)
                try:
                    found[part][k] = _checked_word_entry(k, wanted[k])
                except (ValueError, KeyError, TypeError, AttributeError):
                    raw[part][k] = v  # damaged by hand, or a newer woodshed's: not shown, kept for the next write
        at = entry.get("at", 0)
        out["words"][key] = {**found, "at": float(at) if _number(at) else 0.0}
        if raw["lines"] or raw["removed"]:
            out["words_raw"][key] = raw
    return out


def _whole(given: dict[str, Any], fuller: dict[str, Any], joins: bool) -> dict[str, Any]:
    """The entries of `words` with the splits and joins of `words_more` back: each only while its `words` entry is
    still the one written with it (else an older woodshed changed it, and its change wins). A join comes back whole
    or not at all: the line it went to and every line joined into it unchanged; if the older woodshed took a joined
    line back (or changed it), the line it went to gets the fix it had before the join and the joined lines it did
    not touch are the placement's again; if it changed the line the join went to, every line stays as it wrote it."""
    out = dict(given)
    same = {k for k, full in fuller.items() if k in given and older_word_entry(full) == given[k]}
    done: set[str] = set()
    for owner in sorted((k for k in fuller if k.isdigit()), key=int) if joins else []:
        full = fuller[owner]
        if not (isinstance(full, dict) and "unjoined" in full):
            continue
        held, j = [], int(owner) + 1
        while isinstance(fuller.get(str(j)), dict) and fuller[str(j)].get("gone") == "joined":
            held.append(str(j))
            j += 1
        done |= {owner, *held}
        if owner not in same:
            continue  # the line it went to changed there: every line as the older woodshed left it
        if all(k in same for k in held):
            out.update({k: fuller[k] for k in (owner, *held)})
            continue
        if full["unjoined"] is None:
            out.pop(owner, None)
        else:
            out[owner] = full["unjoined"]
        for k in held:
            if k in same:
                out.pop(k, None)
    for k in same - done:
        if not (joins and isinstance(fuller[k], dict) and fuller[k].get("gone") == "joined"):
            out[k] = fuller[k]
    return out


def older_word_entry(entry: Any) -> Any:
    """A fix of the words as woodshed 0.5.1 reads it (one line, or not sung), what the file's `words` holds: a
    split line as one line (its first row past 0.5.1's limits), a line joined into the one before as not sung (so
    its words are never shown twice), without the fix the line had before a join. The whole of it goes in
    `words_more`, a section 0.5.1 keeps as it is."""
    if not isinstance(entry, dict):
        return entry
    if entry.get("gone") == "joined":
        return {"was": entry.get("was"), "gone": "not-sung"}
    out = {k: v for k, v in entry.items() if k != "unjoined"}
    rows = out.get("lines")
    if isinstance(rows, list) and len(rows) > 1 and all(isinstance(r, dict) for r in rows):
        # A split line as one line, every row's words in it, when 0.5.1's limits allow; else its first row.
        words = [w for r in rows for w in r.get("words") or []]
        text = " ".join(str(r.get("text", "")) for r in rows)
        if len(words) <= LINE_WORDS_MAX and len(text) <= WORD_TEXT_MAX:
            backing = [b for r in rows for b in r.get("backing") or []]
            check = next((r.get("check") for r in rows if r.get("check")), None)
            out["lines"] = [{"text": text, "backing": backing, "words": words, "check": check}]
        else:
            out["lines"] = rows[:1]
    return out


@contextlib.contextmanager
def corrections_lock(path: Path) -> Iterator[None]:
    """One writer at a time for a page's corrections, across processes: the library app and `woodshed lyrics` on
    the same library read, change and write the file inside it (a lock file beside it, locked by the system and let
    go if the process dies). A writer that waits LOCK_WAIT seconds in vain is refused with a sentence."""
    path.parent.mkdir(exist_ok=True)
    with path.with_name(path.name + ".lock").open("a+b") as fh:
        deadline = time.monotonic() + LOCK_WAIT
        while not _lock_file(fh):
            if time.monotonic() > deadline:
                raise WoodshedError("another woodshed is writing the corrections of this song: try again")
            time.sleep(0.05)
        try:
            yield
        finally:
            _unlock_file(fh)


def _lock_file(fh: Any) -> bool:
    try:
        if sys.platform == "win32":
            import msvcrt

            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    return True


def _unlock_file(fh: Any) -> None:
    if sys.platform == "win32":
        import msvcrt

        fh.seek(0)
        msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def write_corrections(path: Path, stored: dict[str, Any], seen: int = 0) -> int:
    """A page's corrections and band choices written whole (`stored` as read_corrections gives it), with the next
    revision (past `seen`, the last one this library told). Every section is written back, a newer woodshed's too."""
    rev: int = max(stored["rev"], seen) + 1  # kept in the file: grows across restarts
    body: dict[str, Any] = dict(stored.get("other") or {})
    body["rev"] = rev
    if stored["by_key"] or "by_key" not in body:  # one this version could not read is kept until it has its own
        body["by_key"] = {
            k: {
                "fixes": v,
                "at": stored["at"][k],
                **({"removed": r} if (r := stored["removed"].get(k)) else {}),
            }
            for k, v in stored["by_key"].items()
        }
    for name in ("band", "edits"):
        if stored.get(name):
            body[name] = stored[name]
    if stored.get("words"):
        body["words"], more = _words_body(stored["words"], stored.get("words_raw") or {})
        if more:
            body["words_more"] = more
    path.parent.mkdir(exist_ok=True)
    tmp = path.with_name(f".{path.name}.{secrets.token_hex(4)}")
    try:
        tmp.write_text(json.dumps(body, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)
    return rev


def _words_body(words: dict[str, Any], raw: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """The words fixed on the sheet as the file keeps them: `words` readable by woodshed 0.5.1 (older_word_entry),
    `words_more` the splits and joins whole; the entries this version could not read written back as they were,
    unless the line was fixed or taken back here since."""
    body: dict[str, Any] = {}
    more: dict[str, Any] = {}
    for key, entry in words.items():
        out: dict[str, dict[str, Any]] = {"lines": {}, "removed": {}}
        whole: dict[str, dict[str, Any]] = {"lines": {}, "removed": {}}
        for part in ("lines", "removed"):
            for k, v in entry[part].items():
                out[part][k] = older_word_entry(v)
                if out[part][k] != v:
                    whole[part][k] = v
        kept = raw.get(key) or {}
        for part in ("lines", "removed"):
            for k, v in (kept.get(part) or {}).items():
                if k not in entry["lines"] and k not in entry["removed"]:
                    out[part][k] = v
        body[key] = {**out, "at": entry["at"]}
        if whole["lines"] or whole["removed"]:
            more[key] = whole
    return body, more


def songbook_of(page: Path, song: dict[str, Any], data: dict[str, Any], folder: Path) -> None:
    """The songbook file of a page (`folder`: its exports) with the words `data` and the band's fixes of them, read
    and written holding the page's corrections lock: a fix saved meanwhile is waited for, then written too. A page
    out of a library (no corrections file) gets the words as placed."""
    from woodshed import exports, lyrics

    path = page.parent / CORRECTIONS_DIR / f"{page.name}.json"
    if not path.is_file():
        exports.write_chordpro(song, folder, data)
        return
    with corrections_lock(path):
        fixed = read_corrections(path)["words"].get(lyrics.words_key(data), {}).get("lines", {})
        exports.write_chordpro(song, folder, lyrics.apply_edits(data, fixed))


def _number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _checked_word_entry(k: Any, v: Any) -> dict[str, Any]:
    """A fix of the words as the library keeps it: the placement's text (`was`), then the line's words and
    times placed by the library, another voice, or not in this recording."""
    if not isinstance(k, str) or not LINE_INDEX.fullmatch(k) or not isinstance(v, dict):
        raise ValueError("a line fix by index")
    was = v.get("was")
    if not isinstance(was, str) or len(was) > 4 * WORDS_BYTES:
        raise ValueError("was: the placement's text")
    if set(v) == {"was", "gone"} and v["gone"] in ("not-sung", "joined"):
        return {"was": was, "gone": v["gone"]}
    if not set(v) <= {"was", "lines", "voice", "unjoined"} or len(v) < 2 or v.get("voice", "other") != "other":
        raise ValueError("a line fix")
    out: dict[str, Any] = {"was": was}
    unjoined: Any = None
    if "unjoined" in v:  # the fix the line had before lines were joined into it (spec 028 B), or none
        if "lines" not in v or (v["unjoined"] is not None and "unjoined" in v["unjoined"]):
            raise ValueError("unjoined: the line's fix before a join")
        unjoined = None if v["unjoined"] is None else _checked_word_entry(k, v["unjoined"])
    if "lines" in v:
        fixed = v["lines"]
        if not isinstance(fixed, list) or not 0 < len(fixed) <= LINE_PIECES_MAX:  # more than one: a split
            raise ValueError("lines: one to four lines")
        out["lines"] = []
        for line in fixed:
            text, words, check, backing = line["text"], line["words"], line.get("check"), line.get("backing", [])
            if not isinstance(text, str) or len(text) > WORD_TEXT_MAX or not isinstance(words, list):
                raise ValueError("lines: words")
            if not 0 < len(words) <= LINE_WORDS_MAX or not (
                check is None or (isinstance(check, str) and len(check) < 200)
            ):
                raise ValueError("lines: words")
            if not isinstance(backing, list) or not all(
                isinstance(b, str) and len(b) <= WORD_TEXT_MAX for b in backing
            ):
                raise ValueError("lines: backing vocals")
            kept = []
            for w in words:
                start, end = w["start"], w["end"]
                timed = _number(start) and _number(end) and 0 <= start <= end < 86400
                text_ok = isinstance(w["text"], str) and len(w["text"]) <= WORD_TEXT_MAX
                if not text_ok or not (timed or start is end is None):
                    raise ValueError("lines: words in time")
                kept.append({"text": w["text"], "start": start, "end": end})
            out["lines"].append({"text": text, "backing": list(backing), "words": kept, "check": check})
    if "voice" in v:
        out["voice"] = "other"
    if "unjoined" in v:  # last, as the library answers it: a page compares the two as written
        out["unjoined"] = unjoined
    return out
