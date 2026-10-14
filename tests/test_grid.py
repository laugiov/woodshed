"""Beat grid conversions, shared by structure, parts and exports."""

import numpy as np
import pytest

from woodshed.grid import BeatGrid


def test_inside_the_grid_interpolates() -> None:
    g = BeatGrid.of([0.0, 0.5, 1.0, 1.6])
    assert g.time(1) == 0.5 and g.time(2.5) == pytest.approx(1.3)


def test_extrapolation_follows_local_tempo_drift() -> None:
    periods = np.linspace(0.5, 0.7, 64)  # a decelerating band
    times = np.concatenate([[0.0], np.cumsum(periods)])
    g = BeatGrid.of(times[:-1])
    true_next = times[-1]
    assert abs(g.time(len(times) - 1) - true_next) < 0.01  # the global median would be ~0.1 s off


def test_pickup_before_the_first_beat() -> None:
    g = BeatGrid.of(np.arange(1.0, 9.0, 0.5))
    assert g.time(-1) == pytest.approx(0.5)


def test_sixteenths_per_bar() -> None:
    g = BeatGrid.of(np.arange(0.0, 8.0, 0.5))
    bars = g.sixteenths(first_beat=-1, beats_per_bar=4, n_bars=2)
    assert len(bars) == 2 and len(bars[0]) == 16
    assert bars[0][0] == pytest.approx(-0.5) and np.allclose(np.diff(bars[1]), 0.125)


def test_a_grid_needs_two_beats() -> None:
    with pytest.raises(ValueError):
        BeatGrid.of([1.0])
