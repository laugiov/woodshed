"""Chord engine: same labels as the golden file for the installed librosa and numpy, on the synthetic songs."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from tests import synth
from tests.golden.regenerate import environment
from tests.scoring import majmin_accuracy
from woodshed import audio
from woodshed.engine import decoding as dec
from woodshed.engine import detect

_DATA = json.loads((Path(__file__).parent / "golden" / "engine.json").read_text())
GOLDEN = _DATA["environments"]
REFERENCE = _DATA["reference"]  # labels of the original implementation, never regenerated
# Exact labels are pinned on Linux, where the golden file is made. Other platforms (other BLAS and
# FFT builds) are held to the accuracy of the reference instead.
EXACT = sys.platform == "linux"


def golden(name: str) -> dict[str, Any]:
    installed = environment()
    if installed not in GOLDEN:
        pytest.fail(f"no golden entry for {installed}: run python -m tests.golden.regenerate and review the diff")
    entry: dict[str, Any] = GOLDEN[installed][name]
    return entry


@pytest.fixture(scope="session")
def songs(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    folder = tmp_path_factory.mktemp("songs")
    return {name: synth.write(name, folder).wav for name in synth.SONGS}


def bpb(name: str) -> int:
    return synth.SONGS[name].beats_per_bar


@pytest.mark.parametrize("name", list(synth.SONGS))
def test_matches_the_golden_labels(name: str, songs: dict[str, Path]) -> None:
    res = detect(songs[name], sevenths=False, beats_per_bar=bpb(name))
    if not EXACT:
        truth = synth.render(name).chords
        floor = majmin_accuracy(REFERENCE[name]["starts"], REFERENCE[name]["labels"], truth) - 0.02
        assert majmin_accuracy(list(res.beat_times), res.labels, truth) >= floor
        return
    gold = golden(name)
    assert res.labels == gold["labels"]
    assert res.key_name == gold["key"]
    assert res.offset == gold["offset"]
    assert [bool(x) for x in res.doubtful] == gold["doubtful"]


@pytest.mark.parametrize("name", list(synth.SONGS))
def test_every_golden_entry_is_as_accurate_as_the_reference(name: str) -> None:
    truth = synth.render(name).chords
    floor = majmin_accuracy(REFERENCE[name]["starts"], REFERENCE[name]["labels"], truth) - 0.02
    for entry in GOLDEN.values():
        assert majmin_accuracy(entry[name]["starts"], entry[name]["labels"], truth) >= floor


@pytest.mark.parametrize("name", list(synth.SONGS))
def test_sevenths_vocabulary_matches_the_golden_labels(name: str, songs: dict[str, Path]) -> None:
    if not EXACT:
        pytest.skip("exact labels are pinned on Linux only")
    res = detect(songs[name], sevenths=True, beats_per_bar=bpb(name))
    assert res.labels == golden(name)["labels7"]


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
    monkeypatch.setattr("woodshed.audio.shutil.which", lambda _name: None)
    y = audio.load(songs["pop"])
    assert y.dtype == np.float32
    assert abs(y.size / audio.SR - synth.render("pop").mix.size / synth.SR) < 0.01


def test_without_ffmpeg_an_mp3_gets_a_helpful_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("woodshed.audio.shutil.which", lambda _name: None)
    bad = tmp_path / "song.mp3"
    bad.write_bytes(b"ID3 not really")
    with pytest.raises(audio.AudioError, match="ffmpeg is not installed"):
        audio.load(bad)


def test_a_soft_passage_is_not_erased(tmp_path: Path) -> None:
    import soundfile as sf

    song = synth.render("pop")
    half = song.mix.size // 2
    soft = song.mix.copy()
    soft[:half] *= 10 ** (-15 / 20)  # the first half 15 dB quieter, like a soft verse
    wav = tmp_path / "soft.wav"
    sf.write(wav, soft, synth.SR)
    res = detect(wav)
    first_half = [lab for t, lab in zip(res.beat_times, res.labels, strict=True) if 1.2 < t < half / synth.SR]
    assert first_half and "N" not in first_half


def test_digital_silence_has_no_chords_and_an_unknown_key() -> None:
    from woodshed.engine.features import spectral, sync

    y = np.zeros(synth.SR * 8, dtype=np.float32)
    res = dec.decode(sync(spectral(y), np.arange(0.5, 7.5, 0.5)), False, 4)
    assert set(res.labels) == {"N"} and not res.key_known and res.clarity == 0.0
