"""Exports of a song, from its JSON (song.schema.json): ChordPro, MIREX .lab, MIDI and MusicXML.

They read the published song format, not the analysis objects, so a page's own data (with the
listener's corrections) can be exported the same way.
"""

from __future__ import annotations

import bisect
import itertools
import json
import math
import re
import struct
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from woodshed import theory

Song = dict[str, Any]
LAB_QUALITY = {"": "maj", "m": "min", "7": "7", "m7": "min7"}
PPQ = 480  # MIDI ticks per beat
STEM_SLOTS = 4  # sixteenths per beat in the parts


CONTROL = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def directive_text(text: str) -> str:
    """Text inside a ChordPro directive: one line, no braces (they would end the directive)."""
    return CONTROL.sub("", re.sub(r"[\r\n]+", " ", text)).replace("{", "(").replace("}", ")")


def xml_text(text: str) -> str:
    """Text for XML 1.0: control characters removed, markup escaped."""
    return escape(CONTROL.sub("", text))


def half_up(x: float) -> int:
    """Rounding as the page does it (JavaScript's Math.round), for identical exports."""
    return math.floor(x + 0.5)


def _key(song: Song) -> theory.Key:
    return theory.Key(song["key"]["pc"], song["key"]["mode"])


class Keys:
    """The key of every bar (spec 012): the song's key regions, the first at bar 0."""

    def __init__(self, song: Song) -> None:
        regions = song.get("key_regions") or [{"bar": 0, **song["key"]}]
        self.starts = [int(r["bar"]) for r in regions]
        self.keys = [theory.Key(r["pc"], r["mode"]) for r in regions]

    def region(self, u: int) -> int:
        return max(0, bisect.bisect_right(self.starts, u) - 1)

    def at(self, u: int) -> theory.Key:
        return self.keys[self.region(u)]


def key_name(key: theory.Key) -> str:
    return theory.spell(key.tonic, key) + ("" if key.mode == "maj" else "m")


def _name(chord: dict[str, Any], key: theory.Key) -> str:
    return "N.C." if chord["pc"] < 0 else theory.chord_name(chord["pc"], chord["quality"], key)


def beat_time(song: Song, b: float) -> float:
    """Time of beat b counted from the first bar's beat one (extrapolated outside the tracked beats)."""
    beats = song["beats"]
    i = song["first_beat"] + b
    n = len(beats)
    if 0 <= i <= n - 1 and float(i).is_integer():
        return float(beats[int(i)])
    lo = min(max(int(i), 0), n - 2)
    return float(beats[lo] + (i - lo) * (beats[lo + 1] - beats[lo]))


def chord_spans(song: Song) -> list[tuple[int, int, dict[str, Any]]]:
    """(first beat, beats, chord) for every chord, in beats from the first bar's beat one."""
    out = []
    per = song["beats_per_bar"]
    for u, bar in enumerate(song["bars"]):
        b = u * per
        for c in bar["chords"]:
            out.append((b, c["beats"], c))
            b += c["beats"]
    return out


# ChordPro: the chart for songbook apps. Each part under its name; a sung part as its words with
# each chord on the word it lands on, a part without words as a grid of its bars. A chord to check is
# not marked in its name (songbook apps would read "E?" as a chord): the bars are listed in a comment.

ENVIRONMENT = {"chorus": "chorus", "bridge": "bridge"}  # the other sung parts are verses in ChordPro


def lyric_text(text: str) -> str:
    """Words as ChordPro reads them: a brace would open a directive, so braces become parentheses."""
    return CONTROL.sub("", text).replace("{", "(").replace("}", ")")


def lyric_row(row: str) -> str:
    """A row starting with # would be a ChordPro comment: a space before it keeps it a lyric."""
    return " " + row if row.startswith("#") else row


def _cells(song: Song, u: int, keys: Keys) -> str:
    cells: list[str] = []
    for c in song["bars"][u]["chords"]:
        cells += [_name(c, keys.at(u))] + ["."] * (c["beats"] - 1)
    return " ".join(cells)


