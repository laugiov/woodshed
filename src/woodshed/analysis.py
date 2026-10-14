"""Full analysis of a recording: beats, chords, structure and, with stems, every instrument's part."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import numpy.typing as npt

from woodshed import __version__, audio, beats, meter, parts, stems, structure, theory
from woodshed.engine import Decoded, decode
from woodshed.engine.decoding import MIN_CLARITY
from woodshed.engine.features import Spectral, beat_accents, spectral, sync
from woodshed.model import AnalysisInfo, Meta, Parts, Song, Structure

Progress = Callable[[str, float], None]
Floats = npt.NDArray[np.float64]
# Below this share of tracked downbeats on one residue, the downbeats are too inconsistent to set
# the bar phase and the chord changes decide instead.
MIN_DOWNBEAT_SHARE = 0.5


def _noop(step: str, fraction: float) -> None:
    del step, fraction


@dataclass(frozen=True)
class Meter:
    """The final beat grid and the chords decoded on it, with the bar phase they were decoded with."""

    decoded: Decoded
    halved: bool


def resolve_meter(spec: Spectral, grid: Floats, downbeats: Floats | None, beats_per_bar: int, sevenths: bool) -> Meter:
    """Tempo octave and bar phase, then one last decoding on the final grid with that phase.

    Every correction ends in a fresh decoding, so the chords, the doubts and the bar lines the
    chart uses all come from the same grid and the same phase.
    """
    phase: int | None = None
    if downbeats is not None:
        found, share = meter.phase_from_downbeats(grid, downbeats, beats_per_bar)
        phase = found if share >= MIN_DOWNBEAT_SHARE else None
    decoded = decode(sync(spec, grid), sevenths, beats_per_bar, phase=phase)

    halved = False
    if downbeats is None:  # beat_this does not double the tempo; librosa sometimes does
        parity = meter.tempo_octave_parity(decoded.labels, decoded.tempo, beat_accents(spec, decoded.beat_times))
        if parity is not None:
            decoded = decode(sync(spec, decoded.beat_times[parity::2]), sevenths, beats_per_bar)
            halved = True

    if phase is None:
        accents = np.power(10.0, decoded.energy_db / 20.0)
        phase = meter.pick_phase(decoded.labels, accents, beats_per_bar)
        if phase != decoded.phase:
            decoded = decode(sync(spec, decoded.beat_times), sevenths, beats_per_bar, phase=phase)
    return Meter(decoded, halved)


def analyze(
    path: str | Path,
    *,
    use_stems: bool,
    sevenths: bool = False,
    title: str | None = None,
    beats_per_bar: int = 4,
    offline: bool = False,
    stems_result: stems.Stems | None = None,
    progress: Progress | None = None,
) -> Song:
    """Analyse one recording. With `use_stems`, the stems also give each instrument's part and,
    when beat_this is installed, better beats and downbeats.

    `stems_result` hands over stems separated earlier (a songbook run, tests); it needs `use_stems`.
    """
    if stems_result is not None and not use_stems:
        raise ValueError("stems_result was given but use_stems is False")
    report = progress or _noop
    started = time.monotonic()
    src = Path(path).expanduser().resolve()

    report("decode", 0.0)
    y = audio.load(src)
    duration = y.size / audio.SR

    separated = None
    if use_stems:
        separated = stems_result or stems.separate(src, offline=offline, progress=lambda f: report("stems", f))

    report("beats", 0.0)
    downbeats: Floats | None = None
    if use_stems and beats.beat_this_available():
        grid, downbeats = beats.track_beat_this(src, offline=offline)
    else:
        _, grid = beats.track_librosa(y)

    report("chords", 0.0)
    resolved = resolve_meter(spectral(y), grid, downbeats, beats_per_bar, sevenths)
    decoded = resolved.decoded
    times = decoded.beat_times

    report("structure", 0.0)
    built = structure.build(
        times,
        decoded.labels,
        decoded.doubtful,
        decoded.scores,
        decoded.names,
        decoded.phase,
        beats_per_bar,
        sharpness=decoded.sharpness,
    )
    key = theory.Key(decoded.key_pc, decoded.key_mode)
    timed = [theory.TimedChord(c.pc, c.quality, c.beats) for b in built.bars for c in b.chords if c.pc >= 0]

    song_parts = None
    if separated is not None and built.bars:
        report("parts", 0.0)
        song_parts = _parts(separated, times, built, beats_per_bar)

    report("done", 1.0)
    return Song(
        title=title or src.stem,
        file=src.name,
        duration=duration,
        bpm=60.0 / float(np.median(np.diff(times))),
        beats_per_bar=beats_per_bar,
        key=key,
        key_known=decoded.key_known,
        capo=theory.suggest_capo(timed),
        beats=[float(t) for t in times],
        structure=built,
        harmony=structure.harmony_summary(built, key),
        energy=[(float(t), float(e)) for t, e in zip(times, decoded.energy_db, strict=True)],
        parts=song_parts,
        analysis=AnalysisInfo(
            beats="librosa" if downbeats is None else "beat_this",
            tempo_halved=resolved.halved,
            stems=separated is not None,
            sevenths=sevenths,
            clarity=decoded.clarity,
            chords_reliable=decoded.clarity >= MIN_CLARITY,
            stems_gain=None if separated is None else separated.gain,
        ),
        meta=Meta(__version__, time.monotonic() - started),
    )


def _parts(separated: stems.Stems, times: Floats, built: Structure, beats_per_bar: int) -> Parts:
    track = {name: audio.load(p) for name, p in separated.paths.items()}
    shift = parts.drum_grid_shift(track["drums"], times)
    grid = parts.Grid.from_beats(times + shift, built.first_beat, beats_per_bar, n_bars=len(built.bars))
    return Parts(
        groove=parts.drum_groove(track["drums"], grid),
        bass=parts.bass_line(track["bass"], grid),
        comp=parts.comp_rhythm(track["other"], grid),
        voicings=parts.voicings(track["other"], grid),
        vocal=parts.vocal_range(track["vocals"]),
        grid_shift=shift,
    )
