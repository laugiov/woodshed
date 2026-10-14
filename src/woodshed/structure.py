"""Song structure from per-beat labels: bars, lines of four bars, section letters and repeats."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np
import numpy.typing as npt

from woodshed import theory

LINE_BARS = 4
PRIMES = ("′", "″", "‴")


@dataclass(frozen=True)
class Alternative:
    pc: int
    quality: str
    share: int  # percent

    @property
    def name(self) -> str:
        return theory.SHARP_NAMES[self.pc] + self.quality


@dataclass(frozen=True)
class Doubt:
    id: int
    why: str
    alternatives: list[Alternative]


@dataclass(frozen=True)
class Chord:
    pc: int  # -1 for no chord
    quality: str  # "", "m", "7", "m7"; "N" for no chord
    beats: int
    doubt: Doubt | None = None

    @property
    def name(self) -> str:
        return "N" if self.pc < 0 else theory.SHARP_NAMES[self.pc] + self.quality


@dataclass
class Bar:
    start: float
    end: float
    chords: list[Chord]
    group: int = 0
    occurrence: int = 0
    column: int = 0

    def signature(self) -> tuple[tuple[int, str, int], ...]:
        return tuple((c.pc, c.quality, c.beats) for c in self.chords)


@dataclass
class Group:
    """Consecutive identical lines, shown once with a repeat count."""

    label: str
    occurrences: list[list[int]] = field(default_factory=list)


@dataclass
class Structure:
    bars: list[Bar]
    groups: list[Group]
    music_start: float | None
    music_end: float | None


@dataclass(frozen=True)
class SectionHarmony:
    label: str  # a section letter, or "A+B" for a loop spanning two sections
    chords: list[tuple[int, str]]
    romans: list[str]
    name: str | None


@dataclass(frozen=True)
class HarmonySummary:
    sections: list[SectionHarmony]

    @property
    def name(self) -> str | None:
        return next((h.name for h in self.sections if h.name), None)


def _chord_from(label: str, beats: int) -> Chord:
    parsed = theory.parse_label(label)
    return Chord(-1, "N", beats) if parsed is None else Chord(parsed[0], parsed[1], beats)


def _alternatives(mean: npt.NDArray[np.float64], names: Sequence[str], sharpness: float = 25.0) -> list[Alternative]:
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
) -> tuple[list[Bar], float | None, float | None]:
    voiced = [i for i, lab in enumerate(labels) if lab != "N"]
    if not voiced:
        return [], None, None
    first, last = voiced[0], voiced[-1]
    start = first - ((first - phase) % per_bar)
    period = float(np.median(np.diff(times))) if len(times) > 1 else 0.5

    def beat_time(i: int) -> float:
        return float(times[i]) if 0 <= i < len(times) else float(times[0] + i * period)

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
                alts = _alternatives(scores[:, inside].mean(axis=1), names)
                why = (
                    "Close call between the top candidates."
                    if alts and alts[0].share < 70
                    else "The chord starts off the beat or lasts a single beat."
                )
                chord = Chord(chord.pc, chord.quality, chord.beats, Doubt(doubt_id, why, alts))
                doubt_id += 1
            chords.append(chord)
        bars.append(Bar(beat_time(b0), beat_time(b0 + per_bar), chords))
        b0 += per_bar
    return bars, beat_time(first), beat_time(last) + period


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
        self.known: dict[LineSignature, str] = {}

    def letter_for(self, sig: LineSignature) -> str:
        if sig not in self.known:
            self.known[sig] = self._variant_of_family(sig) or self._new_family(sig)
        return self.known[sig]

    def _variant_of_family(self, sig: LineSignature) -> str | None:
        for fam in self.families:
            if len(fam.signature) == len(sig) and sum(a != b for a, b in zip(fam.signature, sig, strict=True)) <= 1:
                fam.variants += 1
                mark = PRIMES[fam.variants - 1] if fam.variants <= len(PRIMES) else f"({fam.variants})"
                return fam.letter + mark
        return None

    def _new_family(self, sig: LineSignature) -> str:
        letter = chr(ord("A") + len(self.families)) if len(self.families) < 26 else "Z"
        self.families.append(_Family(sig, letter))
        return letter


def _group(bars: list[Bar]) -> list[Group]:
    """Lines of four bars. Only exactly identical consecutive lines collapse into a repeat."""
    lettering = _Lettering()
    groups: list[Group] = []
    previous: LineSignature | None = None
    for start in range(0, len(bars), LINE_BARS):
        line = list(range(start, min(start + LINE_BARS, len(bars))))
        sig = tuple(bars[i].signature() for i in line)
        if groups and sig == previous:
            groups[-1].occurrences.append(line)
        else:
            groups.append(Group(lettering.letter_for(sig), [line]))
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
) -> Structure:
    bars, start, end = _bars(times, labels, flags, scores, names, phase, per_bar)
    return Structure(bars, _group(bars), start, end)


LOOP_COVERAGE = 0.7  # two sections are one loop when their alternation covers this share of the lines


def _section_harmony(label: str, signature: LineSignature, key: theory.Key) -> SectionHarmony:
    seq: list[tuple[int, str]] = []
    for bar in signature:
        for pc, quality, _ in bar:
            if pc >= 0 and (not seq or seq[-1] != (pc, quality)):
                seq.append((pc, quality))
    romans = [theory.roman(pc, q, key) for pc, q in seq]
    return SectionHarmony(label, seq, romans, theory.named_progression(romans))


def harmony_summary(structure: Structure, key: theory.Key) -> HarmonySummary:
    """Harmony per section, as roman numerals with a name when a progression is well known.

    Two sections that strictly alternate (A B A B, as in an eight-bar loop) are one loop and are
    summarised together; otherwise each section family gets its own line.
    """
    if not structure.bars:
        return HarmonySummary([])
    occurrences = [(g.label, occ) for g in structure.groups for occ in g.occurrences]
    lines = [tuple(structure.bars[i].signature() for i in occ) for _, occ in occurrences]
    families = [label.rstrip("".join(PRIMES)) for label, _ in occurrences]

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
