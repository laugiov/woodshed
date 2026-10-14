"""Music theory: chord spelling, transposition, roman numerals, named progressions, capo."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

SHARP_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
FLAT_NAMES = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"]
# Major keys written with flats. F# major (6) is written with sharps: Gb major would need Cb.
FLAT_MAJOR_KEYS = frozenset({5, 10, 3, 8, 1})
ROMAN = {
    0: "I",
    1: "bII",
    2: "II",
    3: "bIII",
    4: "III",
    5: "IV",
    6: "#IV",
    7: "V",
    8: "bVI",
    9: "VI",
    10: "bVII",
    11: "VII",
}
OPEN_SHAPES = frozenset(
    {"C", "A", "G", "E", "D", "Am", "Em", "Dm", "A7", "E7", "D7", "G7", "C7", "B7", "Am7", "Em7", "Dm7"}
)
EASY_BARRES = frozenset({"F", "Bm"})

Mode = Literal["maj", "min"]
Prefer = Literal["sharps", "flats"] | None


@dataclass(frozen=True)
class Key:
    tonic: int
    mode: Mode = "maj"

    @property
    def relative_major(self) -> int:
        return self.tonic if self.mode == "maj" else (self.tonic + 3) % 12


@dataclass(frozen=True)
class TimedChord:
    pc: int
    quality: str
    beats: int


def transpose(pc: int, semitones: int) -> int:
    return (pc + semitones) % 12


def spell(pc: int, key: Key, prefer: Prefer = None) -> str:
    """Note name for a pitch class, with the accidentals of the key unless forced."""
    flats = prefer == "flats" or (prefer is None and key.relative_major in FLAT_MAJOR_KEYS)
    return (FLAT_NAMES if flats else SHARP_NAMES)[pc % 12]


MAJOR_STEPS = (0, 2, 4, 5, 7, 9, 11)
LOWERED_DEGREES = {1: 2, 3: 4, 8: 9, 10: 11}  # bII, bIII, bVI, bVII: lowered from the degree above
RAISED_DEGREES = {6: 5}  # #IV: raised from the fourth


def _lower(name: str) -> str:
    if name.endswith("#"):
        return name[0]
    return {"C": "B", "F": "E"}.get(name, name + "b")  # no Cb or Fb in a chart


def _raise(name: str) -> str:
    if name.endswith("b"):
        return name[0]
    return {"B": "C", "E": "F"}.get(name, name + "#")


def spell_root(pc: int, key: Key, prefer: Prefer = None) -> str:
    """Chord root spelled by scale degree: borrowed roots on lowered degrees take a flat (Bb in C)."""
    if prefer is not None:
        return spell(pc, key, prefer)
    major = key.relative_major
    degree = (pc - major) % 12
    if degree in MAJOR_STEPS:
        return spell(pc, key)
    if degree in LOWERED_DEGREES:
        return _lower(spell(major + LOWERED_DEGREES[degree], key))
    return _raise(spell(major + RAISED_DEGREES[degree], key))


def chord_name(pc: int, quality: str, key: Key, prefer: Prefer = None) -> str:
    return spell_root(pc, key, prefer) + quality


NATURALS = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


def parse_label(label: str) -> tuple[int, str] | None:
    """'A#m7' -> (10, 'm7'), 'Cb' -> (11, ''); 'N' -> None."""
    if label in ("N", "X", ""):
        return None
    if label[0] not in NATURALS:
        raise ValueError(f"not a chord label: {label!r}")
    accidental = {"#": 1, "b": -1}.get(label[1:2], 0)
    return (NATURALS[label[0]] + accidental) % 12, label[1 + abs(accidental) :]


def roman(pc: int, quality: str, key: Key) -> str:
    """Degree relative to the tonic; lower case for minor chords, the seventh kept as a suffix."""
    numeral = ROMAN[(pc - key.tonic) % 12]
    if quality.startswith("m") and not quality.startswith("maj"):
        numeral = numeral.lower()
    return numeral + ("maj7" if quality == "maj7" else "7" if quality.endswith("7") else "")


PROGRESSIONS: list[tuple[list[str], str]] = [
    (["I", "vi", "IV", "ii", "V"], "the 1950s progression (I-vi-IV-V) with a ii before the V"),
    (["I", "V", "vi", "IV"], "the I-V-vi-IV progression, the most common one in pop of the last fifty years"),
    (["vi", "IV", "I", "V"], "the I-V-vi-IV pop progression, started on the vi"),
    (["I", "vi", "IV", "V"], "the 1950s progression (I-vi-IV-V)"),
    (["I", "vi", "ii", "V"], "the I-vi-ii-V turnaround"),
    (["ii", "V", "I"], "the jazz ii-V-I"),
    (["I", "IV", "V"], "the three-chord I-IV-V"),
]


def named_progression(romans: Sequence[str]) -> str | None:
    """Name of the first well-known progression found in the sequence, if any."""
    plain = [r.removesuffix("7") for r in romans]
    for pattern, name in PROGRESSIONS:
        for i in range(len(plain) - len(pattern) + 1):
            if plain[i : i + len(pattern)] == pattern:
                return name
    return None


def progression_name(chords: Sequence[tuple[int, str]], key: Key) -> str | None:
    """Name of a well-known progression in these chords, whether the key reads as major or minor.

    Am-F-C-G is vi-IV-I-V in C and i-bVI-bIII-bVII in A minor: the key estimate often cannot tell
    the two apart on such loops, so names are matched relative to the relative major.
    """
    major = Key(key.relative_major, "maj")
    return named_progression([roman(pc, q, major) for pc, q in chords])


def shape_difficulty(pc: int, quality: str) -> int:
    """1 for an open shape, 2 for an easy barre (F, Bm), 3 otherwise."""
    name = SHARP_NAMES[pc % 12] + quality
    if name in OPEN_SHAPES:
        return 1
    return 2 if name in EASY_BARRES else 3


def suggest_capo(chords: Sequence[TimedChord], transposition: int = 0) -> int:
    """Capo position (0 to 7) worth suggesting: only when it makes the song clearly easier."""

    def cost(capo: int) -> int:
        return sum(shape_difficulty(c.pc + transposition - capo, c.quality) * c.beats for c in chords)

    base = cost(0)
    best, best_cost = 0, base
    for capo in range(1, 8):
        c = cost(capo)
        if c < best_cost:
            best, best_cost = capo, c
    return best if best_cost <= 0.75 * base else 0
