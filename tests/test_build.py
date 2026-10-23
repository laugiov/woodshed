"""The page builder: one folder that opens from disk, tracks that add up, data embedded safely."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import jsonschema
import numpy as np
import pytest
import soundfile as sf

from tests import synth
from tests.test_analysis import fake_stems
from woodshed import analysis, build, song, theory, view
from woodshed.model import Song

HOSTILE = '</script><script>alert(1)</script><!-- "quotes" & \u2028 ü'


@pytest.fixture(scope="module")
def folder(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("build")


@pytest.fixture(scope="module")
def pop_song(folder: Path) -> tuple[Path, Song]:
    wav = synth.write("pop", folder).wav
    return wav, analysis.analyze(wav, use_stems=True, stems_result=fake_stems("pop", folder), title=HOSTILE)


@pytest.fixture(scope="module")
def page(folder: Path, pop_song: tuple[Path, Song]) -> Path:
    wav, result = pop_song
    return build.build(result, wav, folder / "out", fake_stems("pop", folder))


def embedded(page: Path) -> dict[str, object]:
    text = (page / "index.html").read_text(encoding="utf-8")
    match = re.search(r'<script type="application/json" id="woodshed-data">(.*?)</script>', text, re.S)
    assert match is not None
    data: dict[str, object] = json.loads(match.group(1))
    return data


@pytest.mark.parametrize(
    ("title", "name"),
    [
        ("Morning Song", "Morning Song.woodshed"),
        ('a/b\\c:d*e?"f<g>h|i', "a_b_c_d_e__f_g_h_i.woodshed"),
        (" . ", "song.woodshed"),
        ("..", "song.woodshed"),
        ("x" * 300, "x" * 200 + ".woodshed"),
    ],
)  # fmt: skip
def test_folder_names_are_safe_on_every_system(title: str, name: str) -> None:
    assert build.folder_name(title) == name


def test_embedded_json_cannot_end_its_script_element() -> None:
    text = build.script_json({"title": HOSTILE})
    assert "<" not in text and ">" not in text and "&" not in text and "\u2028" not in text
    assert json.loads(text) == {"title": HOSTILE}


def test_the_page_folder_has_the_page_assets_and_every_track(page: Path) -> None:
    assert (page / "index.html").is_file() and (page / "assets" / "app.css").is_file()
    assert (page / "assets" / "vendor" / "vexflow-4.2.2-bravura.js").is_file()
    names = sorted(p.name for p in (page / "audio").iterdir())
    assert names == sorted(
        ["mix.flac"] + [f"{k}-{s}.flac" for k in ("minus", "solo") for s in ("drums", "bass", "other", "vocals")]
    )
    for track in (page / "audio").iterdir():
        info = sf.info(track)
        assert (info.format, info.subtype, info.samplerate, info.channels) == ("FLAC", "PCM_24", 44100, 2)


def test_the_title_is_text_in_the_page(page: Path) -> None:
    text = (page / "index.html").read_text(encoding="utf-8")
    assert "<title>&lt;/script&gt;&lt;script&gt;alert(1)" in text
    assert text.count("</script>") == text.count("<script")  # nothing closes a script early
    assert embedded(page)["song"]["title"] == HOSTILE  # type: ignore[index]


def test_embedded_data_matches_both_schemas(page: Path) -> None:
    data = embedded(page)
    jsonschema.validate(data["song"], song.schema())
    assert song.cross_check(data["song"]) == []  # type: ignore[arg-type]
    jsonschema.validate(data["view"], view.schema())
    files = [t["file"] for t in data["view"]["tracks"]]  # type: ignore[index]
    assert all((page / f).is_file() for f in files)


def test_tracks_add_up_and_share_one_level(page: Path) -> None:
    mix, _ = sf.read(page / "audio" / "mix.flac")
    for stem in ("drums", "bass", "other", "vocals"):
        minus, _ = sf.read(page / "audio" / f"minus-{stem}.flac")
        solo, _ = sf.read(page / "audio" / f"solo-{stem}.flac")
        assert np.allclose(minus + solo, mix, atol=1e-4)  # same gain on every track
    assert np.max(np.abs(mix)) <= 0.999


def test_without_stems_there_is_only_the_mix(folder: Path) -> None:
    wav = synth.write("waltz", folder).wav
    result = analysis.analyze(wav, use_stems=False, beats_per_bar=3)
    page = build.build(result, wav, folder / "plain")
    assert [p.name for p in (page / "audio").iterdir()] == ["mix.flac"]
    assert [t["id"] for t in embedded(page)["view"]["tracks"]] == ["mix"]  # type: ignore[index]


def test_a_rebuild_replaces_the_folder_and_leaves_nothing_behind(folder: Path, pop_song: tuple[Path, Song]) -> None:
    wav, result = pop_song
    out = folder / "rebuild"
    first = build.build(result, wav, out)
    (first / "stale.txt").write_text("from an older build")
    second = build.build(result, wav, out)
    assert first == second and not (second / "stale.txt").exists()
    assert [p.name for p in out.iterdir()] == [second.name]


def test_view_tables_come_from_the_theory_module(pop_song: tuple[Path, Song]) -> None:
    _, result = pop_song
    tables = view.view(result, [])
    up_two = tables["transpositions"][2]
    assert up_two["key"] == "D" and up_two["roots"][7] == "A"  # G becomes A in D
    assert tables["transpositions"][0]["roots"][10] == "Bb"  # by degree: the bVII of C
    assert tables["transpositions"][6]["key"] == "F#"  # F# major is written with sharps
    assert tables["romans"]["m"][9] == "vi" and tables["romans"][""][7] == "V"
    timed = [theory.TimedChord(c.pc, c.quality, c.beats) for b in result.structure.bars for c in b.chords if c.pc >= 0]
    assert [t["capo"] for t in tables["transpositions"]] == [theory.suggest_capo(timed, t) for t in range(12)]
    assert tables["shapes"]["open"]["C"] == [-1, 3, 2, 0, 1, 0]


def test_loud_stems_lower_every_track_together(folder: Path, pop_song: tuple[Path, Song]) -> None:
    wav, result = pop_song
    loud = fake_stems("pop", folder)
    for path in loud.paths.values():  # stems stored at 4 times the level: minus tracks would clip
        data, rate = sf.read(path)
        sf.write(path, np.clip(data * 4, -1, 1), rate, subtype="PCM_24")
    page = build.build(result, wav, folder / "loud", loud)
    peaks = [float(np.max(np.abs(sf.read(p)[0]))) for p in (page / "audio").iterdir()]
    assert max(peaks) <= 0.999 + 1e-6


def test_the_mix_track_is_the_decoded_source_sample_for_sample(page: Path, pop_song: tuple[Path, Song]) -> None:
    from woodshed import audio

    wav, _ = pop_song
    source = audio.load(wav, sr=44100, channels=2)
    mix, _ = sf.read(page / "audio" / "mix.flac", always_2d=True)
    assert mix.shape == (source.shape[1], 2)
    assert np.max(np.abs(mix.T - source)) < 2 / 2**23 + 1e-9  # 24-bit rounding only


def stems_from(folder: Path, signals: dict[str, np.ndarray], gain: float) -> Any:
    from woodshed.stems import Stems

    folder.mkdir(parents=True, exist_ok=True)
    paths = {}
    for name, x in signals.items():
        paths[name] = folder / f"{name}.flac"
        sf.write(paths[name], np.stack([x, x], axis=1) * gain, 44100, subtype="PCM_24")
    return Stems(folder, paths, from_cache=True, gain=gain)


def test_stored_stem_gain_is_undone_and_short_stems_are_padded(folder: Path, pop_song: tuple[Path, Song]) -> None:
    from woodshed import audio

    wav, result = pop_song
    n = audio.load(wav, sr=44100, channels=2).shape[1]
    t = np.arange(n) / 44100
    signals = {
        name: 0.1 * np.sin(2 * np.pi * f * t)
        for name, f in (("drums", 100), ("bass", 55), ("other", 440), ("vocals", 660))
    }
    signals["vocals"] = signals["vocals"][: n - 5000]  # a stem a little shorter than the mix
    stems = stems_from(folder / "gain-stems", signals, gain=0.5)  # stored at half level, as the cache can
    page = build.build(result, wav, folder / "gain", stems)
    bass, _ = sf.read(page / "audio" / "solo-bass.flac", always_2d=True)
    assert np.max(np.abs(bass[:, 0] - signals["bass"])) < 1e-4  # back to the stem's real level
    vocals, _ = sf.read(page / "audio" / "solo-vocals.flac", always_2d=True)
    assert vocals.shape[0] == n and np.all(vocals[n - 5000 :] == 0)


def test_loud_tracks_are_lowered_by_one_common_factor(folder: Path, pop_song: tuple[Path, Song]) -> None:
    from woodshed import audio

    wav, result = pop_song
    n = audio.load(wav, sr=44100, channels=2).shape[1]
    t = np.arange(n) / 44100
    loud = {
        name: 0.9 * np.sin(2 * np.pi * f * t)
        for name, f in (("drums", 100), ("bass", 55), ("other", 440), ("vocals", 660))
    }
    page = build.build(result, wav, folder / "common", stems_from(folder / "loud-stems", loud, gain=1.0))
    mix_src = audio.load(wav, sr=44100, channels=2)[0]
    factors = []
    mix, _ = sf.read(page / "audio" / "mix.flac", always_2d=True)
    factors.append(np.max(np.abs(mix[:, 0])) / np.max(np.abs(mix_src)))
    for name, x in loud.items():
        solo, _ = sf.read(page / "audio" / f"solo-{name}.flac", always_2d=True)
        factors.append(np.max(np.abs(solo[:, 0])) / np.max(np.abs(x)))
    assert max(factors) < 1 and max(factors) - min(factors) < 1e-3  # the same gain on every track


@pytest.mark.parametrize("title", ["{{BODY}}", "{{DATA}}", "{{TITLE}}"])
def test_placeholders_in_a_title_stay_text(folder: Path, pop_song: tuple[Path, Song], title: str) -> None:
    import dataclasses

    wav, result = pop_song
    page = build.build(dataclasses.replace(result, title=title), wav, folder / "placeholders")
    data: Any = embedded(page)
    assert data["song"]["title"] == title
    html_text = (page / "index.html").read_text(encoding="utf-8")
    assert f"<title>{title} · woodshed</title>" in html_text and html_text.count('id="woodshed-data"') == 1


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("CON", "_CON.woodshed"),
        ("aux.mp3", "_aux.mp3.woodshed"),
        ("Lpt1", "_Lpt1.woodshed"),
        ("Console", "Console.woodshed"),
    ],
)
def test_windows_device_names_are_avoided(title: str, expected: str) -> None:
    assert build.folder_name(title) == expected


def test_long_titles_are_cut_in_bytes_not_characters(folder: Path) -> None:
    name = build.folder_name("曲" * 150)  # 450 bytes in UTF-8
    assert len(name.encode("utf-8")) <= build.MAX_NAME_BYTES + len(build.FOLDER_SUFFIX)
    (folder / name).mkdir()  # the file system accepts it


def test_undecodable_file_names_do_not_break_the_page(folder: Path, pop_song: tuple[Path, Song]) -> None:
    import dataclasses

    wav, result = pop_song
    odd = dataclasses.replace(result, title="song\udcff", file="song\udcff.wav")
    page = build.build(odd, wav, folder / "surrogates")
    data: Any = embedded(page)
    assert data["song"]["file"] == "song\ufffd.wav"


def test_the_page_folder_is_readable_by_others(page: Path) -> None:
    import os
    import stat

    umask = os.umask(0)
    os.umask(umask)
    assert stat.S_IMODE(page.stat().st_mode) == 0o777 & ~umask
    assert stat.S_IMODE((page / "index.html").stat().st_mode) == 0o666 & ~umask


def test_a_failed_build_keeps_the_previous_page(
    folder: Path, pop_song: tuple[Path, Song], monkeypatch: pytest.MonkeyPatch
) -> None:
    wav, result = pop_song
    out = folder / "keep"
    first = build.build(result, wav, out)
    before = (first / "index.html").read_text(encoding="utf-8")

    def broken(*args: object, **kwargs: object) -> None:
        raise RuntimeError("disk full")

    monkeypatch.setattr("woodshed.tracks.write_tracks", broken)
    with pytest.raises(RuntimeError, match="disk full"):
        build.build(result, wav, out)
    assert (first / "index.html").read_text(encoding="utf-8") == before
    assert [p.name for p in out.iterdir()] == [first.name]  # no temporary folder left


def test_a_page_without_words_still_loads_its_lyrics_script(page: Path) -> None:
    assert (page / "lyrics.js").read_text() == "window.WOODSHED_LYRICS = null;\n"


def test_words_placed_on_a_page_survive_a_rebuild(tmp_path: Path, pop_song: tuple[Path, Song]) -> None:
    from woodshed import lyrics

    wav, result = pop_song
    first = build.build(result, wav, tmp_path / "out")
    words = {"version": 1, "language": "auto", "text": "la la", "chords": [],
             "lines": [{"text": "la la", "tag": None, "block": 0, "backing": [], "sung": True, "check": None,
                        "words": [{"text": "la", "start": 1.0, "end": 1.4},
                                  {"text": "la", "start": 3.0, "end": 3.4}]}]}  # fmt: skip
    lyrics.write(first, words)
    again = build.build(result, wav, tmp_path / "out")
    kept = json.loads((again / lyrics.LYRICS).read_text())
    assert kept["lines"] == words["lines"]
    assert kept["chords"]  # placed again on the new analysis
    (cho,) = (again / "exports").glob("*.cho")
    assert "{start_of_verse" in cho.read_text()  # the songbook file has the words too
    assert (again / lyrics.LYRICS_JS).read_text().startswith("window.WOODSHED_LYRICS = {")


def test_parts_named_by_the_words_follow_the_new_analysis(tmp_path: Path, pop_song: tuple[Path, Song]) -> None:
    # The names the words gave belong to the old chart: a rebuild names the new chart's parts again.
    from woodshed import lyrics

    wav, result = pop_song
    first = build.build(result, wav, tmp_path / "out")
    stale = [{"name": "Chorus 1", "role": "chorus", "letter": "Z", "start": 0, "end": 99}]
    lyrics.write(first, {"version": 1, "language": "auto", "text": "la", "chords": [], "sections": stale,
                         "lines": [{"text": "la", "tag": None, "block": 0, "backing": [], "sung": True,
                                    "check": None, "words": [{"text": "la", "start": 1.0, "end": 1.4}]}]})  # fmt: skip
    again = build.build(result, wav, tmp_path / "out")
    kept = json.loads((again / lyrics.LYRICS).read_text())
    assert kept.get("sections") != stale


def test_a_songbook_file_that_cannot_be_written_keeps_the_words(
    tmp_path: Path, pop_song: tuple[Path, Song], monkeypatch: pytest.MonkeyPatch
) -> None:
    from woodshed import exports, lyrics

    wav, result = pop_song
    first = build.build(result, wav, tmp_path / "out")
    lyrics.write(first, {"version": 1, "language": "auto", "text": "la", "chords": [],
                         "lines": [{"text": "la", "tag": None, "block": 0, "backing": [], "sung": True,
                                    "check": None, "words": [{"text": "la", "start": 1.0, "end": 1.4}]}]})  # fmt: skip

    def broken(*args: object) -> None:
        raise KeyError("end")

    monkeypatch.setattr(exports, "write_chordpro", broken)
    again = build.build(result, wav, tmp_path / "out")
    assert json.loads((again / lyrics.LYRICS).read_text())["lines"][0]["text"] == "la"


def test_a_page_rebuilt_from_another_recording_keeps_the_text_not_the_times(
    tmp_path: Path, pop_song: tuple[Path, Song]
) -> None:
    from woodshed import lyrics

    wav, result = pop_song
    first = build.build(result, wav, tmp_path / "out")
    (first / "woodshed.json").write_text(json.dumps({"settings": {"source": "another-recording"}}))
    lyrics.write(first, {"version": 1, "text": "la la", "lines": [], "chords": []})
    again = build.build(result, wav, tmp_path / "out")
    assert not (again / lyrics.LYRICS).exists()
    assert json.loads((again / "lyrics.previous.json").read_text())["text"] == "la la"
    assert (again / lyrics.LYRICS_JS).read_text() == "window.WOODSHED_LYRICS = null;\n"
    third = build.build(result, wav, tmp_path / "out")  # set aside, and kept so
    assert json.loads((third / "lyrics.previous.json").read_text())["text"] == "la la"


NAN_LYRICS = '{"version": 1, "lines": [{"sung": true, "words": [{"start": NaN, "end": 1}]}]}'


@pytest.mark.parametrize("content", ["{not json", NAN_LYRICS, '{"version": 7}', "[]", "null", '"x"'])
def test_damaged_lyrics_never_break_a_rebuild(tmp_path: Path, pop_song: tuple[Path, Song], content: str) -> None:
    from woodshed import lyrics

    wav, result = pop_song
    first = build.build(result, wav, tmp_path / "out")
    (first / lyrics.LYRICS).write_text(content)
    again = build.build(result, wav, tmp_path / "out")
    assert (again / lyrics.LYRICS_JS).read_text() == "window.WOODSHED_LYRICS = null;\n"


def test_the_page_says_which_woodshed_wrote_its_code_and_found_its_chords(page: Path) -> None:
    from woodshed import __version__

    data = embedded(page)
    assert data["page"] == {"version": __version__, "analysis": analysis.REVISION}
    assert data["song"]["meta"]["version"] == __version__  # type: ignore[index]
    assert data["song"]["meta"]["analysis"] == analysis.REVISION  # type: ignore[index]


def as_analysed_by(page: Path, version: str, revision: int | None) -> None:
    """The page's data as an older woodshed wrote it: its analysis version, its revision or none, no page stamp."""
    index = page / "index.html"
    text = index.read_text(encoding="utf-8")
    found = build.DATA_BLOCK.search(text)
    assert found is not None
    data = json.loads(found.group(1))
    data.pop("page", None)
    data["song"]["meta"]["version"] = version
    data["song"]["meta"].pop("analysis", None)
    if revision is not None:
        data["song"]["meta"]["analysis"] = revision
    block = f'<script type="application/json" id="woodshed-data">{build.script_json(data)}</script>'
    index.write_text(text[: found.start()] + block + text[found.end() :], encoding="utf-8")


@pytest.mark.parametrize(
    ("kept", "manifest", "expected"),
    [(2, None, 2), (2, 3, 2), (None, 3, 3), (None, None, None)],
)  # fmt: skip
def test_a_refresh_stamps_this_version_and_keeps_the_analysis_version(
    tmp_path: Path, pop_song: tuple[Path, Song], kept: int | None, manifest: int | None, expected: int | None
) -> None:
    from woodshed import __version__

    wav, result = pop_song
    page = build.build(result, wav, tmp_path / "out")
    as_analysed_by(page, "0.4.0", kept)
    assert build.refresh_code(page, analysis=manifest)
    data = embedded(page)
    assert data["page"] == {"version": __version__, "analysis": analysis.REVISION}  # the code now running
    meta = data["song"]["meta"]  # type: ignore[index]
    assert meta["version"] == "0.4.0"  # the analysis is the same: still said as found by 0.4.0
    assert meta.get("analysis") == expected  # the page's own revision first, else the manifest's, else unknown
    jsonschema.validate(data["song"], song.schema())
