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
from woodshed import analysis, app, build, stems
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
        served.append(self.library.running is not None)  # one heavy job at a time: it holds the queue's turn
        release.set()
        self.library.queue.join()

    monkeypatch.setattr(app.AppServer, "serve_forever", serve_forever)
    started = time.monotonic()
    app.serve(root, Options(use_stems=False, open_page=False), port=0, open_browser=False)
    assert served == [True]
    assert time.monotonic() - started < 20
    assert data_of(root / "lift.woodshed")["song"]["parts"]["vocal"]["regions"][1]["high"] == 72


def test_a_failed_measure_is_tried_again_at_the_next_start(
    tmp_path: Path, sung_lift: Sung, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = library_with(tmp_path, sung_lift)
    page = root / "lift.woodshed"
    index = (page / "index.html").read_bytes()
    real = build.measure_vocal_regions

    def broken(page: Path, data: dict[str, Any]) -> list[dict[str, Any]]:
        raise RuntimeError("the vocal track could not be read")

    monkeypatch.setattr(build, "measure_vocal_regions", broken)
    lib = app.Library(root, Options(use_stems=False, open_page=False))
    told: list[str] = []
    lib.on_reload = told.append
    assert lib.measure_voices() == ["lift.woodshed"]
    lib.queue.join()
    assert (page / "index.html").read_bytes() == index  # the page as it was
    assert told == []
    assert "lift.woodshed: the voice range per key was not measured" in capsys.readouterr().out
    lib.interrupted()
    monkeypatch.setattr(build, "measure_vocal_regions", real)
    again = app.Library(root, Options(use_stems=False, open_page=False))  # the next start
    assert again.measure_voices() == ["lift.woodshed"]
    again.queue.join()
    assert len(data_of(page)["song"]["parts"]["vocal"]["regions"]) == 2


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
