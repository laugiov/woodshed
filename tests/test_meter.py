"""Meter: tempo octave, bar phase from labels and from tracked downbeats."""

from __future__ import annotations

import numpy as np

from woodshed import meter


def test_tempo_octave_detects_chords_changing_every_other_beat() -> None:
    labels = ["C", "C", "G", "G", "Am", "Am", "F", "F"] * 4
    strong_even = np.tile([1.0, 0.4], 16)
    assert meter.tempo_octave_parity(labels, 144.0, strong_even) == 0
    assert meter.tempo_octave_parity(["N", *labels], 144.0, np.append(0.4, strong_even)) == 1


def test_tempo_octave_needs_the_kept_beats_to_be_accented() -> None:
    # A real 130 BPM song with a chord every two beats: changes on one parity, but the beats in
    # between (the snare on 2 and 4) are as strong as the kept ones. Not halved.
    labels = ["C", "C", "G", "G", "Am", "Am", "F", "F"] * 4
    assert meter.tempo_octave_parity(labels, 130.0, np.tile([0.8, 1.0], 16)) is None


def test_tempo_octave_leaves_normal_songs_alone() -> None:
    flat = np.ones(32)
    assert meter.tempo_octave_parity(["C", "C", "G", "Am", "Am", "Am", "F", "C"] * 4, 144.0, flat) is None
    assert meter.tempo_octave_parity(["C", "C", "G", "G"] * 8, 100.0, flat) is None


def test_phase_from_downbeats_ignores_spurious_beat_three() -> None:
    grid = np.arange(0, 32, dtype=float)
    downbeats = np.sort(np.concatenate([grid[1::4], grid[3::4][:4]]))
    phase, share = meter.phase_from_downbeats(grid, downbeats)
    assert phase == 1 and share > 0.6


def test_phase_from_too_few_downbeats_has_no_confidence() -> None:
    phase, share = meter.phase_from_downbeats(np.arange(0, 32, dtype=float), np.array([]))
    assert share == 0.0 and phase == 0


def test_pick_phase_prefers_changes_then_accents() -> None:
    labels = ["C"] * 3 + ["G"] * 4 + ["Am"] * 4 + ["F"] * 4
    assert meter.pick_phase(labels, np.ones(len(labels))) == 3
    tied = ["C", "C", "G", "G"] * 4 + ["C"]
    accents = np.append(np.tile([1.0, 0.2, 0.6, 0.2], 4), 1.0)
    assert meter.pick_phase(tied, accents) == 0
