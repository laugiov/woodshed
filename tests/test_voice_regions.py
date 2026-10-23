"""The singer's range per key region (spec 024b): measured by the analysis, carried by the song data, and measured
in the background, after the library starts, for the pages built before."""

from __future__ import annotations

import dataclasses
import json
import shutil
import threading
import time
from pathlib import Path
from typing import Any

import jsonschema
import numpy as np
import pytest
import soundfile as sf

from tests import synth
from tests.test_analysis import fake_stems
from woodshed import analysis, app, build, pitch, stems
from woodshed import song as song_json
from woodshed.model import KeyRegion, RegionRange, Song
from woodshed.run import MANIFEST, Options

TUNE = [72, 74, 76, 77, 79, 81]


@dataclasses.dataclass(frozen=True)
class Sung:
    wav: Path
    separated: stems.Stems
    song: Song
    page: Path  # as built: every page of a library is a copy of it


@pytest.fixture(scope="module")
def sung_lift(tmp_path_factory: pytest.TempPathFactory) -> Sung:
    """lift (C, D♭ from bar 17) with a voice: the tune over its 16 bars in C, then 5 semitones up to the end."""
    folder = tmp_path_factory.mktemp("sung")
    wav = synth.write("lift", folder).wav
    separated = fake_stems("lift", folder)
    beats = sum(b for _, b in synth.SONGS["lift"].chords)
    notes = (TUNE * 12)[:64] + [m + 5 for m in (TUNE * 8)[: beats - 64]]
    voice = synth.sung(notes, step=60 / synth.SONGS["lift"].bpm)
    up = np.interp(np.arange(0, voice.size, synth.SR / 44100), np.arange(voice.size), voice)
    sf.write(separated.paths["vocals"], np.stack([up, up], axis=1), 44100, subtype="PCM_24")
    song = analysis.analyze(wav, use_stems=True, stems_result=separated)
    page = build.build(song, wav, folder / "pages", separated)
    return Sung(wav, separated, song, page)


def data_of(page: Path) -> dict[str, Any]:
    found = build.DATA_BLOCK.search((page / "index.html").read_text(encoding="utf-8"))
    assert found is not None
    data: dict[str, Any] = json.loads(found.group(1))
    return data


def rewrite(page: Path, change: Any) -> None:
    index = page / "index.html"
    text = index.read_text(encoding="utf-8")
    found = build.DATA_BLOCK.search(text)
    assert found is not None
    data = json.loads(found.group(1))
    change(data)
    index.write_text(text[: found.start(1)] + build.script_json(data) + text[found.end(1) :], encoding="utf-8")


