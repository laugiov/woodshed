"""Song structure from per-beat labels: bars, lines of four bars, section letters and repeats."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from woodshed import sections as song_sections
from woodshed import theory
from woodshed.grid import BeatGrid
from woodshed.model import (
    SHARPNESS,
    Alternative,
    Bar,
    Chord,
    Doubt,
    Group,
    HarmonySummary,
    Section,
    SectionHarmony,
    Structure,
)

LINE_BARS = song_sections.LINE_BARS
PRIMES = ("′", "″", "‴")
CLOSE_CALL = 70  # % for the top candidate: under it the chord itself is uncertain
MIN_VARIANT_BARS = 3  # a line differing by one bar is a variant only if it has at least this many


def _chord_from(label: str, beats: int) -> Chord:
    parsed = theory.parse_label(label)
    return Chord(-1, "N", beats) if parsed is None else Chord(parsed[0], parsed[1], beats)


def _alternatives(mean: npt.NDArray[np.float64], names: Sequence[str], sharpness: float) -> list[Alternative]:
    order = np.argsort(-mean)[:3]
    w = np.exp(sharpness * (mean[order] - mean[order[0]]))
    shares = np.round(100 * w / w.sum()).astype(int)
    out = []
    for k, share in zip(order, shares, strict=True):
        parsed = theory.parse_label(names[int(k)])
        if parsed is not None:
            out.append(Alternative(parsed[0], parsed[1], int(share)))
    return out


def _bars(
    times: npt.NDArray[np.float64],
    labels: Sequence[str],
    flags: npt.NDArray[np.bool_],
    scores: npt.NDArray[np.float64] | None,
    names: Sequence[str],
    phase: int,
    per_bar: int,
    sharpness: float,
) -> tuple[list[Bar], float | None, float | None, int]:
    voiced = [i for i, lab in enumerate(labels) if lab != "N"]
    if not voiced:
        return [], None, None, 0
    first, last = voiced[0], voiced[-1]
    start = first - ((first - phase) % per_bar)
    beat_time = BeatGrid.of(times).time

    bars, doubt_id = [], 0
    b0 = start
    while b0 <= last:

        def label_at(i: int) -> str:
            return labels[i] if 0 <= i < len(labels) else "N"

        runs: list[list[int]] = []
        for i in range(b0, b0 + per_bar):
            if runs and label_at(runs[-1][0]) == label_at(i):
                runs[-1].append(i)
            else:
                runs.append([i])
        chords = []
        for run in runs:
            chord = _chord_from(label_at(run[0]), len(run))
            inside = [i for i in run if 0 <= i < len(labels)]
            if chord.pc >= 0 and scores is not None and any(flags[i] for i in inside):
                alts = _alternatives(scores[:, inside].mean(axis=1), names, sharpness)
                close = bool(alts) and alts[0].share < CLOSE_CALL  # nothing to offer: not a close call
                why = (
                    "Close call between the top candidates."
                    if close
                    else "The chord is clear, but it starts off the beat or lasts a single beat."
                )
                kind = "chord" if close else "timing"
                chord = Chord(chord.pc, chord.quality, chord.beats, Doubt(doubt_id, why, alts, kind))
                doubt_id += 1
            chords.append(chord)
        # A pickup bar can start before the file does: the page cannot seek there.
        bars.append(Bar(max(0.0, beat_time(b0)), beat_time(b0 + per_bar), chords))
        b0 += per_bar
    return bars, beat_time(first), beat_time(last + 1), start


LineSignature = tuple[tuple[tuple[int, str, int], ...], ...]


@dataclass
class _Family:
    signature: LineSignature
    letter: str
    variants: int = 0


class _Lettering:
    """Letters name sections. A line that differs from a known one by a single bar keeps its letter
    with a prime (A′); any other new line gets the next letter."""

    def __init__(self) -> None:
        self.families: list[_Family] = []
        self.known: dict[LineSignature, tuple[str, str]] = {}

    def letter_for(self, sig: LineSignature) -> tuple[str, str]:
        """(label, family) of a line."""
        if sig not in self.known:
            self.known[sig] = self._of_family(sig) or self._new_family(sig)
        return self.known[sig]

    def _of_family(self, sig: LineSignature) -> tuple[str, str] | None:
        # A short last line is compared with the start of a full line.
        candidates = [f for f in self.families if len(sig) <= len(f.signature)]

        def differences(fam: _Family) -> int:
            return sum(a != b for a, b in zip(fam.signature, sig, strict=False))

        for fam in candidates:  # an exact match in any family wins over a variant
            if differences(fam) == 0:
                return fam.letter, fam.letter
        if len(sig) < MIN_VARIANT_BARS:  # one bar in common out of two says nothing
            return None
        for fam in candidates:
            if differences(fam) == 1:
                fam.variants += 1
                mark = PRIMES[fam.variants - 1] if fam.variants <= len(PRIMES) else f"({fam.variants})"
                return fam.letter + mark, fam.letter
        return None

    def _new_family(self, sig: LineSignature) -> tuple[str, str]:
        letter = section_letter(len(self.families))
        self.families.append(_Family(sig, letter))
        return letter, letter


def section_letter(n: int) -> str:
    """0 -> A, 25 -> Z, 26 -> AA, 27 -> AB, as spreadsheet columns."""
    out = ""
    n += 1
    while n:
        n, r = divmod(n - 1, 26)
        out = chr(ord("A") + r) + out
    return out


def _group(bars: list[Bar], sections: Sequence[Section] = ()) -> list[Group]:
    """Lines of four bars. Only exactly identical consecutive lines of one section collapse into a
    repeat: a section always starts a new line on the page."""
    lettering = _Lettering()
    groups: list[Group] = []
    previous: LineSignature | None = None
    starts = {s.start for s in sections}
    for start in range(0, len(bars), LINE_BARS):
        line = list(range(start, min(start + LINE_BARS, len(bars))))
        sig = tuple(bars[i].signature() for i in line)
        if groups and sig == previous and start not in starts:
            groups[-1].occurrences.append(line)
        else:
            label, family = lettering.letter_for(sig)
            groups.append(Group(label, family, [line]))
        previous = sig
    for g, group in enumerate(groups):
        for o, line in enumerate(group.occurrences):
            for c, i in enumerate(line):
                bars[i].group, bars[i].occurrence, bars[i].column = g, o, c
    return groups


def build(
    times: npt.NDArray[np.float64],
    labels: Sequence[str],
    flags: npt.NDArray[np.bool_],
    scores: npt.NDArray[np.float64] | None,
    names: Sequence[str],
    phase: int,
    per_bar: int = 4,
    *,
    sharpness: float = SHARPNESS,
    energy_db: npt.NDArray[np.float64] | None = None,
    vocal: npt.NDArray[np.float64] | None = None,
) -> Structure:
    """Bars, lines, sections and doubts. `sharpness` must be the decoder's, so doubt shares match
    its odds. `energy_db` and `vocal` (per beat) help name the sections; without them the sections
    come from the chords alone."""
    bars, start, end, first_beat = _bars(times, labels, flags, scores, names, phase, per_bar, sharpness)
    found = song_sections.sections(
        [[(c.pc, c.quality, c.beats) for c in b.chords] for b in bars],
        [(b.start, b.end) for b in bars],
        np.asarray(times, dtype=float),
        energy_db,
        vocal,
    )
    return Structure(bars, _group(bars, found), start, end, first_beat, found)


LOOP_COVERAGE = 0.7  # two sections are one loop when their alternation covers this share of the lines


def _section_harmony(label: str, signature: LineSignature, key: theory.Key) -> SectionHarmony:
    seq: list[tuple[int, str]] = []
    for bar in signature:
        for pc, quality, _ in bar:
            if pc >= 0 and (not seq or seq[-1] != (pc, quality)):
                seq.append((pc, quality))
    romans = [theory.roman(pc, q, key) for pc, q in seq]
    return SectionHarmony(label, seq, romans, theory.progression_name(seq, key))


def harmony_summary(structure: Structure, key: theory.Key) -> HarmonySummary:
    """Harmony per section, as roman numerals with a name when a progression is well known.

    Two sections that strictly alternate (A B A B, as in an eight-bar loop) are one loop and are
    summarised together; otherwise each section family gets its own line.
    """
    if not structure.bars:
        return HarmonySummary([])
    occurrences = [(g.family, occ) for g in structure.groups for occ in g.occurrences]
    lines = [tuple(structure.bars[i].signature() for i in occ) for _, occ in occurrences]
    families = [family for family, _ in occurrences]

    pairs = Counter((families[i], families[i + 1]) for i in range(len(families) - 1) if families[i] != families[i + 1])
    if pairs:
        (fa, fb), _ = pairs.most_common(1)[0]
        covered, i, first = 0, 0, None
        while i < len(families) - 1:
            if (families[i], families[i + 1]) == (fa, fb):
                first = i if first is None else first
                covered += 2
                i += 2
            else:
                i += 1
        if first is not None and covered / len(families) >= LOOP_COVERAGE:
            return HarmonySummary([_section_harmony(f"{fa}+{fb}", lines[first] + lines[first + 1], key)])

    sections = []
    for family in dict.fromkeys(families):
        family_lines = [line for line, f in zip(lines, families, strict=True) if f == family]
        sections.append(_section_harmony(family, Counter(family_lines).most_common(1)[0][0], key))
    return HarmonySummary(sections)
