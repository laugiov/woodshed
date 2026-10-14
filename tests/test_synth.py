"""The synthetic songs are the ground truth for every engine test, so they must be exact."""

from pathlib import Path

import numpy as np
import pytest

from tests import synth


@pytest.mark.parametrize("name", list(synth.SONGS))
def test_song_is_deterministic(name: str) -> None:
    a, b = synth.render(name), synth.render(name)
    assert np.array_equal(a.mix, b.mix)


@pytest.mark.parametrize("name", list(synth.SONGS))
def test_chord_labels_cover_the_whole_song(name: str) -> None:
    song = synth.render(name)
    spans = song.chords
    assert spans[0][0] == 0.0
    assert all(abs(spans[i][1] - spans[i + 1][0]) < 1e-9 for i in range(len(spans) - 1))
    assert spans[-1][1] == pytest.approx(len(song.mix) / synth.SR)


@pytest.mark.parametrize("name", list(synth.SONGS))
def test_beats_and_downbeats_match_the_meter(name: str) -> None:
    song = synth.render(name)
    spec = synth.SONGS[name]
    period = 60.0 / spec.bpm
    assert np.allclose(np.diff(song.beats), period)
    assert np.allclose(np.diff(song.downbeats), period * spec.beats_per_bar)
    assert song.downbeats[0] == pytest.approx(song.beats[spec.pickup])


@pytest.mark.parametrize("name", list(synth.SONGS))
def test_stems_add_up_to_the_mix(name: str) -> None:
    song = synth.render(name)
    total = sum(song.stems.values())
    assert np.allclose(total, song.mix, atol=1e-6)
    assert set(song.stems) == {"drums", "bass", "other", "vocals"}


def test_songs_are_short_enough_for_fast_tests() -> None:
    assert all(synth.render(n).mix.size / synth.SR <= 30.0 for n in synth.SONGS)


def test_write_creates_wav_and_lab(tmp_path: Path) -> None:
    out = synth.write("pop", tmp_path)
    assert out.wav.exists() and out.lab.exists()
    assert out.lab.read_text().splitlines()[0].split()[2] in {"N", "C"}
