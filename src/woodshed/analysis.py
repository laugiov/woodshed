"""Full analysis of a recording: beats, chords, structure and, with stems, every instrument's part."""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import numpy.typing as npt

from woodshed import __version__, audio, beats, meter, parts, stems, structure, theory, tracks
from woodshed.engine import Decoded, decode
from woodshed.engine.decoding import MIN_CLARITY
from woodshed.engine.features import Spectral, beat_accents, spectral, sync
from woodshed.model import AnalysisInfo, KeyRegion, Meta, Parts, Song, Structure

Progress = Callable[[str, float], None]
# Bumped whenever the analysis gives different results for the same file: pages built by an older
# revision are then rebuilt by the next run instead of being kept as up to date.
# Any change to the engine, features or structure that changes labels needs a bump too.
REVISION = 4  # 2: silence judged on absolute level (soft verses kept); 3: doubt kinds, sections; 4: key regions
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


def fit_octave(spec: Spectral, grid: Floats, bpm: float) -> tuple[Floats, bool]:
    """The grid kept, halved or doubled, whichever lands nearest the tempo the musician hears.

    Returns (grid, halved). Halving keeps the more accented of the two beat parities.
    """
    tempo = 60.0 / float(np.median(np.diff(grid)))
    options = {"keep": tempo, "halve": tempo / 2, "double": tempo * 2}
    best = min(options, key=lambda k: abs(math.log(options[k] / bpm)))
    if best == "halve":
        accents = beat_accents(spec, grid)
        parity = 0 if float(np.median(accents[0::2])) >= float(np.median(accents[1::2])) else 1
        return grid[parity::2], True
    if best == "double":
        return np.sort(np.concatenate([grid, grid[:-1] + np.diff(grid) / 2])), False
    return grid, False


def resolve_meter(
    spec: Spectral,
    grid: Floats,
    downbeats: Floats | None,
    beats_per_bar: int,
    sevenths: bool,
    bpm: float | None = None,
    bar_phase: int | None = None,
) -> Meter:
    """Tempo octave and bar phase, then one last decoding on the final grid with that phase.

    Every correction ends in a fresh decoding, so the chords, the doubts and the bar lines the
    chart uses all come from the same grid and the same phase. `bpm`, the tempo the musician
    hears, replaces the automatic tempo-octave guess.
    """
    halved = False
    if bpm is not None:
        grid, halved = fit_octave(spec, grid, bpm)
    phase: int | None = None
    if downbeats is not None:
        found, share = meter.phase_from_downbeats(grid, downbeats, beats_per_bar)
        phase = found if share >= MIN_DOWNBEAT_SHARE else None
    decoded = decode(sync(spec, grid), sevenths, beats_per_bar, phase=phase)

    if downbeats is None and bpm is None:  # beat_this does not double the tempo; librosa sometimes does
        parity = meter.tempo_octave_parity(decoded.labels, decoded.tempo, beat_accents(spec, decoded.beat_times))
        if parity is not None:
            decoded = decode(sync(spec, decoded.beat_times[parity::2]), sevenths, beats_per_bar)
            halved = True

    if phase is None:
        accents = np.power(10.0, decoded.energy_db / 20.0)
        phase = meter.pick_phase(decoded.labels, accents, beats_per_bar)
        if phase != decoded.phase:
            decoded = decode(sync(spec, decoded.beat_times), sevenths, beats_per_bar, phase=phase)
    # The band's bar lines (`bar_phase`: the beats before the first bar line): only at the last decoding, once the
    # tempo is settled, so the beats stay the same and the chords typed on them stay where they were.
    if bar_phase is not None and bar_phase != decoded.phase:
        decoded = decode(sync(spec, decoded.beat_times), sevenths, beats_per_bar, phase=bar_phase)
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
    bpm: float | None = None,
    bar_phase: int | None = None,
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
        separated = stems_result or stems.separate(
            src, stems.DEFAULT, offline=offline, progress=lambda f: report("stems", f)
        )

    report("beats", 0.0)
    downbeats: Floats | None = None
    if use_stems and beats.beat_this_available():
        grid, downbeats = beats.track_beat_this(src, offline=offline)
    else:
        _, grid = beats.track_librosa(y)

    report("chords", 0.0)
    resolved = resolve_meter(spectral(y), grid, downbeats, beats_per_bar, sevenths, bpm, bar_phase)
    decoded = resolved.decoded
    times = decoded.beat_times

    report("structure", 0.0)
    vocals = audio.load(separated.paths["vocals"]) if separated is not None else None
    built = structure.build(
        times,
        decoded.labels,
        decoded.doubtful,
        decoded.scores,
        decoded.names,
        decoded.phase,
        beats_per_bar,
        sharpness=decoded.sharpness,
        energy_db=np.asarray(decoded.energy_db, dtype=float),
        vocal=None if vocals is None else parts.vocal_activity(vocals, times),
    )
    key = theory.Key(decoded.key_pc, decoded.key_mode)
    regions = key_regions(decoded, built, beats_per_bar)
    timed = [theory.TimedChord(c.pc, c.quality, c.beats) for b in built.bars for c in b.chords if c.pc >= 0]

    song_parts = None
    if separated is not None and built.bars:
        report("parts", 0.0)
        song_parts = _parts(separated, times, built, beats_per_bar, vocals)

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
        harmony=structure.harmony_summary(built, key, lambda bar: key_at(regions, bar)),
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
            bpm_hint=bpm,
        ),
        meta=Meta(__version__, time.monotonic() - started),
        key_regions=regions,
    )


