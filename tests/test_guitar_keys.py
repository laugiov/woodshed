"""Guitar and keys apart (spec 010): the six-stem model, the keys sum, the instruments not heard."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from tests import synth
from tests.test_analysis import fake_stems
from woodshed import analysis, parts, stems, tracks
from woodshed.view import Track

RATE = 44100


def tone(seconds: float, db: float, start: float = 0.0, total: float | None = None) -> np.ndarray:
    total = total or seconds
    y = np.zeros(int(total * RATE), dtype=np.float32)
    t = np.arange(int(seconds * RATE)) / RATE
    y[int(start * RATE) : int(start * RATE) + t.size] = 10 ** (db / 20) * np.sqrt(2) * np.sin(2 * np.pi * 330 * t)
    return y


def windows(y: np.ndarray) -> np.ndarray:
    return parts.window_rms(y, RATE)


@pytest.mark.parametrize(
    ("signal", "loudest_db", "heard"),
    [
        (np.zeros(RATE * 30, dtype=np.float32), -20.0, False),  # silence
        (tone(30, -20), -20.0, True),  # plays all along
        (tone(4, -25, start=10, total=120), -20.0, True),  # a short keys intro in a long song
        (tone(120, -62), -20.0, False),  # bleed under -50 dBFS everywhere
        (tone(120, -45), -10.0, False),  # always 35 dB under the loudest instrument: what leaked in
    ],
)
def test_an_instrument_is_heard_by_what_it_plays_not_by_its_average(
    signal: np.ndarray, loudest_db: float, heard: bool
) -> None:
    loudest = 10 ** (loudest_db / 20)
    assert parts.heard(windows(signal), loudest) is heard


def test_the_models_and_the_page_s_model() -> None:
    assert stems.FOUR.stems == ("drums", "bass", "other", "vocals")
    assert set(stems.SIX.stems) == {"drums", "bass", "other", "vocals", "guitar", "piano"}
    assert stems.model_of({}) is stems.FOUR  # every page built before keeps four
    assert stems.model_of({"separation": "six"}) is stems.SIX
    assert stems.model_of({"separation": "nine"}) is stems.FOUR
    assert stems.DEFAULT is stems.SIX


def test_a_cache_entry_counts_only_with_its_model_s_stems(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WOODSHED_CACHE", str(tmp_path / "cache"))
    song = tmp_path / "song.wav"
    sf.write(song, np.zeros((RATE, 2)), RATE)
    for model in (stems.FOUR, stems.SIX):
        folder = stems.folder_of(stems.fingerprint(song), model)
        folder.mkdir(parents=True)
        for name in stems.FOUR.stems:  # four stems in both folders
            sf.write(folder / f"{name}.flac", np.zeros((RATE, 2)), RATE, subtype="PCM_24")
        (folder / stems.GAIN_FILE).write_text('{"gain": 1.0}', encoding="utf-8")
    assert stems.cached(song, stems.FOUR) is not None
    assert stems.cached(song, stems.SIX) is None  # no guitar.flac: separated again


def six_stems(folder: Path, keys: bool, guitar: bool = True, synth_keys: bool = False) -> stems.Stems:
    """The pop song's synthetic stems as a six-stem separation: its chord stem is the guitar, or the keys (on
    Demucs's piano, or left in "other" as a synth would be)."""
    four = fake_stems("pop", folder)
    chords, _ = sf.read(four.paths["other"], dtype="float32")
    silence = np.zeros_like(chords)
    paths = dict(four.paths)
    for name, signal in (
        ("guitar", chords if guitar else silence),
        ("piano", chords if keys and not synth_keys else silence),
        ("other", chords if keys and synth_keys else silence),
    ):
        sf.write(folder / f"pop-stems/{name}.flac", signal, RATE, subtype="PCM_24")
        paths[name] = folder / f"pop-stems/{name}.flac"
    return stems.Stems(four.folder, paths, from_cache=True, model=stems.SIX)


def ids(found: list[Track]) -> list[str]:
    return sorted(t.id for t in found)


def test_six_stems_give_the_guitar_and_the_keys_their_tracks(tmp_path: Path) -> None:
    found = tracks.write_tracks(synth.write("pop", tmp_path).wav, six_stems(tmp_path, keys=True), tmp_path / "page")
    instruments = ("bass", "drums", "guitar", "keys", "vocals")
    assert ids(found) == sorted(["mix", *(f"minus-{i}" for i in instruments), *(f"solo-{i}" for i in instruments)])
    labels = {t.id: t.label for t in found}
    assert labels["solo-guitar"] == "Guitar alone" and labels["minus-keys"] == "Without keys"
    for t in found:
        assert (tmp_path / "page" / t.file).is_file()