def _grid(song: Song, label: str, rows: list[tuple[list[int], int]], keys: Keys) -> list[str]:
    """A grid: rows of bars, each played `times` times."""
    out = ['{start_of_grid: label="' + directive_text(label).replace('"', "'") + '"}']
    for bars, times in rows:
        text = " | ".join(_cells(song, u, keys) for u in bars)
        out.append("|: " + text + " :|" + (f" x{times}" if times > 2 else "") if times > 1 else "| " + text + " |")
    out.append("{end_of_grid}")
    return out


def _rows(song: Song, bars: list[int], keys: Keys) -> list[tuple[list[int], int]]:
    """Bars four a row; the same row again is a repeat."""
    rows: list[tuple[list[int], int]] = []
    for i in range(0, len(bars), 4):
        row = bars[i : i + 4]
        if rows and [_cells(song, u, keys) for u in rows[-1][0]] == [_cells(song, u, keys) for u in row]:
            rows[-1] = (rows[-1][0], rows[-1][1] + 1)
        else:
            rows.append((row, 1))
    return rows


def bar_list(bars: list[int]) -> str:
    """Bar numbers as a musician reads them: "bar 3", "bars 18-19, 23"."""
    spans: list[list[int]] = []
    for b in sorted(set(bars)):
        if spans and b == spans[-1][1] + 1:
            spans[-1][1] = b
        else:
            spans.append([b, b])
    text = ", ".join(str(a) if a == z else f"{a}-{z}" for a, z in spans)
    return ("bar " if len(spans) == 1 and spans[0][0] == spans[0][1] else "bars ") + text


def _to_check(song: Song, sections: list[dict[str, Any]], keys: Keys) -> str:
    """The chords to check by ear, by part with its bars ("Chorus 1, bars 18-19 (D#m, C#)"). Without
    parts, by bar."""
    doubtful = [
        (u, c)
        for u, bar in enumerate(song["bars"])
        for c in bar["chords"]
        if c.get("doubt") and c["doubt"].get("kind", "chord") == "chord"
    ]
    if not doubtful:
        return ""
    if not sections:
        bars = list(dict.fromkeys(u + 1 for u, _ in doubtful))
        return ("bar " if len(bars) == 1 else "bars ") + ", ".join(map(str, bars))
    parts: dict[str, tuple[list[int], list[str]]] = {}
    for u, c in doubtful:
        sec = next((s for s in sections if s["start"] <= u < s["end"]), None)
        part = sec["name"] if sec else "outside the parts"
        bars, names = parts.setdefault(part, ([], []))
        bars.append(u + 1)
        if _name(c, keys.at(u)) not in names:
            names.append(_name(c, keys.at(u)))
    return ", ".join(f"{part}, {bar_list(bars)} ({', '.join(names)})" for part, (bars, names) in parts.items())


