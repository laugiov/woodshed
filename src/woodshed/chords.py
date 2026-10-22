"""Chords a musician types on the chart: the table of qualities, the parser, names and numerals.

The analysis only ever writes "", "m", "7" and "m7"; a band corrects its chart with any chord of
`chords.json` (sus, maj7, dim, slash chords…). One table for the library, which checks what a page
sends, and for the page itself (core/chords.js reads the same file): a test runs both on one table
of cases.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from importlib import resources
from typing import Any

from woodshed import theory

_TABLE: dict[str, Any] = json.loads(resources.files("woodshed").joinpath("chords.json").read_text(encoding="utf-8"))
QUALITIES: dict[str, dict[str, Any]] = _TABLE["qualities"]
ALIASES: dict[str, str] = _TABLE["aliases"]
REFUSALS: dict[str, str] = _TABLE["refusals"]
DEGREES: list[str] = _TABLE["degrees"]
MOVABLE: dict[str, dict[str, list[int | None]]] = {q: f for q, f in _TABLE["movable"].items() if q != "description"}
OPEN: dict[str, list[int]] = {n: f for n, f in _TABLE["open"].items() if n != "description"}

HINTS: dict[str, str] = _TABLE["hints"]  # "{root}" is the root as typed
SPACES = re.compile(r"[ \t\r\n\u00a0]+")  # the same class as core/chords.js

NO_CHORD_SPELLINGS = frozenset({"N.C.", "NC", "N.C", "N/C"})
ACCIDENTALS = {"#": 1, "♯": 1, "b": -1, "♭": -1, "": 0}
CHORD = re.compile(r"([A-Ga-g])([#♯b♭]?)([^/]*)(?:/(.*))?")
NOTE = re.compile(r"([A-Ga-g])([#♯b♭]?)")
ALTERED = re.compile(r"(?:^|7|9|11|13)[-+#b♯♭](?:5|9|11|13)")


@dataclass(frozen=True)
class Chord:
    pc: int  # -1: no chord
    quality: str
    bass: int | None = None  # only when it is not the root


@dataclass(frozen=True)
class Refusal:
    code: str
    hint: str


NO_CHORD = Chord(-1, "", None)


def _quality(suffix: str) -> str | None:
    # Only a capital M (major seventh, CM7) differs from its lower case: everything else is read in
    # either case ("Cmin", "CMIN").
    candidate = suffix if suffix.startswith("M") and not suffix.lower().startswith(("maj", "min")) else suffix.lower()
    for text in (suffix, candidate):
        if text in QUALITIES:
            return text
        if text in ALIASES:
            return ALIASES[text]
    return None


def parse(text: str) -> Chord | Refusal:
    """A chord as written on a chord sheet, or why it is refused (never a guess)."""

    def refuse(code: str, root: str = "") -> Refusal:
        return Refusal(code, HINTS[code].format(root=root))

    typed = SPACES.sub("", str(text))
    if not typed:
        return refuse("empty")
    if "|" in typed:
        return refuse("bar-line")
    if typed.upper() in NO_CHORD_SPELLINGS:
        return NO_CHORD
    typed = typed.replace("(", "").replace(")", "")
    found = CHORD.fullmatch(typed)
    if not found:
        return refuse("unknown")
    root, accidental, suffix, bass_text = found.groups()
    pc = (theory.NATURALS[root.upper()] + ACCIDENTALS[accidental]) % 12
    named = root.upper() + accidental
    quality = _quality(suffix)
    if quality is None:
        code = REFUSALS.get(suffix.lower()) or ("altered" if ALTERED.search(suffix) else "unknown")
        return refuse(code, named)
    bass: int | None = None
    if bass_text is not None:
        note = NOTE.fullmatch(bass_text)
        if not note:
            return refuse("six-nine" if quality == "6" and bass_text == "9" else "unknown", named)
        bass = (theory.NATURALS[note.group(1).upper()] + ACCIDENTALS[note.group(2)]) % 12
        if bass == pc:
            bass = None  # C/C is C
    return Chord(pc, quality, bass)


def intervals(quality: str) -> list[int]:
    return list(QUALITIES[quality]["intervals"])


def name(chord: Chord, key: theory.Key, transpose: int = 0, prefer: theory.Prefer = None) -> str:
    """The chord as the chart writes it, root and bass spelled by the key (transposed with the song)."""
    if chord.pc < 0:
        return "N.C."
    moved = theory.Key((key.tonic + transpose) % 12, key.mode)
    out = theory.spell_root((chord.pc + transpose) % 12, moved, prefer) + chord.quality
    if chord.bass is not None:
        out += "/" + theory.spell_root((chord.bass + transpose) % 12, moved, prefer)
    return out


def roman(chord: Chord, key: theory.Key) -> str:
    """Degree of the root, lower case for the minor family, the quality's mark; a slash bass as its
    degree above the root ("I/3", "V/b7"), never the "V/V" of a secondary dominant."""
    if chord.pc < 0:
        return ""
    form = QUALITIES[chord.quality]["roman"]
    numeral = theory.ROMAN[(chord.pc - key.tonic) % 12]
    out = (numeral.lower() if form["lower"] else numeral) + str(form["mark"])
    if chord.bass is not None:
        out += "/" + DEGREES[(chord.bass - chord.pc) % 12]
    return out