def test_an_instrument_not_heard_gets_no_track(tmp_path: Path) -> None:
    found = tracks.write_tracks(synth.write("pop", tmp_path).wav, six_stems(tmp_path, keys=False), tmp_path / "page")
    assert "solo-keys" not in ids(found) and "minus-keys" not in ids(found)
    assert "solo-guitar" in ids(found)


def test_four_stems_keep_their_nine_tracks(tmp_path: Path) -> None:
    found = tracks.write_tracks(synth.write("pop", tmp_path).wav, fake_stems("pop", tmp_path), tmp_path / "page")
    instruments = ("bass", "drums", "other", "vocals")
    assert ids(found) == sorted(["mix", *(f"minus-{i}" for i in instruments), *(f"solo-{i}" for i in instruments)])


@pytest.mark.parametrize(
    ("guitar", "keys"),
    [
        (True, False),  # the chords only on the guitar: a strumming grid, no keys voicing
        (False, True),  # only on the keys: their voicing, and the strumming read from them
        (False, False),  # neither: nothing read
    ],
)
def test_the_strumming_comes_from_the_guitar_and_the_voicing_from_the_keys(
    tmp_path: Path, guitar: bool, keys: bool
) -> None:
    wav = synth.write("pop", tmp_path).wav
    song = analysis.analyze(wav, use_stems=True, stems_result=six_stems(tmp_path, keys=keys, guitar=guitar))
    assert song.parts is not None
    assert any(song.parts.comp) is (guitar or keys)
    assert any(song.parts.voicings) is keys


def test_the_parts_and_the_tracks_take_the_same_answer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    wav = synth.write("pop", tmp_path).wav
    separated = six_stems(tmp_path, keys=True)
    monkeypatch.setattr(tracks, "heard_instruments", lambda s: frozenset({"guitar"}))  # one place decides
    song = analysis.analyze(wav, use_stems=True, stems_result=separated)
    assert song.parts is not None and not any(song.parts.voicings)
    assert "solo-keys" not in ids(tracks.write_tracks(wav, separated, tmp_path / "page"))


def test_a_synth_left_in_other_is_the_keys(tmp_path: Path) -> None:
    wav = synth.write("pop", tmp_path).wav
    separated = six_stems(tmp_path, keys=True, guitar=False, synth_keys=True)
    song = analysis.analyze(wav, use_stems=True, stems_result=separated)
    assert song.parts is not None and any(song.parts.voicings)
    found = tracks.write_tracks(wav, separated, tmp_path / "page")
    assert "solo-keys" in ids(found) and "solo-guitar" not in ids(found)


def test_four_stem_parts_are_unchanged(tmp_path: Path) -> None:
    from woodshed import audio

    wav = synth.write("pop", tmp_path).wav
    separated = fake_stems("pop", tmp_path)
    song = analysis.analyze(wav, use_stems=True, stems_result=separated)
    assert song.parts is not None and any(song.parts.comp) and any(song.parts.voicings)
    # Both read the one "other" track, never judged heard or not: as before six stems.
    other = audio.load(separated.paths["other"])
    times = np.asarray(song.beats)
    shift = song.parts.grid_shift
    grid = parts.Grid.from_beats(times + shift, song.structure.first_beat, 4, n_bars=len(song.structure.bars))
    assert song.parts.comp == parts.comp_rhythm(other, grid)
    assert song.parts.voicings == parts.voicings(other, grid)


# The separation travels with the page (spec 010, R1b): absent means four, for every page built before.


