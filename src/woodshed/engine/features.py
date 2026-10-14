"""Beat-synchronous features: bass and treble chroma, energy."""

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
class Features:
    tempo: float
    tuning: float
    beat_times: Floats
    bass: Floats  # (12, n_beats), C1-B2
    treble: Floats  # (12, n_beats), C3-B7
    energy_db: Floats  # (n_beats,), relative to the loud parts of the song


def extract(y: npt.NDArray[np.float32], beat_times: Floats | None = None) -> Features:
    """Bass and treble chroma per beat. `beat_times` imposes a grid from another tracker."""
    y_harm = librosa.effects.harmonic(y, margin=4)
    tuning = float(librosa.estimate_tuning(y=y_harm, sr=SR))
    cqt = np.abs(librosa.cqt(y_harm, sr=SR, hop_length=HOP, fmin=librosa.note_to_hz("C1"), n_bins=84, tuning=tuning))
    octaves = cqt.reshape(7, 12, -1)
    bass, treble = octaves[:2].sum(axis=0), octaves[2:].sum(axis=0)

    if beat_times is None:
        tempo, times = beat_tracking.track_librosa(y)
    else:
        times = np.asarray(beat_times, dtype=np.float64)
        tempo = 60.0 / float(np.median(np.diff(times)))
    frames = librosa.time_to_frames(times, sr=SR, hop_length=HOP)
    # sync() merges duplicate edges: drop them here so times and vectors stay aligned.
    keep = np.concatenate([[True], np.diff(frames) > 0]) & (frames < cqt.shape[1])
    times, frames = times[keep], frames[keep]
    edges = np.concatenate([frames, [cqt.shape[1]]])
    idx = [int(e) for e in edges]
    bass = librosa.util.sync(bass, idx, aggregate=np.median, pad=False)
    treble = librosa.util.sync(treble, idx, aggregate=np.median, pad=False)

    rms = librosa.feature.rms(y=y, hop_length=HOP)[0]
    rms_edges = np.concatenate([np.minimum(frames, len(rms) - 1), [len(rms)]])
    energy = librosa.util.sync(rms[None], [int(e) for e in rms_edges], aggregate=np.mean, pad=False)[0]
    energy_db = 20 * np.log10((energy + 1e-9) / (np.percentile(rms, 95) + 1e-9))
    return Features(tempo, tuning, times, bass, treble, energy_db)
