"""The woodshed command: build a page per song, the text chart, the cache, errors and exit codes."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from tests import synth
from tests.test_stems import install_fake_demucs
from woodshed import analysis, cli
from woodshed.engine.features import spectral


@pytest.fixture
def cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    folder = tmp_path / "cache"
    monkeypatch.setenv("WOODSHED_CACHE", str(folder))
    return folder


@pytest.fixture
def opened(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Pages the command would open in the browser (nothing is opened during tests)."""
    urls: list[str] = []

    def record(url: str, *args: object, **kwargs: object) -> bool:
        urls.append(url)
        return True

    monkeypatch.setattr("webbrowser.open", record)
    return urls


def install_full_length_demucs(monkeypatch: pytest.MonkeyPatch) -> None:
    """The fake Demucs, returning stems as long as the input (the parts analysis needs that)."""
    install_fake_demucs(monkeypatch, {})
    monkeypatch.setitem(__import__("sys").modules, "beat_this", None)

    def separate_tensor(self: object, wav: np.ndarray, sr: int) -> tuple[np.ndarray, dict[str, np.ndarray]]:
        return wav, {
            name: wav * share for name, share in (("drums", 0.3), ("bass", 0.3), ("other", 0.3), ("vocals", 0.1))
        }

    monkeypatch.setattr(__import__("sys").modules["demucs.api"].Separator, "separate_tensor", separate_tensor)


@pytest.fixture
def no_stems_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("demucs", "demucs.api", "beat_this", "beat_this.inference"):
        monkeypatch.setitem(__import__("sys").modules, name, None)


def page_data(folder: Path) -> dict[str, Any]:
    text = (folder / "index.html").read_text(encoding="utf-8")
    match = re.search(r'id="woodshed-data">(.*?)</script>', text, re.S)
    assert match is not None
    data: dict[str, Any] = json.loads(match.group(1))
    return data


