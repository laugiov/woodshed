"""Chord recognition engine."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import numpy.typing as npt

from woodshed import audio
from woodshed.engine.decoding import Config, Decoded, decode
from woodshed.engine.features import Features, extract

__all__ = ["Config", "Decoded", "Features", "decode", "detect", "extract"]


def detect(
    path: str | Path,
    sevenths: bool = False,
    beats_per_bar: int = 4,
    cfg: Config | None = None,
    beat_times: npt.ArrayLike | None = None,
    phase: int | None = None,
) -> Decoded:
    """Decode the chords of an audio file, one label per beat."""
    times = None if beat_times is None else np.asarray(beat_times, dtype=np.float64)
    return decode(extract(audio.load(path), times), sevenths, beats_per_bar, cfg, phase)