def _sung(
    song: Song, words: dict[str, Any] | None, sections: list[dict[str, Any]], keys: Keys
) -> dict[int, list[str]]:
    """The rows of each sung section: its lines with the chords on their words, and the chords
    between lines on rows of their own. Placed as the page places them (lyrics.place_chords).
    Between lines only the changes are written: bars held on one chord are not counted there."""
    from woodshed import lyrics

    lines = (words or {}).get("lines") or []

    def has_time(w: dict[str, Any]) -> bool:  # a start and an end, as the page reads a word
        return isinstance(w.get("start"), (int, float)) and isinstance(w.get("end"), (int, float))

    timed = {
        li: [(w["start"], w["end"]) if has_time(w) else (math.nan, math.nan) for w in line["words"]]
        for li, line in enumerate(lines)
        if line.get("sung") and any(has_time(w) for w in line["words"])
    }
    if not timed or not sections:
        return {}
    changes = lyrics.chord_changes(song)
    placed = lyrics.place_chords(changes, timed, float(song["bpm"]), int(song["beats_per_bar"]))
    starts = lyrics.bar_starts(song)
    bar_time = 60 / float(song["bpm"]) * int(song["beats_per_bar"])
    half_bar = bar_time / 2
    first_bars = [sec["start"] for sec in sections]

    def section_of_bar(u: int) -> int:
        return max(0, bisect.bisect_right(first_bars, u) - 1)

    def name(p: dict[str, Any]) -> str:
        return "[" + _name(song["bars"][p["bar"]]["chords"][p["index"]], keys.at(p["bar"])) + "]"

    def chord_rows(ps: list[dict[str, Any]]) -> list[str]:
        """Chords with no word of their own: bar by bar, four bars a row, never one long row."""
        bars: list[list[str]] = []
        last = None
        for p in ps:
            if p["bar"] != last:
                bars.append([])
                last = p["bar"]
            bars[-1].append(name(p))
        # Framed by bar lines, as every chord row: "| [D] | [C#m] [E] |".
        return ["| " + " | ".join(" ".join(b) for b in bars[i : i + 4]) + " |" for i in range(0, len(bars), 4)]

    begin = {li: min(s for s, _ in ws if s == s) for li, ws in timed.items()}
    finish = {li: max(e for _, e in ws if e == e) for li, ws in timed.items()}
    by_section: dict[int, list[int]] = {}
    for li in sorted(timed, key=lambda li: (begin[li], li)):
        u = max(0, bisect.bisect_right(starts, begin[li] + half_bar) - 1)
        by_section.setdefault(section_of_bar(u), []).append(li)
    gaps: dict[int, list[tuple[float, dict[str, Any]]]] = {}
    on_word: dict[tuple[int, int], list[dict[str, Any]]] = {}
    for (t, _, _), p in zip(changes, placed, strict=True):
        if p["line"] is None:
            gaps.setdefault(section_of_bar(p["bar"]), []).append((t, p))
        else:
            on_word.setdefault((p["line"], p["word"]), []).append(p)

    out: dict[int, list[str]] = {}
    for k, ids in by_section.items():
        rows: list[str] = []
        waiting = list(gaps.get(k, []))
        for li in ids:
            # Chords before the line: those of the bar leading into it go on its first word.
            lead = [p for t, p in waiting if begin[li] - bar_time <= t < begin[li]]
            before = [p for t, p in waiting if t < begin[li] - bar_time]
            rows += chord_rows(before)
            inside = [(t, p) for t, p in waiting if begin[li] <= t < finish[li]]
            waiting = [(t, p) for t, p in waiting if t >= finish[li]]
            tokens: list[str] = []
            for wi, w in enumerate(lines[li]["words"]):
                start = timed[li][wi][0]
                ahead = [p for t, p in inside if start == start and t <= start]
                inside = [(t, p) for t, p in inside if not (start == start and t <= start)]
                chords = (lead if wi == 0 else []) + ahead + on_word.get((li, wi), [])
                # One chord a word. Those before it go on a chord row of their own: above the line for
                # its first word; for a later word the line breaks there (they change while the word
                # before it is held).
                if chords[:-1] and tokens:
                    rows.append(lyric_row(" ".join(tokens)))
                    tokens = []
                rows += chord_rows(chords[:-1])
                tokens.append((name(chords[-1]) if chords else "") + lyric_text(w["text"]))
            tokens += [name(p) for _, p in inside]
            backing = lines[li].get("backing") or []
            rows.append(lyric_row(" ".join(tokens) + "".join(f" ({lyric_text(b)})" for b in backing)))
        rows += chord_rows([p for _, p in waiting])
        out[k] = rows
    return out