def library_with(tmp_path: Path, sung: Sung, *, measured: bool = False, name: str = "lift") -> Path:
    """A library holding the sung lift's page as an older woodshed left it: this page code, no regions."""
    root = tmp_path / "library"
    page = root / f"{name}.woodshed"
    shutil.copytree(sung.page, page)
    if not measured:
        rewrite(page, lambda d: d["song"]["parts"]["vocal"].pop("regions"))
        export = page / "exports" / "lift.json"
        song = json.loads(export.read_text(encoding="utf-8"))
        song["parts"]["vocal"].pop("regions")
        export.write_text(json.dumps(song, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    settings = {"page": build.page_revision(), "stems": True}
    manifest = {"settings": settings, "summary": {"title": name}, "complete": True}
    (page / MANIFEST).write_text(json.dumps(manifest), encoding="utf-8")
    return root


def test_the_analysis_measures_the_range_of_each_key_region(sung_lift: Sung) -> None:
    vocal = sung_lift.song.parts.vocal if sung_lift.song.parts else None
    assert [(r.bar, r.key.tonic) for r in sung_lift.song.key_regions] == [(0, 0), (16, 1)]
    assert vocal is not None
    assert [(r.bar, r.low, r.high) for r in vocal.regions] == [(0, 72, 81), (16, 77, 86)]
    assert [r.notes for r in vocal.regions] == [64, 48]


def test_the_song_data_carries_the_regions_only_after_a_key_change(sung_lift: Sung) -> None:
    data = song_json.to_json(sung_lift.song)
    assert data["parts"]["vocal"]["regions"] == [
        {"bar": 0, "low": 72, "high": 81, "notes": 64},
        {"bar": 16, "low": 77, "high": 86, "notes": 48},
    ]
    jsonschema.validate(data, song_json.schema())
    # A region too short to measure: null, and still valid.
    assert sung_lift.song.parts is not None and sung_lift.song.parts.vocal is not None
    vocal = sung_lift.song.parts.vocal
    short = dataclasses.replace(vocal, regions=(vocal.regions[0], RegionRange(16, None, None, 7)))
    parts = dataclasses.replace(sung_lift.song.parts, vocal=short)
    data = song_json.to_json(dataclasses.replace(sung_lift.song, parts=parts))
    assert data["parts"]["vocal"]["regions"][1] == {"bar": 16, "low": None, "high": None, "notes": 7}
    jsonschema.validate(data, song_json.schema())
    # A song in one key: its data as before, byte for byte (no "regions" at all).
    one = dataclasses.replace(vocal, regions=())
    song = dataclasses.replace(
        sung_lift.song,
        key_regions=[KeyRegion(0, sung_lift.song.key)],
        parts=dataclasses.replace(sung_lift.song.parts, vocal=one),
    )
    data = song_json.to_json(song)
    assert list(data["parts"]["vocal"]) == ["low", "high", "voiced_share"]
    jsonschema.validate(data, song_json.schema())


def test_the_schema_refuses_a_region_it_does_not_know(sung_lift: Sung) -> None:
    data = song_json.to_json(sung_lift.song)
    data["parts"]["vocal"]["regions"][0]["top"] = 90
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(data, song_json.schema())


def test_the_library_measures_an_older_page_in_the_background(tmp_path: Path, sung_lift: Sung) -> None:
    root = library_with(tmp_path, sung_lift)
    page = root / "lift.woodshed"
    before = data_of(page)
    lib = app.Library(root, Options(use_stems=False, open_page=False))
    told: list[str] = []
    lib.on_reload = told.append
    assert lib.measure_voices() == ["lift.woodshed"]
    lib.queue.join()
    after = data_of(page)
    vocal = dict(after["song"]["parts"]["vocal"])
    # The same numbers as the analysis's own, from the page's own vocal track.
    assert vocal["regions"] == song_json.to_json(sung_lift.song)["parts"]["vocal"]["regions"]
    assert {k: vocal[k] for k in ("low", "high", "voiced_share")} == {
        k: before["song"]["parts"]["vocal"][k] for k in ("low", "high", "voiced_share")
    }  # the whole song's range stays the analysis's
    after["song"]["parts"]["vocal"].pop("regions")
    assert after == before  # nothing else moved, the page stamp included
    assert told == ["lift.woodshed"]  # the open pages load it again
    export = json.loads((page / "exports" / "lift.json").read_text(encoding="utf-8"))
    assert export["parts"]["vocal"]["regions"] == vocal["regions"]  # the JSON export carries them too
    assert lib.measure_voices() == []  # measured: never again


def test_the_measure_never_holds_the_start(tmp_path: Path, sung_lift: Sung, monkeypatch: pytest.MonkeyPatch) -> None:
    root = library_with(tmp_path, sung_lift)
    release = threading.Event()
    measuring = threading.Event()

    def slow(page: Path, data: dict[str, Any]) -> list[dict[str, Any]]:
        measuring.set()
        assert release.wait(20)
        return [{"bar": 0, "low": 60, "high": 70, "notes": 20}, {"bar": 16, "low": 62, "high": 72, "notes": 9}]

    monkeypatch.setattr(build, "measure_vocal_regions", slow)
    served: list[bool] = []

    def serve_forever(self: app.AppServer) -> None:
        # The app is serving while the measure still runs: the start never waited for it.
        assert measuring.wait(20)
        served.append(self.library.busy())  # one heavy job at a time: the renders wait for it
        release.set()
        self.library.queue.join()

    monkeypatch.setattr(app.AppServer, "serve_forever", serve_forever)
    started = time.monotonic()
    app.serve(root, Options(use_stems=False, open_page=False), port=0, open_browser=False)
    assert served == [True]
    assert time.monotonic() - started < 20
    assert data_of(root / "lift.woodshed")["song"]["parts"]["vocal"]["regions"][1]["high"] == 72


REGIONS = [{"bar": 0, "low": 60, "high": 70, "notes": 20}, {"bar": 16, "low": 62, "high": 72, "notes": 9}]


def test_a_failed_measure_is_tried_again_at_the_next_start_but_not_at_every_start(
    tmp_path: Path, sung_lift: Sung, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = library_with(tmp_path, sung_lift)
    page = root / "lift.woodshed"
    index = (page / "index.html").read_bytes()

    def broken(page: Path, data: dict[str, Any]) -> list[dict[str, Any]]:
        raise RuntimeError("the vocal track could not be read")

    def start(expected: list[str]) -> app.Library:
        lib = app.Library(root, Options(use_stems=False, open_page=False))
        assert lib.measure_voices() == expected
        lib.queue.join()
        lib.interrupted()
        return lib

    monkeypatch.setattr(build, "measure_vocal_regions", broken)
    told: list[str] = []
    lib = app.Library(root, Options(use_stems=False, open_page=False))
    lib.on_reload = told.append
    assert lib.measure_voices() == ["lift.woodshed"]
    lib.queue.join()
    lib.interrupted()
    assert (page / "index.html").read_bytes() == index  # the page as it was
    assert told == []
    assert "lift.woodshed: the voice range per key was not measured" in capsys.readouterr().out
    assert (root / ".lift.woodshed.voice").is_file()  # the failure noted beside the page
    start(["lift.woodshed"])  # the next start tries again, once
    start([])  # failed twice: not at every start
    monkeypatch.setattr(app, "__version__", "9.9.9")
    start(["lift.woodshed"])  # another woodshed: tried again, twice at most
    start(["lift.woodshed"])
    start([])
    monkeypatch.setattr(build, "measure_vocal_regions", lambda page, data: REGIONS)
    rewrite(page, lambda d: d["song"].update(title="lift, edited"))  # the page changed: tried again
    start(["lift.woodshed"])
    assert data_of(page)["song"]["parts"]["vocal"]["regions"] == REGIONS
    assert not (root / ".lift.woodshed.voice").exists()  # measured: the note goes


def test_a_render_waited_for_goes_between_two_measures(
    tmp_path: Path, sung_lift: Sung, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = library_with(tmp_path, sung_lift)
    shutil.copytree(root / "lift.woodshed", root / "lift2.woodshed")
    events: list[str] = []
    measuring = threading.Event()
    release = threading.Event()

    def slow(page: Path, data: dict[str, Any]) -> list[dict[str, Any]]:
        events.append("measure " + page.name)
        if page.name == "lift.woodshed":
            measuring.set()
            assert release.wait(20)
        return REGIONS

    def render(src: Path, dst: Path, *args: Any, **kwargs: Any) -> None:
        events.append("render")
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(b"rendered")

    monkeypatch.setattr(build, "measure_vocal_regions", slow)
    monkeypatch.setattr(pitch, "render", render)
    lib = app.Library(root, Options(use_stems=False, open_page=False, pitch=False))
    lib.renders = pitch.Renders(root, busy=lib.busy)
    try:
        assert lib.measure_voices() == ["lift.woodshed", "lift2.woodshed"]
        assert measuring.wait(20)
        assert lib.renders.ask("lift.woodshed", "mix", 2, pitch.WAITED) == "queued"  # a page waits for it
        time.sleep(1.5)
        assert events == ["measure lift.woodshed"]  # never during a measure
        release.set()
        lib.queue.join()
        assert events == ["measure lift.woodshed", "render", "measure lift2.woodshed"]
    finally:
        lib.interrupted()


def test_a_page_rebuilt_during_the_measure_is_left_as_it_is(
    tmp_path: Path, sung_lift: Sung, monkeypatch: pytest.MonkeyPatch
) -> None:
    page = library_with(tmp_path, sung_lift) / "lift.woodshed"
    export = (page / "exports" / "lift.json").read_bytes()

    def rebuilt_meanwhile(page: Path, data: dict[str, Any]) -> list[dict[str, Any]]:
        index = page / "index.html"
        index.write_text(index.read_text(encoding="utf-8") + "<!-- rebuilt -->", encoding="utf-8")
        return REGIONS

    monkeypatch.setattr(build, "measure_vocal_regions", rebuilt_meanwhile)
    assert build.add_vocal_regions(page) is False
    rebuilt = (page / "index.html").read_bytes()
    assert rebuilt.endswith(b"<!-- rebuilt -->")
    assert "regions" not in data_of(page)["song"]["parts"]["vocal"]  # the new page, byte for byte
    assert (page / "exports" / "lift.json").read_bytes() == export
    assert not [p.name for p in page.iterdir() if p.name.startswith(".")]


def test_a_write_cut_short_leaves_the_page_and_nothing_else(
    tmp_path: Path, sung_lift: Sung, monkeypatch: pytest.MonkeyPatch
) -> None:
    page = library_with(tmp_path, sung_lift) / "lift.woodshed"
    before = {p.name: p.read_bytes() for p in (page / "index.html", page / "exports" / "lift.json")}
    monkeypatch.setattr(build, "measure_vocal_regions", lambda page, data: REGIONS)
    real = Path.replace
    for target in ("index.html", "lift.json"):

        def failing(self: Path, to: Any, target: str = target) -> Path:
            if Path(to).name == target:
                raise OSError("no space left on device")
            return real(self, to)

        monkeypatch.setattr(Path, "replace", failing)
        with pytest.raises(OSError):
            build.add_vocal_regions(page)
        monkeypatch.setattr(Path, "replace", real)
        assert not [p.name for p in page.rglob(".*")]  # no temporary file left
        assert (page / "index.html").read_bytes() == before["index.html"]  # the page as it was: measured again
        if target == "lift.json":  # the export goes first: never newer than the page, never half written
            assert (page / "exports" / "lift.json").read_bytes() == before["lift.json"]
        (page / "exports" / "lift.json").write_bytes(before["lift.json"])


def test_pages_that_need_no_measure_are_left_alone(
    tmp_path: Path, sung_lift: Sung, monkeypatch: pytest.MonkeyPatch, pages_built: Path
) -> None:
    root = library_with(tmp_path, sung_lift, measured=True, name="measured")
    shutil.copytree(sung_lift.page, root / "no-voice-track.woodshed")
    rewrite(root / "no-voice-track.woodshed", lambda d: d["song"]["parts"]["vocal"].pop("regions"))
    (root / "no-voice-track.woodshed" / "audio" / "solo-vocals.flac").unlink()
    shutil.copytree(pages_built, root / "one-key.woodshed")  # a song in one key: nothing to measure
    for page in root.glob("*.woodshed"):
        manifest = {"settings": {"page": build.page_revision()}, "summary": {"title": page.name}, "complete": True}
        (page / MANIFEST).write_text(json.dumps(manifest), encoding="utf-8")

    def never(page: Path, data: dict[str, Any]) -> list[dict[str, Any]]:
        raise AssertionError(f"{page.name} measured")

    monkeypatch.setattr(build, "measure_vocal_regions", never)
    lib = app.Library(root, Options(use_stems=False, open_page=False))
    assert lib.measure_voices() == []


@pytest.fixture(scope="module")
def pages_built(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The ballad (one key, a voice) as a page."""
    folder = tmp_path_factory.mktemp("ballad")
    wav = synth.write("ballad", folder).wav
    separated = fake_stems("ballad", folder)
    song = analysis.analyze(wav, use_stems=True, stems_result=separated)
    assert song.parts is not None and song.parts.vocal is not None and len(song.key_regions) == 1
    return build.build(song, wav, folder / "pages", separated)


def test_the_open_pages_are_told_to_load_the_measured_page(tmp_path: Path) -> None:
    srv = app.AppServer(app.Library(tmp_path / "library", Options(use_stems=False, open_page=False)))
    try:
        assert "updated" not in srv.live.payload()
        assert srv.library.on_reload is not None
        srv.library.on_reload("lift.woodshed")
        assert srv.live.payload()["updated"] == {"lift.woodshed": 1}  # views/band.js loads the page again
    finally:
        srv.library.interrupted()
        srv.server_close()
