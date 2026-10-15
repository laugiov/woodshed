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
    drums[: drums.size // 2] = 0.0  # drums come in halfway, as on many ballads
    groove = parts.drum_groove(drums, grid("pop"))
    assert groove is not None and groove.bars <= 5
    assert groove.kick[0] > 0.9 and groove.snare[4] > 0.9


def test_grid_extrapolates_a_pickup_before_the_first_beat() -> None:
    beats = np.arange(1.0, 9.0, 0.5)
    g = parts.Grid.from_beats(beats, first_beat=-1, beats_per_bar=4, n_bars=2)
    assert g.bars[0][0] == pytest.approx(0.5)


def test_parts_survive_a_pickup_bar_before_time_zero() -> None:
    song = synth.render("pop")
    # Three beats of pickup before the first tracked beat: the first bar starts before 0 s.
    g = parts.Grid.from_beats(song.beats, first_beat=-3, beats_per_bar=4, n_bars=9)
    assert g.bars[0][0] < 0 and g.span(0)[0] == 0.0
    s = stems_at_rate("pop")
    groove = parts.drum_groove(s["drums"], g)  # any warning (empty slice, NaN) fails the test
    assert groove is not None and groove.bars >= 4
    voicings = parts.voicings(s["other"], g)
    assert len(voicings) == 9 and all(isinstance(v, list) for v in voicings)
    assert len(parts.bass_line(s["bass"], g)) == 9


def hat_only(n: int) -> np.ndarray:
    rng = np.random.default_rng(0)
    out = np.zeros(n, dtype=np.float32)
    burst = np.diff(rng.standard_normal(1100), prepend=0) * 0.2 * np.exp(-60 * np.arange(1100) / synth.SR)
    for t in np.arange(0, n / synth.SR - 0.1, 0.25):
        out[int(t * synth.SR) : int(t * synth.SR) + burst.size] += burst
    return out


def test_hat_only_drums_report_no_kick_and_no_snare() -> None:
    drums = hat_only(stems_at_rate("pop")["drums"].size)
    groove = parts.drum_groove(drums, grid("pop"))
    assert groove is not None
    assert max(groove.kick) < 0.2 and max(groove.snare) < 0.2
    assert set(np.flatnonzero(np.array(groove.hat) > 0.5)) >= {0, 2, 4, 6, 8, 10, 12, 14}


@pytest.mark.parametrize("level", [0.0, 1e-4])
def test_a_silent_or_hissing_stem_gives_no_part(level: float) -> None:
    n = stems_at_rate("pop")["other"].size
    stem = (np.random.default_rng(1).standard_normal(n) * level).astype(np.float32)
    g = grid("pop")
    assert parts.comp_rhythm(stem, g) == [0.0] * 16
    assert parts.voicings(stem, g) == [[]] * 8
    assert all(note is None for bar in parts.bass_line(stem, g) for note in bar)
    assert parts.drum_groove(stem, g) is None and parts.vocal_range(stem) is None


def test_funk_hats_survive_the_band_floor() -> None:
    groove = parts.drum_groove(stems_at_rate("funk")["drums"], grid("funk"))
    assert groove is not None and sum(h > 0.5 for h in groove.hat) >= 8


def test_faint_bleed_in_the_vocal_stem_does_not_widen_the_range() -> None:
    vocals = stems_at_rate("ballad")["vocals"]
    # A piano intro leaking into the vocal stem 30 dB below the singing, as on a piano ballad: twelve
    # G2 notes before the voice comes in.
    note = int(0.4 * synth.SR)
    t = np.arange(note) / synth.SR
    leak = 10 ** (-30 / 20) * np.abs(vocals).max() * np.sin(2 * np.pi * 98.0 * t) * np.hanning(note)
    gap = np.zeros(int(0.1 * synth.SR))
    intro = np.concatenate([np.concatenate([leak, gap]) for _ in range(12)]).astype(np.float32)
    rng = parts.vocal_range(np.concatenate([intro, vocals]))
    assert rng is not None and 72 <= rng.low <= rng.high <= 83