def transposed(song: Song, semitones: int) -> Song:
    """The song as played `semitones` higher (lower if negative): every chord, its doubt's
    candidates and the key move; the timing stays."""
    if semitones % 12 == 0:
        return song

    def up(c: dict[str, Any]) -> dict[str, Any]:
        return {**c, "pc": c["pc"] if c["pc"] < 0 else (c["pc"] + semitones) % 12}

    def chord(c: dict[str, Any]) -> dict[str, Any]:
        doubt = c.get("doubt")
        if doubt and doubt.get("alternatives"):
            doubt = {**doubt, "alternatives": [up(a) for a in doubt["alternatives"]]}
        return {**up(c), **({"doubt": doubt} if "doubt" in c else {})}

    bars = [{**b, "chords": [chord(c) for c in b["chords"]]} for b in song["bars"]]
    regions = [{**r, "pc": (r["pc"] + semitones) % 12} for r in song.get("key_regions") or []]
    moved = {**song, "bars": bars, "key": {**song["key"], "pc": (song["key"]["pc"] + semitones) % 12}}
    return {**moved, "key_regions": regions} if "key_regions" in song else moved


def chordpro(song: Song, words: dict[str, Any] | None = None, transpose: int = 0) -> str:
    """The song in ChordPro; with the words placed on it (lyrics.json), each chord on its word. With
    `transpose`, in the key the band plays (the page exports in the key it shows)."""
    song = transposed(song, transpose)
    keys = Keys(song)
    per = song["beats_per_bar"]
    lines = [
        "{title: " + directive_text(song["title"]) + "}",
        "{key: " + key_name(keys.keys[0]) + "}",
        "{tempo: " + str(half_up(song["bpm"])) + "}",
        "{time: " + f"{per}/4" + "}",
        "{comment: chords found by woodshed from " + directive_text(song["file"]) + "}",
    ]
    from woodshed import lyrics

    named = lyrics.fitting_sections((words or {}).get("sections"), len(song["bars"]))
    sections = named or list(song.get("sections") or [])
    check = _to_check(song, sections, keys)
    if check:
        lines.append("{comment: check by ear: " + directive_text(check) + "}")
    # A key change is announced where it happens (spec 012): before the part (or the line of a grid) it starts.
    said = [0]

    def announce(region: int) -> list[str]:
        if region == said[0]:
            return []
        said[0] = region
        return ["{key: " + key_name(keys.keys[region]) + "}"]

    if not sections:  # no parts named: the chart's lines and their repeats
        for group in song["groups"]:
            rows = [(group["occurrences"][0], len(group["occurrences"]))]
            lines += ["", *announce(keys.region(group["occurrences"][0][0])), *_grid(song, group["label"], rows, keys)]
        return "\n".join(lines) + "\n"
    sung = _sung(song, words, sections, keys)
    for k, sec in enumerate(sections):
        lines.append("")
        bars = list(range(sec["start"], sec["end"]))
        if k in sung:  # a change inside sung lines is said before the part
            lines += announce(keys.region(sec["end"] - 1))
            env = ENVIRONMENT.get(sec["role"], "verse")
            lines.append(f'{{start_of_{env}: label="' + directive_text(sec["name"]).replace('"', "'") + '"}')
            lines += sung[k]
            lines.append(f"{{end_of_{env}}}")
            continue
        # A grid splits at the bar where the key changes, the same label on both sides.
        cuts = [u for u in bars[1:] if keys.region(u) != keys.region(u - 1)]
        for piece in (bars[a:b] for a, b in itertools.pairwise([0, *(u - sec["start"] for u in cuts), len(bars)])):
            lines += announce(keys.region(piece[0]))
            lines += _grid(song, sec["name"], _rows(song, piece, keys), keys)
    return "\n".join(lines) + "\n"


# MIREX .lab: start, end and chord label, the format of chord-recognition evaluations.