def test_a_page_built_before_stays_up_to_date(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from woodshed import run
    from woodshed.run import MANIFEST, Options, Reporter, first_pass

    monkeypatch.setattr(run, "stems_extra_installed", lambda: True)
    four = fake_stems("pop", tmp_path)
    monkeypatch.setattr(stems, "cached", lambda src, model: four if model is stems.FOUR else None)
    wav = synth.write("pop", tmp_path).wav
    out = tmp_path / "lib"
    first_pass(wav, Options(out=out, open_page=False, separation="four"), Reporter(), out)
    manifest = out / "pop.woodshed" / MANIFEST
    assert "separation" not in manifest.read_text(encoding="utf-8")  # as a page built before six stems
    again = first_pass(wav, Options(out=out, open_page=False), Reporter(), out)  # no --separation: the page's own
    assert not again.stems_to_come and again.mix_song is None  # up to date: nothing separated, nothing rebuilt


def test_a_new_page_is_separated_with_six_and_says_so(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from woodshed import run
    from woodshed.run import MANIFEST, Options, Reporter, first_pass

    monkeypatch.setattr(run, "stems_extra_installed", lambda: True)
    asked: list[stems.Model] = []
    monkeypatch.setattr(stems, "cached", lambda src, model: asked.append(model))
    out = tmp_path / "lib"
    done = first_pass(synth.write("pop", tmp_path).wav, Options(out=out, open_page=False), Reporter(), out)
    assert asked == [stems.SIX] and done.stems_to_come
    assert json.loads((out / "pop.woodshed" / MANIFEST).read_text(encoding="utf-8"))["settings"]["separation"] == "six"


@pytest.mark.parametrize("change", ["mix only", "another recording"])
def test_a_page_without_its_tracks_or_from_another_recording_is_separated_as_new(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    from woodshed import run
    from woodshed.run import Options, Reporter, first_pass

    monkeypatch.setattr(run, "stems_extra_installed", lambda: True)
    four = fake_stems("pop", tmp_path)
    monkeypatch.setattr(stems, "cached", lambda src, model: four if model is stems.FOUR else None)
    wav = synth.write("pop", tmp_path).wav
    out = tmp_path / "lib"
    first = Options(out=out, open_page=False, separation="four", use_stems=change != "mix only")
    first_pass(wav, first, Reporter(), out)
    if change == "another recording":
        other = synth.write("waltz", tmp_path / "other").wav
        wav = wav.with_name("pop.wav")
        wav.write_bytes(other.read_bytes())
    asked: list[stems.Model] = []
    monkeypatch.setattr(stems, "cached", lambda src, model: asked.append(model))
    first_pass(wav, Options(out=out, open_page=False), Reporter(), out)
    assert asked == [stems.SIX]


def test_downloaded_ignores_a_download_cut_short(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WOODSHED_CACHE", str(tmp_path / "cache"))
    hub = tmp_path / "cache" / "models" / "checkpoints"
    hub.mkdir(parents=True)
    (hub / f"{stems.SIX.signature}.th.1f2e.partial").write_bytes(b"x")
    assert not stems.downloaded(stems.SIX)
    (hub / f"{stems.SIX.signature}.th").write_bytes(b"x")
    assert stems.downloaded(stems.SIX)


def test_offline_without_the_six_stem_weights_keeps_four(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from woodshed import run
    from woodshed.run import Options, Reporter

    monkeypatch.setattr(stems, "downloaded", lambda model: model is stems.FOUR)
    said: list[str] = []
    report = Reporter()
    monkeypatch.setattr(report, "say", said.append)
    song = tmp_path / "new.wav"
    model = run._separation(song, tmp_path / "new.woodshed", Options(offline=True), report)
    assert model is stems.FOUR and any("--separation four" in line for line in said)
    assert run._separation(song, tmp_path / "new.woodshed", Options(), report) is stems.SIX  # online: six


def test_the_words_find_the_stems_of_the_page_s_own_model(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from woodshed import lyrics
    from woodshed.run import MANIFEST

    monkeypatch.setenv("WOODSHED_CACHE", str(tmp_path / "cache"))
    for model, settings in ((stems.FOUR, {}), (stems.SIX, {"separation": "six"})):
        page = tmp_path / f"{model.key}.woodshed"
        page.mkdir()
        (page / MANIFEST).write_text(json.dumps({"settings": {"source": "abc", **settings}}), encoding="utf-8")
        folder = stems.folder_of("abc", model)
        folder.mkdir(parents=True)
        (folder / "vocals.flac").write_bytes(b"x")
        assert lyrics.stems_folder(page) == folder


def test_the_library_keeps_a_page_s_separation(tmp_path: Path) -> None:
    from woodshed import app
    from woodshed.run import Options

    lib = app.Library(tmp_path / "library", Options(use_stems=False, open_page=False))
    assert lib._options_of({"stems": True}).separation == "four"  # resumed or bar lines moved: as it was built
    assert lib._options_of({"stems": True, "separation": "six"}).separation == "six"
    assert lib._options_of({}).separation is None  # no tracks yet (resumed, mix only): separated as a new page
    assert lib._options_of({"stems": False}).separation is None
    assert lib.options(separation="four").separation == "four"
    with pytest.raises(ValueError):
        lib.options(separation="five")


def test_the_tracks_that_hold_the_voice_keep_its_formants_in_another_key() -> None:
    from woodshed import pitch

    assert {"minus-guitar", "minus-keys"} <= pitch.FORMANTS_KEPT
    assert not {"solo-guitar", "solo-keys"} & pitch.FORMANTS_KEPT