def test_one_song_without_stems_gives_one_page(
    tmp_path: Path, cache: Path, opened: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    wav = synth.write("pop", tmp_path).wav
    assert cli.main([str(wav), "--no-stems", "-o", str(tmp_path / "out")]) == 0
    page = tmp_path / "out" / "pop.woodshed"
    assert (page / "index.html").is_file()
    assert opened == [(page / "index.html").as_uri()]
    err = capsys.readouterr().err
    for step in ("decode", "beats", "chords", "page"):
        assert step in err
    assert "MB" in err and str(page) in err  # where the page is, and its size


def test_the_page_goes_next_to_the_song_by_default(tmp_path: Path, cache: Path, opened: list[str]) -> None:
    wav = synth.write("pop", tmp_path).wav
    assert cli.main([str(wav), "--no-stems", "--no-open"]) == 0
    assert (tmp_path / "pop.woodshed" / "index.html").is_file() and opened == []


def test_without_the_stems_extra_the_page_says_how_to_get_it(
    tmp_path: Path, cache: Path, opened: list[str], no_stems_extra: None, capsys: pytest.CaptureFixture[str]
) -> None:
    wav = synth.write("pop", tmp_path).wav
    assert cli.main([str(wav), "--no-open"]) == 0
    err = capsys.readouterr().err
    assert "woodshed[stems]" in err
    assert [t["id"] for t in page_data(tmp_path / "pop.woodshed")["view"]["tracks"]] == ["mix"]


def test_with_stems_the_mix_page_opens_first_then_the_full_page_replaces_it(
    tmp_path: Path, cache: Path, opened: list[str], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    install_full_length_demucs(monkeypatch)
    seen: list[dict[str, Any]] = []
    real_build = __import__("woodshed.build", fromlist=["build"]).build

    def spy(*args: Any) -> Path:
        page: Path = real_build(*args)
        seen.append(page_data(page)["view"])
        return page

    monkeypatch.setattr("woodshed.run.build_page", spy)
    wav = synth.write("pop", tmp_path).wav
    assert cli.main([str(wav)]) == 0
    first, final = seen
    assert first["pending"] is not None and first["pending"]["eta_seconds"] > 0
    assert [t["id"] for t in first["tracks"]] == ["mix"]
    assert final["pending"] is None and len(final["tracks"]) == 9
    assert len(opened) == 1  # opened once, on the first page; reloading shows the final one
    assert "reload" in capsys.readouterr().err.lower()


def test_a_second_run_skips_an_up_to_date_page_and_cached_stems_skip_the_mix_page(
    tmp_path: Path, cache: Path, opened: list[str], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import shutil

    install_full_length_demucs(monkeypatch)
    wav = synth.write("pop", tmp_path).wav
    assert cli.main([str(wav), "--no-open"]) == 0
    builds: list[Path] = []
    real_build = __import__("woodshed.build", fromlist=["build"]).build

    def counting(*args: Any) -> Path:
        builds.append(real_build(*args))
        return builds[-1]

    monkeypatch.setattr("woodshed.run.build_page", counting)
    capsys.readouterr()
    assert cli.main([str(wav), "--no-open"]) == 0
    assert builds == [] and "up to date" in capsys.readouterr().err  # nothing analysed again
    assert cli.main([str(wav), "--no-open", "--sevenths"]) == 0  # other options: rebuilt
    assert len(builds) == 1 and page_data(builds[0])["view"]["pending"] is None  # stems were cached
    shutil.rmtree(builds[0])
    assert cli.main([str(wav), "--no-open"]) == 0
    assert len(builds) == 2 and page_data(builds[1])["view"]["pending"] is None


def test_a_folder_becomes_a_songbook(tmp_path: Path, cache: Path, opened: list[str]) -> None:
    setlist = tmp_path / "Friday rehearsal"
    for name in ("pop", "waltz"):
        synth.write(name, setlist)
    (setlist / "notes.txt").write_text("not a song")
    assert cli.main([str(setlist), "--no-stems"]) == 0
    index = setlist / "index.html"
    assert opened == [index.as_uri()]
    text = index.read_text(encoding="utf-8")
    assert "<h1>Friday rehearsal</h1>" in text and "2 songs" in text
    for folder in ("pop.woodshed", "waltz.woodshed"):
        assert f'href="{folder}/index.html"' in text and (setlist / folder / "index.html").is_file()


def test_a_songbook_opens_its_index_before_the_stems(
    tmp_path: Path, cache: Path, opened: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    install_full_length_demucs(monkeypatch)
    setlist = tmp_path / "set"
    synth.write("pop", setlist)
    events: list[str] = []
    real_separate = __import__("woodshed.stems", fromlist=["separate"]).separate

    def opening(url: str, *args: object, **kwargs: object) -> bool:
        events.append("open")
        return True

    def separating(*args: Any, **kwargs: Any) -> Any:
        events.append("separate")
        return real_separate(*args, **kwargs)

    monkeypatch.setattr("webbrowser.open", opening)
    monkeypatch.setattr("woodshed.stems.separate", separating)
    assert cli.main([str(setlist)]) == 0
    assert events == ["open", "separate"]
    assert "mix only" not in (setlist / "index.html").read_text(encoding="utf-8")  # rewritten with the stems


def test_an_empty_folder_is_an_error(tmp_path: Path, cache: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "empty").mkdir()
    assert cli.main([str(tmp_path / "empty"), "--no-open"]) == 1
    assert "no audio or video file" in capsys.readouterr().err


def test_the_songbook_index_escapes_titles(tmp_path: Path) -> None:
    from woodshed import songbook

    info = {"title": "<script>x</script>", "folder": "a b & c.woodshed", "key": "Bbm", "bpm": 120, "meter": "4/4",
            "duration": 75, "doubts": 2, "stems": False}  # fmt: skip
    html_text = songbook.index_html("Set <1>", [info])
    assert "<script>x" not in html_text and "&lt;script&gt;" in html_text
    assert 'href="a%20b%20%26%20c.woodshed/index.html"' in html_text and "1:15" in html_text
    assert "<td>B♭m</td>" in html_text


def test_several_songs_give_several_pages(tmp_path: Path, cache: Path, opened: list[str]) -> None:
    songs = [synth.write(n, tmp_path).wav for n in ("pop", "funk")]
    assert cli.main([*map(str, songs), "--no-stems", "--no-open"]) == 0
    assert (tmp_path / "pop.woodshed").is_dir() and (tmp_path / "funk.woodshed").is_dir()


def test_a_title_needs_a_single_song(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main(["a.wav", "b.wav", "--title", "Both"])
    assert exc.value.code == 2 and "--title" in capsys.readouterr().err


def test_errors_are_one_line_without_a_traceback(
    tmp_path: Path, cache: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main([str(tmp_path / "missing.mp3"), "--no-open"]) == 1
    err = capsys.readouterr().err
    assert "missing.mp3" in err and "not found" in err and "Traceback" not in err
    assert len(err.strip().splitlines()) == 1


def test_debug_shows_the_traceback(tmp_path: Path, cache: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main([str(tmp_path / "missing.mp3"), "--no-open", "--debug"]) == 1
    assert "Traceback" in capsys.readouterr().err


def test_ctrl_c_exits_with_130(
    tmp_path: Path, cache: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def interrupted(*args: object, **kwargs: object) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr("woodshed.run.analyze", interrupted)
    wav = synth.write("pop", tmp_path).wav
    assert cli.main([str(wav), "--no-stems", "--no-open"]) == 130
    assert "interrupted" in capsys.readouterr().err.lower()


def test_the_page_is_built_with_the_options(tmp_path: Path, cache: Path, opened: list[str]) -> None:
    wav = synth.write("waltz", tmp_path).wav
    args = [str(wav), "--no-stems", "--no-open", "--beats-per-bar", "3", "--sevenths", "--title", "Valse"]
    assert cli.main(args) == 0
    song = page_data(tmp_path / "Valse.woodshed")["song"]
    assert song["title"] == "Valse" and song["beats_per_bar"] == 3 and song["analysis"]["sevenths"] is True


# --bpm: the tempo the musician hears decides between half and double time.


def meter_case(name: str) -> tuple[Any, np.ndarray]:
    song = synth.render(name)
    return spectral(song.mix.astype(np.float32)), song.beats


def test_bpm_halves_a_grid_tracked_at_double_speed() -> None:
    spec, real = meter_case("rock")  # 130 BPM; the musician counts it at 65
    resolved = analysis.resolve_meter(spec, real, None, 4, sevenths=False, bpm=65)
    tempo = 60 / np.median(np.diff(resolved.decoded.beat_times))
    assert tempo == pytest.approx(65, rel=0.05) and resolved.halved


def test_bpm_doubles_a_grid_tracked_at_half_speed() -> None:
    spec, real = meter_case("ballad")  # 72 BPM; counted in eighths at 144
    resolved = analysis.resolve_meter(spec, real, None, 4, sevenths=False, bpm=144)
    tempo = 60 / np.median(np.diff(resolved.decoded.beat_times))
    assert tempo == pytest.approx(144, rel=0.05) and not resolved.halved


def test_bpm_keeps_a_grid_already_at_that_tempo() -> None:
    spec, real = meter_case("rock")
    resolved = analysis.resolve_meter(spec, real, None, 4, sevenths=False, bpm=128)
    assert len(resolved.decoded.beat_times) == len(real) and not resolved.halved


def test_bpm_is_checked(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main(["song.wav", "--bpm", "5"])
    assert exc.value.code == 2 and "--bpm" in capsys.readouterr().err


# woodshed chart: the text chart of the original script.


def test_chart_prints_the_timeline_and_the_grid(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    wav = synth.write("pop", tmp_path).wav
    assert cli.main(["chart", str(wav)]) == 0
    out = capsys.readouterr().out
    assert out.startswith("Tempo: ") and "| key: C |" in out
    assert "== Timeline ==" in out and "== Grid (4 beats per bar, offset " in out and "auto) ==" in out
    assert re.search(r"\| C +\. +\. +\. +\| G ", out)
    assert "Doubtful beats: " in out


def test_chart_writes_text_and_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    wav = synth.write("pop", tmp_path).wav
    txt, js = tmp_path / "chart.txt", tmp_path / "chart.json"
    assert cli.main(["chart", str(wav), "--txt", str(txt), "--json", str(js), "--sevenths"]) == 0
    assert txt.read_text(encoding="utf-8") == capsys.readouterr().out
    data = json.loads(js.read_text(encoding="utf-8"))
    for key in (
        "file",
        "tempo_bpm",
        "tuning_semitones",
        "key",
        "sevenths",
        "beats_per_bar",
        "offset",
        "offset_auto",
        "doubtful_ratio",
        "segments",
        "bars",
        "beats",
    ):
        assert key in data
    assert data["sevenths"] is True and data["file"] == "pop.wav"


def test_chart_offset_is_manual_and_checked(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    wav = synth.write("pop", tmp_path).wav
    assert cli.main(["chart", str(wav), "--offset", "1"]) == 0
    assert "offset 1 manual) ==" in capsys.readouterr().out
    with pytest.raises(SystemExit) as exc:
        cli.main(["chart", str(wav), "--offset", "4"])
    assert exc.value.code == 2


# woodshed cache


def test_cache_shows_its_size_and_clears_the_stems(cache: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (cache / "stems" / "htdemucs-abc").mkdir(parents=True)
    (cache / "stems" / "htdemucs-abc" / "drums.flac").write_bytes(b"x" * 2_000_000)
    (cache / "models").mkdir()
    (cache / "models" / "weights.th").write_bytes(b"x" * 1_000_000)
    assert cli.main(["cache"]) == 0
    out = capsys.readouterr().out
    assert str(cache) in out and "stems" in out and "2.0 MB" in out and "models" in out
    assert cli.main(["cache", "--clear"]) == 0
    assert not (cache / "stems").exists() and (cache / "models" / "weights.th").exists()
    assert cli.main(["cache", "--clear", "--models"]) == 0
    assert not (cache / "models").exists()


def test_a_linked_file_is_named_after_the_link(tmp_path: Path, cache: Path, opened: list[str]) -> None:
    wav = synth.write("pop", tmp_path / "takes").wav
    setlist = tmp_path / "setlist"
    setlist.mkdir()
    (setlist / "Our Song.wav").symlink_to(wav)
    assert cli.main([str(setlist), "--no-stems", "--no-open"]) == 0
    assert (setlist / "Our Song.woodshed").is_dir()
    assert page_data(setlist / "Our Song.woodshed")["song"]["title"] == "Our Song"


# Findings of the phase 4 review, each with the case that showed it.


def test_a_linked_song_with_stems_ends_in_one_complete_page(
    tmp_path: Path, cache: Path, opened: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    install_full_length_demucs(monkeypatch)
    wav = synth.write("pop", tmp_path / "takes").wav
    setlist = tmp_path / "set"
    setlist.mkdir()
    (setlist / "Our Song.wav").symlink_to(wav)
    assert cli.main([str(setlist), "--no-open"]) == 0
    pages = sorted(p.name for p in setlist.iterdir() if p.is_dir())
    assert pages == ["Our Song.woodshed"]
    assert json.loads((setlist / "Our Song.woodshed" / "woodshed.json").read_text())["complete"] is True
    assert page_data(setlist / "Our Song.woodshed")["view"]["pending"] is None


def test_two_files_with_the_same_name_get_two_pages(
    tmp_path: Path, cache: Path, opened: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    import soundfile as sf

    setlist = tmp_path / "set"
    wav = synth.write("pop", setlist).wav
    data, rate = sf.read(wav)
    sf.write(setlist / "pop.flac", data, rate)
    assert cli.main([str(setlist), "--no-stems", "--no-open"]) == 0
    assert sorted(p.name for p in setlist.iterdir() if p.is_dir()) == ["pop (flac).woodshed", "pop (wav).woodshed"]
    capsys.readouterr()
    assert cli.main([str(setlist), "--no-stems", "--no-open"]) == 0
    assert capsys.readouterr().err.count("up to date") == 2  # each page stays its own


def test_a_bad_file_in_a_songbook_does_not_stop_the_others(
    tmp_path: Path, cache: Path, opened: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    setlist = tmp_path / "set"
    synth.write("pop", setlist)
    (setlist / "a broken.wav").write_bytes(b"not audio")
    (setlist / "._pop.wav").write_bytes(b"macOS metadata")
    assert cli.main([str(setlist), "--no-stems", "--no-open"]) == 1
    err = capsys.readouterr().err
    assert "a broken.wav" in err and "._pop" not in err and "1 of 2 songs failed" in err
    assert (setlist / "pop.woodshed" / "index.html").is_file()
    assert "pop.woodshed/index.html" in (setlist / "index.html").read_text(encoding="utf-8")


@pytest.mark.parametrize("damage", ["index", "manifest-list", "manifest-no-summary"])
def test_a_damaged_page_is_rebuilt_not_reported_up_to_date(
    tmp_path: Path, cache: Path, opened: list[str], capsys: pytest.CaptureFixture[str], damage: str
) -> None:
    wav = synth.write("pop", tmp_path).wav
    assert cli.main([str(wav), "--no-stems", "--no-open"]) == 0
    page = tmp_path / "pop.woodshed"
    if damage == "index":
        (page / "index.html").unlink()
    elif damage == "manifest-list":
        (page / "woodshed.json").write_text("[]")
    else:
        manifest = json.loads((page / "woodshed.json").read_text())
        del manifest["summary"]
        (page / "woodshed.json").write_text(json.dumps(manifest))
    capsys.readouterr()
    assert cli.main([str(wav), "--no-stems", "--no-open"]) == 0
    assert "up to date" not in capsys.readouterr().err and (page / "index.html").is_file()


def test_an_output_folder_that_is_a_file_is_a_one_line_error(
    tmp_path: Path, cache: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    wav = synth.write("pop", tmp_path).wav
    blocker = tmp_path / "out"
    blocker.write_text("a file")
    assert cli.main([str(wav), "--no-stems", "--no-open", "-o", str(blocker)]) == 1
    err = capsys.readouterr().err
    assert "Traceback" not in err and "woodshed:" in err


def test_failed_stems_leave_a_page_without_the_reload_banner(
    tmp_path: Path, cache: Path, opened: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from woodshed.errors import StemsError

    install_full_length_demucs(monkeypatch)

    def broken(*args: object, **kwargs: object) -> None:
        raise StemsError("separation failed: out of memory")

    monkeypatch.setattr("woodshed.stems.separate", broken)
    wav = synth.write("pop", tmp_path).wav
    assert cli.main([str(wav), "--no-open"]) == 1
    page = tmp_path / "pop.woodshed"
    assert page_data(page)["view"]["pending"] is None  # no "reload in N min" that would never come true
    assert json.loads((page / "woodshed.json").read_text())["complete"] is False  # the next run tries again


def test_an_unreachable_bpm_hint_is_said(tmp_path: Path, cache: Path, capsys: pytest.CaptureFixture[str]) -> None:
    wav = synth.write("pop", tmp_path).wav  # 120 BPM: 30 is neither half nor double
    assert cli.main([str(wav), "--no-stems", "--no-open", "--bpm", "30"]) == 0
    assert "could not be reached" in capsys.readouterr().err


def test_a_folder_named_like_a_command_is_a_songbook(
    tmp_path: Path, cache: Path, opened: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    synth.write("pop", tmp_path / "chart")
    assert cli.main(["chart", "--no-stems", "--no-open"]) == 0
    assert (tmp_path / "chart" / "index.html").is_file()


def test_models_without_clear_is_a_usage_error(cache: Path) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main(["cache", "--models"])
    assert exc.value.code == 2


def test_a_bad_file_does_not_stop_a_songbook_given_after_it(
    tmp_path: Path, cache: Path, opened: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    bad = tmp_path / "bad.wav"
    bad.write_bytes(b"not audio")
    book = tmp_path / "book"
    synth.write("pop", book)
    assert cli.main([str(bad), str(book), "--no-stems", "--no-open"]) == 1
    assert (book / "pop.woodshed" / "index.html").is_file() and (book / "index.html").is_file()


def test_one_bad_file_among_several_still_builds_the_others(
    tmp_path: Path, cache: Path, opened: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    good = synth.write("pop", tmp_path).wav
    bad = tmp_path / "bad.wav"
    bad.write_bytes(b"not audio")
    assert cli.main([str(bad), str(good), "--no-stems", "--no-open"]) == 1
    assert (tmp_path / "pop.woodshed").is_dir() and "1 of 2 songs failed: bad.wav" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("layout", "expected"),
    [
        (("a/pop.wav", "b/pop.wav"), ["pop (wav, a).woodshed", "pop (wav, b).woodshed"]),
        (("pop.wav", "pop (wav).flac"), ["pop (wav).woodshed", "pop.woodshed"]),
        (("x/pop.wav", "pop.WAV"), ["pop (wav, tmp).woodshed", "pop (wav, x).woodshed"]),
    ],
)
def test_files_given_with_one_name_never_share_a_page(
    tmp_path: Path, cache: Path, opened: list[str], layout: tuple[str, str], expected: list[str]
) -> None:
    import shutil

    wav = synth.write("pop", tmp_path / "src").wav
    paths = []
    for rel in layout:
        target = tmp_path / rel.replace("tmp", "")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(wav, target)
        paths.append(str(target))
    out = tmp_path / "out"
    assert cli.main([*paths, "--no-stems", "--no-open", "-o", str(out)]) == 0
    pages = sorted(p.name for p in out.iterdir())
    expected = sorted(e.replace("tmp", tmp_path.name) for e in expected)  # "tmp": the test's own folder
    assert pages == expected and len({p.lower() for p in pages}) == 2  # distinct, even ignoring case


def test_a_renamed_song_says_where_its_old_page_is(
    tmp_path: Path, cache: Path, opened: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    wav = synth.write("pop", tmp_path).wav
    assert cli.main([str(wav), "--no-stems", "--no-open"]) == 0
    renamed = wav.rename(tmp_path / "Our Song.wav")
    capsys.readouterr()
    assert cli.main([str(renamed), "--no-stems", "--no-open"]) == 0
    assert "older page of this recording is left at" in capsys.readouterr().err and (tmp_path / "pop.woodshed").exists()


def test_a_new_analysis_revision_rebuilds_old_pages(
    tmp_path: Path, cache: Path, opened: list[str], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    wav = synth.write("pop", tmp_path).wav
    assert cli.main([str(wav), "--no-stems", "--no-open"]) == 0
    monkeypatch.setattr("woodshed.run.ANALYSIS_REVISION", 999)  # the analysis changed since
    capsys.readouterr()
    assert cli.main([str(wav), "--no-stems", "--no-open"]) == 0
    assert "up to date" not in capsys.readouterr().err


def test_a_change_to_the_page_code_rebuilds_old_pages(
    tmp_path: Path, cache: Path, opened: list[str], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Updating woodshed from git keeps the version number: the page's own code decides too.
    wav = synth.write("pop", tmp_path).wav
    assert cli.main([str(wav), "--no-stems", "--no-open"]) == 0
    capsys.readouterr()
    assert cli.main([str(wav), "--no-stems", "--no-open"]) == 0
    assert "up to date" in capsys.readouterr().err
    monkeypatch.setattr("woodshed.run.page_revision", lambda: "another page")
    assert cli.main([str(wav), "--no-stems", "--no-open"]) == 0
    assert "up to date" not in capsys.readouterr().err


def test_the_page_revision_follows_the_page_files(tmp_path: Path) -> None:
    from woodshed.build import page_revision

    folder = tmp_path / "page"
    (folder / "assets").mkdir(parents=True)
    (folder / "body.html").write_text("<p>one</p>")
    (folder / "assets" / "app.css").write_text("p {}")
    first = page_revision.__wrapped__(folder)
    assert page_revision.__wrapped__(folder) == first
    (folder / "assets" / "app.css").write_text("p { color: red }")
    changed = page_revision.__wrapped__(folder)
    assert changed != first
    (folder / ".DS_Store").write_bytes(b"finder")  # files a system or an editor leaves around
    (folder / "assets" / "app.css~").write_text("backup")
    assert page_revision.__wrapped__(folder) == changed
    assert len(page_revision()) == 16  # the installed page


def test_the_summary_counts_only_close_calls(tmp_path: Path, cache: Path) -> None:
    from woodshed import analysis
    from woodshed.run import summary

    wav = synth.write("pickup", tmp_path).wav
    song = analysis.analyze(wav, use_stems=False)
    doubts = [c.doubt for b in song.structure.bars for c in b.chords if c.doubt]
    assert doubts and all(d.kind == "timing" for d in doubts)  # a clear pickup chord
    assert summary(song, tmp_path / "pickup.woodshed")["doubts"] == 0


def _as_built_by_an_older_woodshed(page: Path) -> None:
    manifest = json.loads((page / "woodshed.json").read_text(encoding="utf-8"))
    manifest["settings"]["page"] = "0123456789abcdef"
    (page / "woodshed.json").write_text(json.dumps(manifest), encoding="utf-8")
    (page / "assets" / "app.css").write_text("/* the old page */", encoding="utf-8")
    (page / "assets" / "js" / "views" / "words.js").unlink()  # a script the old page did not have


def test_a_page_built_by_an_older_woodshed_gets_the_new_page_code_without_a_new_analysis(
    tmp_path: Path, cache: Path, opened: list[str], capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from woodshed import build, lyrics, run

    wav = synth.write("pop", tmp_path).wav
    assert cli.main([str(wav), "--no-stems", "--no-open"]) == 0
    page = tmp_path / "pop.woodshed"
    (page / lyrics.LYRICS_JS).write_text(
        "window.WOODSHED_LYRICS = {};\n", encoding="utf-8"
    )  # the page's own files stay
    data_before = build.DATA_BLOCK.search((page / "index.html").read_text(encoding="utf-8")).group(1)  # type: ignore[union-attr]
    _as_built_by_an_older_woodshed(page)

    def no_analysis(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("the analysis ran again")

    monkeypatch.setattr(run, "_analyze", no_analysis)
    capsys.readouterr()
    assert cli.main([str(wav), "--no-stems", "--no-open"]) == 0
    assert "page code updated" in capsys.readouterr().err
    shipped = Path(build.__file__).parent / "page" / "assets"
    assert (page / "assets" / "app.css").read_bytes() == (shipped / "app.css").read_bytes()
    assert (page / "assets" / "js" / "views" / "words.js").is_file()
    index = (page / "index.html").read_text(encoding="utf-8")
    assert "views/words.js" in index and build.DATA_BLOCK.search(index).group(1) == data_before  # type: ignore[union-attr]
    assert (page / lyrics.LYRICS_JS).read_text(encoding="utf-8") == "window.WOODSHED_LYRICS = {};\n"
    assert json.loads((page / "woodshed.json").read_text(encoding="utf-8"))["settings"]["page"] == build.page_revision()
    assert not [p.name for p in page.iterdir() if p.name.startswith(".")]  # nothing left behind


def test_page_data_of_another_format_is_rebuilt_not_given_new_code(tmp_path: Path, cache: Path) -> None:
    from woodshed import build, run

    wav = synth.write("pop", tmp_path).wav
    assert cli.main([str(wav), "--no-stems", "--no-open"]) == 0
    page = tmp_path / "pop.woodshed"
    _as_built_by_an_older_woodshed(page)
    from woodshed.view import VIEW_VERSION

    index = page / "index.html"
    before = index.read_text(encoding="utf-8")
    index.write_text(
        before.replace(f'"view_version":{VIEW_VERSION}', f'"view_version":{VIEW_VERSION - 1}'), encoding="utf-8"
    )
    assert index.read_text(encoding="utf-8") != before
    assert run.update_page_code(page) is None  # the page's data is not what this page code reads
    assert (page / "assets" / "app.css").read_text(encoding="utf-8") == "/* the old page */"
    assert json.loads((page / "woodshed.json").read_text(encoding="utf-8"))["settings"]["page"] != build.page_revision()


def test_the_library_updates_its_pages_when_it_starts(tmp_path: Path, cache: Path) -> None:
    from woodshed import app
    from woodshed.run import Options

    wav = synth.write("pop", tmp_path).wav
    library = tmp_path / "library"
    assert cli.main([str(wav), "--no-stems", "--no-open", "-o", str(library)]) == 0
    _as_built_by_an_older_woodshed(library / "pop.woodshed")
    lib = app.Library(library, Options(use_stems=False, open_page=False))
    assert lib.update_pages() == ["pop.woodshed"]
    assert lib.update_pages() == []  # up to date now


def test_a_page_the_library_cannot_update_is_said_stale(tmp_path: Path, cache: Path) -> None:
    from woodshed import app
    from woodshed.run import Options
    from woodshed.view import VIEW_VERSION

    library = tmp_path / "library"
    for name in ("pop", "waltz"):
        assert cli.main([str(synth.write(name, tmp_path).wav), "--no-stems", "--no-open", "-o", str(library)]) == 0
    old = library / "pop.woodshed"
    _as_built_by_an_older_woodshed(old)
    index = old / "index.html"
    text = index.read_text(encoding="utf-8")
    index.write_text(text.replace(f'"view_version":{VIEW_VERSION}', f'"view_version":{VIEW_VERSION - 1}'), "utf-8")
    lib = app.Library(library, Options(use_stems=False, open_page=False))
    assert lib.update_pages() == []  # its data is not what this page code reads
    stale = {p["folder"]: p.get("stale", False) for p in lib.pages()}
    assert stale == {"pop.woodshed": True, "waltz.woodshed": False}  # the home page says to analyse it again
    assert cli.main([str(synth.write("pop", tmp_path).wav), "--no-stems", "--no-open", "-o", str(library)]) == 0
    assert not {p["folder"]: p["stale"] for p in lib.pages()}["pop.woodshed"]  # analysed again: said no more


def test_a_refresh_cut_short_leaves_the_page_as_it_was(
    tmp_path: Path, cache: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from woodshed import run
    from woodshed.errors import WoodshedError

    wav = synth.write("pop", tmp_path).wav
    assert cli.main([str(wav), "--no-stems", "--no-open"]) == 0
    page = tmp_path / "pop.woodshed"
    _as_built_by_an_older_woodshed(page)
    index = (page / "index.html").read_text(encoding="utf-8")
    real = Path.replace
    calls: list[Path] = []

    def failing(self: Path, target: Any) -> Path:
        calls.append(Path(target))
        if len(calls) == 2:  # the new code moving in: the disk is full, the page is held open
            raise OSError("no space left on device")
        return real(self, target)

    monkeypatch.setattr(Path, "replace", failing)
    with pytest.raises(WoodshedError, match=r"could not update pop\.woodshed"):
        run.update_page_code(page)
    monkeypatch.setattr(Path, "replace", real)
    assert (page / "assets" / "app.css").read_text(
        encoding="utf-8"
    ) == "/* the old page */"  # its own code, with its own index
    assert (page / "index.html").read_text(encoding="utf-8") == index
    assert not [p.name for p in page.iterdir() if p.name.startswith(".")]
    assert run.update_page_code(page) is not None  # and the next start updates it


def test_a_page_that_cannot_be_updated_does_not_stop_the_library(
    tmp_path: Path, cache: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from woodshed import app
    from woodshed.run import Options

    library = tmp_path / "library"
    for name in ("pop", "ballad"):
        assert cli.main([str(synth.write(name, tmp_path).wav), "--no-stems", "--no-open", "-o", str(library)]) == 0

    def update(page: Path) -> dict[str, Any] | None:
        if page.name == "ballad.woodshed":
            raise PermissionError(13, "Permission denied")  # a page folder made by root in Docker
        return {"title": "pop"}

    monkeypatch.setattr(app, "update_page_code", update)
    lib = app.Library(library, Options(use_stems=False, open_page=False))
    assert lib.update_pages() == ["pop.woodshed"]


def test_a_ctrl_c_during_a_refresh_leaves_the_page_as_it_was(
    tmp_path: Path, cache: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from woodshed import run

    wav = synth.write("pop", tmp_path).wav
    assert cli.main([str(wav), "--no-stems", "--no-open"]) == 0
    page = tmp_path / "pop.woodshed"
    _as_built_by_an_older_woodshed(page)
    real = Path.replace
    calls: list[Path] = []

    def interrupted(self: Path, target: Any) -> Path:
        moved = real(self, target)
        calls.append(Path(target))
        if len(calls) == 1:  # right after the page's code was set aside
            raise KeyboardInterrupt
        return moved

    monkeypatch.setattr(Path, "replace", interrupted)
    with pytest.raises(KeyboardInterrupt):
        run.update_page_code(page)
    monkeypatch.setattr(Path, "replace", real)
    assert (page / "assets" / "app.css").read_text(encoding="utf-8") == "/* the old page */"
    assert not [p.name for p in page.iterdir() if p.name.startswith(".")]