def lab(song: Song) -> str:
    rows: list[tuple[float, float, str]] = []
    for b, n, c in chord_spans(song):
        label = "N" if c["pc"] < 0 else theory.SHARP_NAMES[c["pc"]] + ":" + LAB_QUALITY[c["quality"]]
        duration = float(song["duration"])
        start, end = max(0.0, beat_time(song, b)), min(duration, beat_time(song, b + n))
        if start >= duration:
            break
        if rows and rows[-1][2] == label:
            rows[-1] = (rows[-1][0], end, label)
        else:
            rows.append((start, end, label))
    if rows and rows[0][0] > 0:
        rows.insert(0, (0.0, rows[0][0], "N"))
    if rows and rows[-1][1] < song["duration"]:
        rows.append((rows[-1][1], float(song["duration"]), "N"))
    return "".join(f"{s:.3f} {e:.3f} {label}\n" for s, e, label in rows)


def groove_hits(groove: dict[str, Any]) -> dict[str, list[bool]]:
    """The drums' one rule, as the page's instruments.grooveHits: a slot is played when it is hit in
    more than half the bars; a drum hit a little everywhere and never steadily (top slot under 0.6,
    half the slots or more at 0.2 and over) plays nothing."""

    def diffuse(row: list[float]) -> bool:
        return max(row) < 0.6 and sum(p >= 0.2 for p in row) >= len(row) / 2

    return {
        k: [False] * len(groove[k]) if diffuse(groove[k]) else [p > 0.5 for p in groove[k]]
        for k in ("kick", "snare", "hat")
    }


# MIDI: chords, bass line and drums on the beat grid, at the song's tempo (type 1, 480 PPQ).


def _vlq(n: int) -> bytes:
    out = [n & 0x7F]
    n >>= 7
    while n:
        out.append((n & 0x7F) | 0x80)
        n >>= 7
    return bytes(reversed(out))


def _track(events: list[tuple[int, bytes]], name: str) -> bytes:
    """events: (absolute tick, message bytes); sorted, with note-offs before note-ons at one tick."""
    data = b"\x00\xff\x03" + _vlq(len(name.encode())) + name.encode()
    now = 0
    for tick, msg in sorted(events, key=lambda e: (e[0], e[1][0] & 0xF0 != 0x80)):
        data += _vlq(tick - now) + msg
        now = tick
    data += b"\x00\xff\x2f\x00"
    return b"MTrk" + struct.pack(">I", len(data)) + data


def _note(events: list[tuple[int, bytes]], channel: int, pitch: int, start: int, length: int, velocity: int) -> None:
    events.append((start, bytes([0x90 | channel, pitch, velocity])))
    events.append((start + max(1, length), bytes([0x80 | channel, pitch, 0])))


