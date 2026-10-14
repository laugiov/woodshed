"""Instrument parts read from stems, checked against the exact synthetic stems."""

from __future__ import annotations

import numpy as np
import pytest

from tests import synth
from woodshed import parts


def stems_at_rate(name: str) -> dict[str, np.ndarray]:
    return {k: v.astype(np.float32) for k, v in synth.render(name).stems.items()}


def grid(name: str) -> parts.Grid:
    song = synth.render(name)
    return parts.Grid.from_beats(song.beats, first_beat=0, beats_per_bar=song.spec.beats_per_bar)


def test_grid_has_four_sixteenths_per_beat() -> None:
    g = grid("pop")
    assert len(g.bars) == 8 and all(len(b) == 16 for b in g.bars)
    step = np.diff(g.bars[0])
    assert np.allclose(step, 0.125)  # 120 BPM: a sixteenth lasts 125 ms


def test_waltz_grid_has_twelve_slots() -> None:
    assert all(len(b) == 12 for b in grid("waltz").bars)


def test_drum_grid_realignment_finds_a_late_tracker() -> None:
    song = synth.render("pop")
    late = song.beats + 0.04
    shift = parts.drum_grid_shift(stems_at_rate("pop")["drums"], late)
    assert shift == pytest.approx(-0.04, abs=0.015)


def test_groove_of_the_pop_song() -> None:
    groove = parts.drum_groove(stems_at_rate("pop")["drums"], grid("pop"))
    assert groove is not None
    assert set(np.flatnonzero(np.array(groove.kick) > 0.5)) == {0, 8}
    assert set(np.flatnonzero(np.array(groove.snare) > 0.5)) == {4, 12}
    assert set(np.flatnonzero(np.array(groove.hat) > 0.5)) >= {0, 2, 4, 6, 8, 10, 12, 14}
    assert groove.agreement["kick"] > 0.9 and groove.agreement["snare"] > 0.9


def test_no_drums_gives_no_groove() -> None:
    silence = np.zeros_like(stems_at_rate("pop")["drums"])
    assert parts.drum_groove(silence, grid("pop")) is None


def test_bass_line_of_the_pop_song() -> None:
    line = parts.bass_line(stems_at_rate("pop")["bass"], grid("pop"))
    roots = [36, 43, 45, 41] * 2  # C2 G2 A2 F2
    for bar, root in zip(line, roots, strict=True):
        assert bar[0] is not None and bar[0].midi == root
        assert {i for i, n in enumerate(bar) if n is not None} == {0, 4, 8, 12}


def test_funk_bass_plays_the_half_step_below_on_the_and() -> None:
    line = parts.bass_line(stems_at_rate("funk")["bass"], grid("funk"))
    first = line[0]  # Ab bar: G#2 then G2 on the "and"
    assert first[0] is not None and first[0].midi == 44
    assert first[2] is not None and first[2].midi == 43


def test_comping_rhythm_hits_every_beat() -> None:
    comp = parts.comp_rhythm(stems_at_rate("pop")["other"], grid("pop"))
    assert set(np.flatnonzero(np.array(comp) > 0.5)) == {0, 4, 8, 12}


def test_voicings_are_the_chord_tones() -> None:
    voicings = parts.voicings(stems_at_rate("pop")["other"], grid("pop"))
    expected = [{0, 4, 7}, {7, 11, 2}, {9, 0, 4}, {5, 9, 0}] * 2
    for got, want in zip(voicings, expected, strict=True):
        assert set(got[:3]) == want


def test_vocal_range_of_the_ballad_melody() -> None:
    rng = parts.vocal_range(stems_at_rate("ballad")["vocals"])
    assert rng is not None
    assert 72 <= rng.low <= rng.high <= 83  # the melody spans C5 to B5


def test_no_singing_gives_no_vocal_range() -> None:
    assert parts.vocal_range(stems_at_rate("pop")["vocals"]) is None


def test_groove_ignores_bars_where_the_drums_are_silent() -> None:
    drums = stems_at_rate("pop")["drums"].copy()
    drums[: drums.size // 2] = 0.0  # drums come in halfway, as on Let It Be
    groove = parts.drum_groove(drums, grid("pop"))
    assert groove is not None and groove.bars <= 5
    assert groove.kick[0] > 0.9 and groove.snare[4] > 0.9
