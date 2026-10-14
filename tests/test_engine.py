"""Chord engine: same behaviour as the prototype, measured on the synthetic songs."""

from __future__ import annotations

import json
from pathlib import Path

import librosa
import numpy as np
import pytest

from tests import synth
from tests.scoring import majmin_accuracy
from woodshed import audio
from woodshed.engine import decoding as dec
from woodshed.engine import detect

GOLDEN = json.loads((Path(__file__).parent / "golden" / "engine.json").read_text())
SAME_LIBROSA = librosa.__version__ == GOLDEN["librosa"]


@pytest.fixture(scope="session")
def songs(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    folder = tmp_path_factory.mktemp("songs")
    return {name: synth.write(name, folder).wav for name in synth.SONGS}


def bpb(name: str) -> int:
    return synth.SONGS[name].beats_per_bar


@pytest.mark.parametrize("name", list(synth.SONGS))
def test_matches_the_prototype_or_its_accuracy(name: str, songs: dict[str, Path]) -> None:
    res = detect(songs[name], sevenths=False, beats_per_bar=bpb(name))
    gold = GOLDEN["songs"][name]
    if SAME_LIBROSA:
        assert res.labels == gold["labels"]
        assert res.key_name == gold["key"]
        assert res.offset == gold["offset"]
        assert [bool(x) for x in res.doubtful] == gold["doubtful"]
    truth = synth.render(name).chords
    gold_acc = majmin_accuracy(gold["starts"], gold["labels"], truth)
    assert majmin_accuracy(list(res.beat_times), res.labels, truth) >= gold_acc - 0.02


@pytest.mark.parametrize("name", list(synth.SONGS))
def test_sevenths_vocabulary_matches_the_prototype(name: str, songs: dict[str, Path]) -> None:
    res = detect(songs[name], sevenths=True, beats_per_bar=bpb(name))
    if not SAME_LIBROSA:
        pytest.skip("golden labels were produced with another librosa version")
    assert res.labels == GOLDEN["songs"][name]["labels7"]


def test_external_beats_and_phase_are_used(songs: dict[str, Path]) -> None:
    truth = synth.render("pop")
    res = detect(songs["pop"], sevenths=False, beat_times=truth.beats, phase=0)
    assert np.allclose(res.beat_times, truth.beats)
    assert res.offset == 0
    assert majmin_accuracy(list(res.beat_times), res.labels, truth.chords) > 0.9


def test_viterbi_prefers_staying_unless_evidence_is_strong() -> None:
    obs = np.log(np.array([[0.9, 0.6, 0.05], [0.1, 0.4, 0.95]]))
    stay, move = np.log(np.full(3, 0.9)), np.log(np.full(3, 0.1))
    assert list(dec.viterbi(obs, stay, move)) == [0, 0, 1]


def test_key_chords_of_c_major() -> None:
    chords = dec.key_chords(0, "maj", strict=True)
    assert {(0, ""), (2, "m"), (4, "m"), (5, ""), (7, ""), (9, "m")} <= chords
    assert (4, "") not in chords
    assert (4, "") in dec.key_chords(0, "maj")  # E major, the dominant of the relative minor


def test_change_probabilities_favour_bar_lines() -> None:
    cfg = dec.Config()
    p = dec.change_probs(8, 4, 1, cfg)
    assert p[1] == p[5] == cfg.change_downbeat
    assert p[3] == p[7] == cfg.change_halfbar
    assert p[0] == cfg.change_other


def test_doubtful_beats_flag_off_grid_starts_and_single_beats() -> None:
    labels = ["N", "C", "C", "C", "C", "G", "G", "G", "G", "Am", "F", "F", "F"]
    flags = dec.doubtful_beats(labels, 4, 1)
    assert not flags[1:5].any()  # starts on the downbeat
    assert flags[9]  # a single beat
    assert flags[10:13].all()  # starts off the grid


def test_missing_file_raises_a_clear_error(tmp_path: Path) -> None:
    with pytest.raises(audio.AudioError, match="not found"):
        audio.load(tmp_path / "nope.mp3")


def test_unreadable_file_raises_a_clear_error(tmp_path: Path) -> None:
    bad = tmp_path / "bad.mp3"
    bad.write_bytes(b"not audio at all")
    with pytest.raises(audio.AudioError, match="could not read"):
        audio.load(bad)


def test_wav_still_loads_without_ffmpeg(monkeypatch: pytest.MonkeyPatch, songs: dict[str, Path]) -> None:
    monkeypatch.setattr(audio.shutil, "which", lambda _name: None)
    y = audio.load(songs["pop"])
    assert y.dtype == np.float32
    assert abs(y.size / audio.SR - synth.render("pop").mix.size / synth.SR) < 0.01


def test_without_ffmpeg_an_mp3_gets_a_helpful_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(audio.shutil, "which", lambda _name: None)
    bad = tmp_path / "song.mp3"
    bad.write_bytes(b"ID3 not really")
    with pytest.raises(audio.AudioError, match="ffmpeg is not installed"):
        audio.load(bad)