def midi(song: Song) -> bytes:
    per = song["beats_per_bar"]
    tempo = struct.pack(">I", round(60_000_000 / song["bpm"]))[1:]
    meta = [(0, b"\xff\x51\x03" + tempo), (0, b"\xff\x58\x04" + bytes([per, 2, 24, 8]))]
    chords: list[tuple[int, bytes]] = []
    for b, n, c in chord_spans(song):
        if c["pc"] >= 0:
            third = 3 if c["quality"].startswith("m") else 4
            seventh = (10,) if c["quality"].endswith("7") else ()
            for interval in (0, third, 7, *seventh):  # close position from the root, around middle C
                _note(chords, 0, 53 + (c["pc"] - 5) % 12 + interval, b * PPQ, n * PPQ - 10, 80)
    bass: list[tuple[int, bytes]] = []
    drums: list[tuple[int, bytes]] = []
    parts = song["parts"]
    sixteenth = PPQ // STEM_SLOTS
    if parts:
        for u, line in enumerate(parts["bass"]):
            onsets = [(i, e) for i, e in enumerate(line) if e]
            for k, (i, e) in enumerate(onsets):
                end = onsets[k + 1][0] if k + 1 < len(onsets) else len(line)
                _note(bass, 1, e[0], (u * per) * PPQ + i * sixteenth, (end - i) * sixteenth - 10, 90)
        groove = parts["groove"]
        if groove:
            hits = groove_hits(groove)
            for u in range(len(song["bars"])):
                for i in range(per * STEM_SLOTS):
                    at = (u * per) * PPQ + i * sixteenth
                    for row, pitch in (("kick", 36), ("snare", 38), ("hat", 42)):
                        if hits[row][i]:
                            _note(drums, 9, pitch, at, sixteenth // 2, 100 if row != "hat" else 70)
    else:  # without stems: the root on each chord, so the file still has a bass line
        for b, n, c in chord_spans(song):
            if c["pc"] >= 0:
                _note(bass, 1, 36 + c["pc"], b * PPQ, n * PPQ - 10, 90)
    programs = [(0, bytes([0xC0, 0])), (0, bytes([0xC1, 33]))]  # piano, finger bass
    tracks = [
        _track(meta, song["title"][:120]),
        _track(programs[:1] + chords, "Chords"),
        _track(programs[1:] + bass, "Bass"),
    ]
    if drums:
        tracks.append(_track(drums, "Drums"))
    return b"MThd" + struct.pack(">IHHH", 6, 1, len(tracks), PPQ) + b"".join(tracks)


# MusicXML: chord symbols over the bars, and the bass line when there are stems.

KIND = {"": "major", "m": "minor", "7": "dominant", "m7": "minor-seventh"}
STEPS = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


def _spelled(pc: int, key: theory.Key) -> tuple[str, int]:
    name = theory.spell_root(pc, key)
    return name[0], {"": 0, "#": 1, "b": -1}[name[1:]]


def _fifths(key: theory.Key) -> int:
    major = key.relative_major
    sharps = {0: 0, 7: 1, 2: 2, 9: 3, 4: 4, 11: 5, 6: 6}
    flats = {5: -1, 10: -2, 3: -3, 8: -4, 1: -5}
    return flats[major] if major in flats else sharps[major]


def _durations(n: int) -> list[tuple[int, str, bool]]:
    """A length in sixteenths as tied notes: (sixteenths, type, dotted), longest first."""
    table = [
        (16, "whole", False), (12, "half", True), (8, "half", False), (6, "quarter", True),
        (4, "quarter", False), (3, "eighth", True), (2, "eighth", False), (1, "16th", False),
    ]  # fmt: skip
    out = []
    while n > 0:
        size, kind, dot = next(t for t in table if t[0] <= n)
        out.append((size, kind, dot))
        n -= size
    return out


def _pitch_xml(midi_note: int, key: theory.Key) -> str:
    step, alter = _spelled(midi_note % 12, key)
    octave = (midi_note - STEPS[step] - alter) // 12 - 1
    alter_xml = f"<alter>{alter}</alter>" if alter else ""
    return f"<pitch><step>{step}</step>{alter_xml}<octave>{octave}</octave></pitch>"


def _notes(events: list[tuple[int, int | None]], key: theory.Key, voice: int) -> str:
    """events: (length in sixteenths, MIDI note or None for a rest), filling a bar."""
    out = []
    for length, note in events:
        pieces = _durations(length)
        for i, (size, kind, dot) in enumerate(pieces):
            ties = ""
            if note is not None and len(pieces) > 1:
                ties = ('<tie type="stop"/>' if i > 0 else "") + ('<tie type="start"/>' if i < len(pieces) - 1 else "")
            body = "<rest/>" if note is None else _pitch_xml(note, key)
            tied = ""
            if ties:
                kinds = (["stop"] if i > 0 else []) + (["start"] if i < len(pieces) - 1 else [])
                tied = "<notations>" + "".join(f'<tied type="{k}"/>' for k in kinds) + "</notations>"
            dotted = "<dot/>" if dot else ""
            timing = f"<duration>{size}</duration>{ties}<voice>{voice}</voice><type>{kind}</type>{dotted}"
            out.append(f"<note>{body}{timing}{tied}</note>")
    return "".join(out)


def _key_xml(key: theory.Key) -> str:
    return f"<key><fifths>{_fifths(key)}</fifths><mode>{'major' if key.mode == 'maj' else 'minor'}</mode></key>"


def musicxml(song: Song) -> str:
    keys = Keys(song)
    per = song["beats_per_bar"]
    slots = per * STEM_SLOTS
    parts = song["parts"]
    attributes = (
        f"<attributes><divisions>{STEM_SLOTS}</divisions>{_key_xml(keys.keys[0])}"
        f"<time><beats>{per}</beats><beat-type>4</beat-type></time>"
    )
    changes = set(keys.starts[1:])
    measures = []
    for u, bar in enumerate(song["bars"]):
        key = keys.at(u)
        xml = [f'<measure number="{u + 1}">']
        if u == 0:
            xml.append(attributes + "<clef><sign>F</sign><line>4</line></clef></attributes>")
        elif u in changes:  # a new key: its signature first in the bar (spec 012)
            xml.append(f"<attributes>{_key_xml(key)}</attributes>")
        offset = 0
        for c in bar["chords"]:
            if c["pc"] >= 0:
                step, alter = _spelled(c["pc"], key)
                alter_xml = f"<root-alter>{alter}</root-alter>" if alter else ""
                xml.append(
                    f"<harmony><root><root-step>{step}</root-step>{alter_xml}</root><kind>{KIND[c['quality']]}</kind>"
                )
                xml.append(f"<offset>{offset * STEM_SLOTS}</offset></harmony>" if offset else "</harmony>")
            offset += c["beats"]
        events: list[tuple[int, int | None]] = []
        if parts:
            line = parts["bass"][u]
            onsets = [i for i, e in enumerate(line) if e]
            if not onsets or onsets[0] > 0:
                events.append(((onsets[0] if onsets else slots), None))
            for k, i in enumerate(onsets):
                end = onsets[k + 1] if k + 1 < len(onsets) else slots
                events.append((end - i, line[i][0]))
        else:
            events.append((slots, None))
        xml.append(_notes(events, key, 1))
        if u + 1 in changes:  # a double bar line before a new key
            xml.append('<barline location="right"><bar-style>light-light</bar-style></barline>')
        xml.append("</measure>")
        measures.append("".join(xml))
    title = xml_text(song["title"])
    part_name = "Bass" if parts else "Chords"
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE score-partwise PUBLIC "-//Recordare//DTD MusicXML 4.0 Partwise//EN" "http://www.musicxml.org/dtds/partwise.dtd">\n'
        f'<score-partwise version="4.0"><work><work-title>{title}</work-title></work>'
        "<identification><encoding><software>woodshed</software></encoding></identification>"
        f'<part-list><score-part id="P1"><part-name>{part_name}</part-name></score-part></part-list>'
        f'<part id="P1">{"".join(measures)}</part></score-partwise>\n'
    )


