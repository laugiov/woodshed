"""Beat grid: one place that converts beat positions to times, inside and outside the tracked beats."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

Floats = npt.NDArray[np.float64]


@dataclass(frozen=True)
class BeatGrid:
    times: Floats

    def __post_init__(self) -> None:
        if len(self.times) < 2:
            raise ValueError("a beat grid needs at least two beats")

    @classmethod
    def of(cls, times: npt.ArrayLike) -> BeatGrid:
        return cls(np.asarray(times, dtype=np.float64))

    def _edge_period(self, at_end: bool) -> float:
        """Local beat period near an edge, so extrapolation follows tempo drift instead of the global median."""
        d = np.diff(self.times[-5:] if at_end else self.times[:5])
        return float(np.median(d))

    def time(self, i: float) -> float:
        """Time of beat position i (fractions allowed); extrapolates before the first and after the last beat."""
        n = len(self.times)
        if i < 0:
            return float(self.times[0] + i * self._edge_period(at_end=False))
        if i > n - 1:
            return float(self.times[-1] + (i - (n - 1)) * self._edge_period(at_end=True))
        lo = int(np.floor(i))
        hi = min(lo + 1, n - 1)
        return float(self.times[lo] + (i - lo) * (self.times[hi] - self.times[lo]))

    def sixteenths(self, first_beat: int, beats_per_bar: int, n_bars: int) -> list[Floats]:
        """Four slots per beat for each bar, starting at beat index `first_beat` (negative for a pickup)."""
        return [
            np.array([self.time(first_beat + b * beats_per_bar + q / 4) for q in range(beats_per_bar * 4)])
            for b in range(n_bars)
        ]
