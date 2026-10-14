"""Beats: tempo octave, bar phase, and the optional beat_this tracker."""

from __future__ import annotations

import sys
import types
from pathlib import Path

import numpy as np
import pytest

from tests import synth
from woodshed import beats
from woodshed.engine import detect


@pytest.fixture(scope="module")
def songs(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    folder = tmp_path_factory.mktemp("beat-songs")
    return {name: synth.write(name, folder).wav for name in synth.SONGS}


def test_tempo_octave_detects_chords_changing_every_other_beat() -> None:
    labels = ["C", "C", "G", "G", "Am", "Am", "F", "F"] * 4
    assert beats.tempo_octave_parity(labels, tempo=144.0) == 0
    assert beats.tempo_octave_parity(["N", *labels], tempo=144.0) == 1


def test_tempo_octave_leaves_normal_songs_alone() -> None:
    labels = ["C", "C", "G", "Am", "Am", "Am", "F", "C"] * 4  # changes on odd and even beats
    assert beats.tempo_octave_parity(labels, tempo=144.0) is None
    assert beats.tempo_octave_parity(["C", "C", "G", "G"] * 8, tempo=100.0) is None  # not fast: keep


def test_halving_keeps_every_other_beat() -> None:
    times = np.arange(8, dtype=float)
    labels = list("aabbccdd")
    kept_times, kept_labels, kept_idx = beats.halve(times, labels, parity=0)
    assert list(kept_times) == [0, 2, 4, 6]
    assert kept_labels == ["a", "b", "c", "d"]
    assert kept_idx == [0, 2, 4, 6]


def test_phase_from_downbeats_ignores_spurious_beat_three() -> None:
    grid = np.arange(0, 32, dtype=float)
    true_downbeats = grid[1::4]
    spurious = grid[3::4][:4]  # a tracker that also marks beat 3 in places
    phase, share = beats.phase_from_downbeats(grid, np.sort(np.concatenate([true_downbeats, spurious])))
    assert phase == 1
    assert share > 0.6


def test_pick_phase_prefers_changes_then_accents() -> None:
    labels = ["C"] * 3 + ["G"] * 4 + ["Am"] * 4 + ["F"] * 4
    strength = np.ones(len(labels))
    assert beats.pick_phase(labels, strength) == 3
    tied = ["C", "C", "G", "G"] * 4 + ["C"]  # four changes on position 2, four on position 0
    accents = np.append(np.tile([1.0, 0.2, 0.6, 0.2], 4), 1.0)
    assert beats.pick_phase(tied, accents) == 0


def test_ballad_ends_at_its_real_tempo(songs: dict[str, Path]) -> None:
    """Whether or not the tracker doubles this ballad (it did on Let It Be), the result is 72 BPM."""
    res = detect(songs["ballad"], beats_per_bar=4)
    times = res.beat_times
    parity = beats.tempo_octave_parity(res.labels, res.tempo)
    if parity is not None:
        times, _, _ = beats.halve(res.beat_times, res.labels, parity)
    assert 60.0 / float(np.median(np.diff(times))) == pytest.approx(72, rel=0.05)


@pytest.mark.parametrize("name", ["pop", "waltz", "funk"])
def test_other_songs_are_not_halved(name: str, songs: dict[str, Path]) -> None:
    res = detect(songs[name], beats_per_bar=synth.SONGS[name].beats_per_bar)
    assert beats.tempo_octave_parity(res.labels, res.tempo) is None


def test_beat_this_missing_gives_a_clear_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "beat_this", None)
    assert not beats.beat_this_available()
    with pytest.raises(beats.MissingExtra, match=r"woodshed\[stems\]"):
        beats.track_beat_this(Path("song.wav"))


def test_beat_this_adapter_decodes_first_and_returns_arrays(
    monkeypatch: pytest.MonkeyPatch, songs: dict[str, Path]
) -> None:
    seen: dict[str, object] = {}

    class FakeFile2Beats:
        def __init__(self, checkpoint_path: str, device: str, dbn: bool) -> None:
            seen["init"] = (checkpoint_path, device, dbn)

        def __call__(self, path: str) -> tuple[list[float], list[float]]:
            seen["path"] = path
            assert Path(path).suffix == ".wav" and Path(path).exists()
            return [0.5, 1.0, 1.5, 2.0], [0.5, 2.0]

    inference = types.ModuleType("beat_this.inference")
    inference.File2Beats = FakeFile2Beats  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "beat_this", types.ModuleType("beat_this"))
    monkeypatch.setitem(sys.modules, "beat_this.inference", inference)
    b, d = beats.track_beat_this(songs["pop"])
    assert seen["init"] == ("final0", "cpu", False)
    assert seen["path"] != str(songs["pop"])  # re-encoded to a clean WAV first
    assert not Path(str(seen["path"])).exists()  # and cleaned up
    assert list(b) == [0.5, 1.0, 1.5, 2.0] and list(d) == [0.5, 2.0]
