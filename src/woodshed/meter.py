"""Meter from beats and chord labels: tempo octave and bar phase."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import numpy.typing as npt

Floats = npt.NDArray[np.float64]
FAST_TEMPO = 125.0  # above this, a tracker that doubled the tempo is plausible
SINGLE_PARITY = 0.8  # share of chord changes on one beat parity that reveals counted eighth notes
# Kept beats against the beats in between, by onset strength. A tracker that counted eighth notes
# puts every other beat on a weak "and": measured 1.2 (a piano ballad) to 2.1 on doubled grids, and
# 0.46 to 0.79 on true grids, including a 130 BPM song with a chord every two beats.
MIN_ACCENT_RATIO = 1.1


def _changes(labels: Sequence[str]) -> list[int]:
    return [i for i in range(1, len(labels)) if labels[i] != labels[i - 1] and "N" not in (labels[i], labels[i - 1])]


def tempo_octave_parity(labels: Sequence[str], tempo: float, accents: Floats) -> int | None:
    """Beat parity to keep when the tracker doubled the tempo, or None to keep every beat.

    Two cues must agree: chord changes (almost) all on one parity, and that parity clearly
    more accented than the other. Chords alone cannot tell a fast song with a chord every two
    beats from a slow one counted in eighth notes.
    """
    changes = _changes(labels)
    if tempo < FAST_TEMPO or len(changes) < 8:
        return None
    even = sum(1 for i in changes if i % 2 == 0) / len(changes)
    if max(even, 1 - even) < SINGLE_PARITY:
        return None
    parity = 0 if even >= 0.5 else 1
    kept, other = float(np.median(accents[parity::2])), float(np.median(accents[1 - parity :: 2]))
    return parity if kept >= MIN_ACCENT_RATIO * max(other, 1e-9) else None


def phase_from_downbeats(grid: Floats, downbeats: Floats, per_bar: int = 4) -> tuple[int, float]:
    """Beat-index residue holding the most detected downbeats, and its share (0 when there are none).

    Trackers sometimes add downbeats on beat 3 when chords change every two beats; the true
    downbeats are still the majority residue.
    """
    if len(downbeats) == 0:
        return 0, 0.0
    idx = [int(np.argmin(np.abs(grid - d))) for d in downbeats]
    counts = np.bincount([i % per_bar for i in idx], minlength=per_bar)
    return int(np.argmax(counts)), float(np.max(counts)) / max(1, int(np.sum(counts)))


def pick_phase(labels: Sequence[str], strength: Floats, per_bar: int = 4) -> int:
    """Bar phase from the labels: most chord changes on beat one, ties broken by the stronger accent."""
    counts = np.zeros(per_bar)
    for i in _changes(labels):
        counts[i % per_bar] += 1
    top = float(np.max(counts))
    candidates = [p for p in range(per_bar) if counts[p] >= 0.9 * top]
    accents = [float(np.mean(strength[p::per_bar])) for p in range(per_bar)]
    return max(candidates, key=lambda p: accents[p])
