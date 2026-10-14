"""Beat-synchronous features: bass and treble chroma, energy.

The spectral part (harmonic separation, CQT) is the expensive step and does not depend on the
beat grid, so it is computed once and re-synchronised when the grid changes.
"""

from __future__ import annotations

from dataclasses import dataclass

import librosa
import numpy as np
import numpy.typing as npt

from woodshed import beats as beat_tracking
from woodshed.audio import SR
from woodshed.beats import HOP

Floats = npt.NDArray[np.float64]


@dataclass(frozen=True)
class Spectral:
    tuning: float
    bass: Floats  # (12, n_frames), C1-B2
    treble: Floats  # (12, n_frames), C3-B7
    rms: Floats  # (n_frames,)
    onset: Floats  # (n_frames,) onset strength, for beat accents


@dataclass(frozen=True)
class Features:
    tempo: float
    tuning: float
    beat_times: Floats
    bass: Floats  # (12, n_beats)
    treble: Floats  # (12, n_beats)
    energy_db: Floats  # (n_beats,), relative to the loud parts of the song
    level_dbfs: Floats  # (n_beats,), absolute level reached by a quarter of the beat's frames, for silence


def spectral(y: npt.NDArray[np.float32]) -> Spectral:
    y_harm = librosa.effects.harmonic(y, margin=4)
    # Silence has no pitch to tune to (librosa would warn and return 0 anyway).
    tuning = float(librosa.estimate_tuning(y=y_harm, sr=SR)) if np.any(np.abs(y_harm) > 1e-4) else 0.0
    cqt = np.abs(librosa.cqt(y_harm, sr=SR, hop_length=HOP, fmin=librosa.note_to_hz("C1"), n_bins=84, tuning=tuning))
    octaves = cqt.reshape(7, 12, -1)
    rms = librosa.feature.rms(y=y, hop_length=HOP)[0]
    onset = librosa.onset.onset_strength(y=y, sr=SR, hop_length=HOP)
    return Spectral(
        tuning,
        octaves[:2].sum(axis=0),
        octaves[2:].sum(axis=0),
        np.asarray(rms, dtype=np.float64),
        np.asarray(onset, dtype=np.float64),
    )


def beat_accents(spec: Spectral, beat_times: Floats, window: float = 0.03) -> Floats:
    """Strongest onset within `window` seconds of each beat."""
    frames = librosa.time_to_frames(np.asarray(beat_times), sr=SR, hop_length=HOP)
    half = max(1, round(window * SR / HOP))
    n = len(spec.onset)
    out = np.zeros(len(frames))
    for i, f in enumerate(frames):
        window_frames = spec.onset[max(0, f - half) : min(n, f + half + 1)]
        out[i] = float(np.max(window_frames)) if window_frames.size else 0.0
    return out


def _upper_quartile(x: Floats, axis: int = -1) -> Floats:
    return np.asarray(np.percentile(x, 75, axis=axis), dtype=np.float64)


def sync(spec: Spectral, beat_times: Floats) -> Features:
    """Chroma and energy per beat on the given grid."""
    n_frames = spec.bass.shape[1]
    times = np.asarray(beat_times, dtype=np.float64)
    frames = librosa.time_to_frames(times, sr=SR, hop_length=HOP)
    # sync() merges duplicate edges: drop them here so times and vectors stay aligned.
    keep = np.concatenate([[True], np.diff(frames) > 0]) & (frames < n_frames)
    times, frames = times[keep], frames[keep]
    idx = [int(e) for e in np.concatenate([frames, [n_frames]])]
    bass = librosa.util.sync(spec.bass, idx, aggregate=np.median, pad=False)
    treble = librosa.util.sync(spec.treble, idx, aggregate=np.median, pad=False)
    rms_idx = [int(e) for e in np.concatenate([np.minimum(frames, len(spec.rms) - 1), [len(spec.rms)]])]
    energy = librosa.util.sync(spec.rms[None], rms_idx, aggregate=np.mean, pad=False)[0]
    energy_db = 20 * np.log10((energy + 1e-9) / (np.percentile(spec.rms, 95) + 1e-9))
    # Not the mean: a beat that ends where the music starts is silence with a note at its very end,
    # yet its mean level looks like a soft note. The level a quarter of its frames reach: a beat is
    # silent only when three quarters of it are (the last beat of a song keeps its chord).
    typical = librosa.util.sync(spec.rms[None], rms_idx, aggregate=_upper_quartile, pad=False)[0]
    level_dbfs = 20 * np.log10(typical * np.sqrt(2) + 1e-9)  # full-scale sine = 0 dBFS
    tempo = 60.0 / float(np.median(np.diff(times))) if len(times) > 1 else 0.0
    return Features(tempo, spec.tuning, times, bass, treble, energy_db, level_dbfs)


def extract(y: npt.NDArray[np.float32], beat_times: Floats | None = None) -> Features:
    """Bass and treble chroma per beat. `beat_times` imposes a grid from another tracker."""
    spec = spectral(y)
    if beat_times is None:
        tempo, times = beat_tracking.track_librosa(y)
        return _with_tempo(sync(spec, times), tempo)
    return sync(spec, beat_times)


def _with_tempo(f: Features, tempo: float) -> Features:
    return Features(tempo, f.tuning, f.beat_times, f.bass, f.treble, f.energy_db, f.level_dbfs)