def key_regions(decoded: Decoded, built: Structure, per: int) -> list[KeyRegion]:
    """The decoding's key regions on the chart's bars. A change found where the chords stop fitting the old key
    can sit a few bars late after pivot chords (a lift to the fourth shares six chords): it moves to the start of
    the part it falls in when that part starts up to 4 bars before (or 1 after), as lifts start on a part."""
    if not built.bars or not decoded.key_regions:
        return [KeyRegion(0, theory.Key(decoded.key_pc, decoded.key_mode))]
    starts = sorted({s.start for s in built.sections})
    out = [KeyRegion(0, theory.Key(decoded.key_regions[0][1], decoded.key_regions[0][2]))]
    for beat, tonic, mode in decoded.key_regions[1:]:
        bar = min(len(built.bars) - 1, max(0, (beat - built.first_beat) // per))
        near = [s for s in starts if bar - 4 <= s <= bar + 1]
        if near:
            bar = min(near, key=lambda s: (abs(s - bar), s))
        if bar > out[-1].bar:
            out.append(KeyRegion(bar, theory.Key(tonic, mode)))
    return out


def key_at(regions: list[KeyRegion], bar: int) -> theory.Key:
    """The key of a bar: the last region starting at or before it."""
    return next(r.key for r in reversed(regions) if r.bar <= bar)


def _parts(
    separated: stems.Stems, times: Floats, built: Structure, beats_per_bar: int, vocals: parts.Audio | None = None
) -> Parts:
    track = {
        name: vocals if name == "vocals" and vocals is not None else audio.load(p)
        for name, p in separated.paths.items()
    }
    shift = parts.drum_grid_shift(track["drums"], times)
    grid = parts.Grid.from_beats(times + shift, built.first_beat, beats_per_bar, n_bars=len(built.bars))
    guitar, keys = track["other"], track["other"]  # four stems: guitars and keys share one
    if "guitar" in track:  # six stems (spec 010): the strumming from the guitar, the voicing from the keys
        found = tracks.heard_instruments(separated)  # the same answer as the page's tracks
        silence = np.zeros_like(track["guitar"])
        keys = track["piano"] + track["other"] if "keys" in found else silence
        # No guitar: the strumming of the keys, as on a four-stem page; neither: nothing to read.
        guitar = track["guitar"] if "guitar" in found else keys
    return Parts(
        groove=parts.drum_groove(track["drums"], grid),
        bass=parts.bass_line(track["bass"], grid),
        comp=parts.comp_rhythm(guitar, grid),
        voicings=parts.voicings(keys, grid),
        vocal=parts.vocal_range(track["vocals"]),
        grid_shift=shift,
    )