def file_stem(song: Song) -> str:
    """A plain ASCII file name for the exports: safe in any file system and in a page link."""
    stem = Path(song["file"]).stem.encode("ascii", "ignore").decode()
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._")[:80] or "song"
    return "_" + stem if re.fullmatch(r"(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(\..*)?", stem, re.IGNORECASE) else stem


def write_chordpro(song: Song, folder: Path, words: dict[str, Any] | None) -> None:
    """The page's ChordPro file again, with the words placed since (woodshed lyrics, a rebuild)."""
    (folder / f"{file_stem(song)}.cho").write_text(chordpro(song, words), encoding="utf-8")


def write_all(song: Song, folder: Path) -> list[Path]:
    """Every export of the song into `folder`. The page offers them under the song's own name."""
    folder.mkdir(parents=True, exist_ok=True)
    stem = file_stem(song)
    files = {
        f"{stem}.cho": chordpro(song).encode("utf-8"),
        f"{stem}.lab": lab(song).encode("utf-8"),
        f"{stem}.json": (json.dumps(song, indent=1, ensure_ascii=False) + "\n").encode("utf-8"),
        f"{stem}.mid": midi(song),
        f"{stem}.musicxml": musicxml(song).encode("utf-8"),
    }
    out = []
    for name, data in files.items():
        (folder / name).write_bytes(data)
        out.append(folder / name)
    return out
