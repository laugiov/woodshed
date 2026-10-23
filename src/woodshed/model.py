"""The analysis result: plain data, no audio library behind it.

Readers of a song (the JSON writer, exporters, the songbook) import this module only, so they do
not load librosa or numba.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from woodshed import theory

# Contrast that turns chord scores into probabilities: the decoder and the doubt shares use it.
SHARPNESS = 25.0


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
    # "chord": the top candidates are close, the chord itself is uncertain (counted, shown in
    # orange); "timing": the chord is clear but starts off the beat or lasts one beat.
    kind: str = "chord"

    @property
    def counts(self) -> bool:
        return self.kind == "chord"


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

    label: str  # letter with its variant mark: A, A′, A″
    family: str  # the letter alone: A′ and A″ are variants of A
    occurrences: list[list[int]] = field(default_factory=list)


@dataclass(frozen=True)
class Section:
    """A part of the song as a band names it: Intro, Verse 1, Chorus 2. Whole lines of the chart."""

    name: str
    role: str  # intro, verse, prechorus, chorus, bridge, instrumental, outro, or part
    letter: str  # the same letter is the same music
    start: int  # first bar
    end: int  # bar after the last


@dataclass(frozen=True)
class KeyRegion:
    """From this bar on, the song is in this key (spec 012); the first region starts at bar 0."""

    bar: int
    key: theory.Key


@dataclass
class Structure:
    bars: list[Bar]
    groups: list[Group]
    music_start: float | None
    music_end: float | None
    first_beat: int = 0  # index, in the beat grid, of the first bar's beat one (negative for a pickup)
    sections: list[Section] = field(default_factory=list)


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


@dataclass(frozen=True)
class Groove:
    kick: list[float]  # share of bars with a hit on each slot
    snare: list[float]
    hat: list[float]
    agreement: dict[str, float]  # share of slots matching the main groove, per instrument
    bars: int


@dataclass(frozen=True)
class BassNote:
    midi: int
    confidence: float


@dataclass(frozen=True)
class RegionRange:
    """The sung range from a key region's first bar (spec 024): None under MIN_REGION_NOTES notes."""

    bar: int
    low: int | None
    high: int | None
    notes: int  # sung notes kept in the region


@dataclass(frozen=True)
class VocalRange:
    low: int  # MIDI, 10th percentile of sung notes: the usual range, not the extremes
    high: int  # MIDI, 90th percentile
    voiced_share: float
    regions: tuple[RegionRange, ...] = ()  # one per key region, on a song with key changes (spec 024)


@dataclass(frozen=True)
class AnalysisInfo:
    """How the result was obtained: part of the result, the same on every run."""

    beats: Literal["librosa", "beat_this"]
    tempo_halved: bool
    stems: bool
    sevenths: bool
    clarity: float  # how well chords fit the sound; below MIN_CLARITY the chart is flagged
    chords_reliable: bool
    stems_gain: float | None  # play the stems at 1 / stems_gain to match the recording
    bpm_hint: float | None = None  # the tempo given with --bpm, when there was one


@dataclass(frozen=True)
class Meta:
    """How this run went: differs between two runs on the same input, so kept apart."""

    version: str
    seconds: float
    analysis: int | None = None  # the analysis revision (analysis.REVISION) that found the chords and beats


@dataclass(frozen=True)
class Parts:
    groove: Groove | None
    bass: list[list[BassNote | None]]
    comp: list[float]
    voicings: list[list[int]]
    vocal: VocalRange | None
    grid_shift: float


@dataclass(frozen=True)
class Song:
    title: str
    file: str
    duration: float
    bpm: float
    beats_per_bar: int
    key: theory.Key
    key_known: bool
    capo: int
    beats: list[float]
    structure: Structure
    harmony: HarmonySummary
    energy: list[tuple[float, float]]
    parts: Parts | None
    analysis: AnalysisInfo
    meta: Meta
    # The key regions, the first at bar 0: one for most songs, more after a key change (spec 012).
    key_regions: list[KeyRegion] = field(default_factory=list)
