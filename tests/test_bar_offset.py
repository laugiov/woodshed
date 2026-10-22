"""Moving the bar lines: the bar phase chosen by the band (the beat the band counts "one" on)."""

from __future__ import annotations

import json
import threading
import time
import traceback
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from tests import synth
from tests.test_app import request
from woodshed import analysis, app, cli, stems
from woodshed.build import DATA_BLOCK
from woodshed.cache import cache_dir
from woodshed.errors import WoodshedError
from woodshed.model import Song
from woodshed.run import MANIFEST, Options, Reporter, first_pass


@pytest.fixture(scope="module")
def pop(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return synth.write("pop", tmp_path_factory.mktemp("phase")).wav


def phase(song: Song) -> int:
    per = song.beats_per_bar
    return int(song.structure.first_beat % per)


def test_the_bar_phase_chosen_is_where_the_bars_start_and_the_beats_do_not_move(pop: Path) -> None:
    auto = analysis.analyze(pop, use_stems=False)
    for shift in (1, 2, 3):
        wanted = (phase(auto) + shift) % auto.beats_per_bar
        moved = analysis.analyze(pop, use_stems=False, bar_phase=wanted)
        assert phase(moved) == wanted
        assert moved.beats == auto.beats  # typed chords stay on their beats
    assert phase(analysis.analyze(pop, use_stems=False, bar_phase=phase(auto))) == phase(auto)


def test_the_bar_phase_is_kept_with_the_page_and_only_when_chosen(pop: Path, tmp_path: Path) -> None:
    out = tmp_path / "lib"
    first_pass(pop, Options(out=out, use_stems=False, open_page=False), Reporter(), out)
    settings = json.loads((out / "pop.woodshed" / MANIFEST).read_text(encoding="utf-8"))["settings"]
    assert "bar_phase" not in settings  # every page built before stays up to date
    first_pass(pop, Options(out=out, use_stems=False, open_page=False, bar_phase=1), Reporter(), out)
    settings = json.loads((out / "pop.woodshed" / MANIFEST).read_text(encoding="utf-8"))["settings"]
    assert settings["bar_phase"] == 1  # a later rebuild keeps it


def test_the_command_takes_the_bar_phase_and_checks_it(
    pop: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main([str(pop), "--no-stems", "--no-open", "--bar-phase", "4"])
    assert exc.value.code == 2 and "--bar-phase" in capsys.readouterr().err
    assert cli.main([str(pop), "--no-stems", "--no-open", "--bar-phase", "1", "-o", str(tmp_path)]) == 0
    settings = json.loads((tmp_path / "pop.woodshed" / MANIFEST).read_text(encoding="utf-8"))["settings"]
    assert settings["bar_phase"] == 1


# The library moves the bar lines of a page it holds: a new analysis with the band's bar phase.


@pytest.fixture
def library(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[app.AppServer]:
    monkeypatch.setenv("WOODSHED_CACHE", str(tmp_path / "cache"))
    srv = app.AppServer(app.Library(tmp_path / "library", Options(use_stems=False, open_page=False)))
    src = srv.library.songs / "pop.wav"
    src.write_bytes(synth.write("pop", tmp_path / "src").wav.read_bytes())
    first_pass(src, srv.library.options(), Reporter(), srv.library.root)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()
    srv.server_close()


def song_of(lib: app.Library) -> dict[str, Any]:
    page = (lib.root / "pop.woodshed" / "index.html").read_text(encoding="utf-8")
    found = DATA_BLOCK.search(page)
    assert found
    data: dict[str, Any] = json.loads(found.group(1))["song"]
    return data


def wait(lib: app.Library, job: app.Job) -> None:
    deadline = time.monotonic() + 120
    while job.status not in ("done", "failed"):
        assert time.monotonic() < deadline, job
        time.sleep(0.2)


def test_the_library_moves_the_bar_lines_and_keeps_the_beats(library: app.AppServer) -> None:
    lib = library.library
    before = song_of(lib)
    per = before["beats_per_bar"]
    wanted = (before["first_beat"] % per + 1) % per
    job = lib.move_bars({"page": "pop.woodshed", "bar_phase": wanted})
    assert job.kind == "bars" and job.page == "pop.woodshed"
    wait(lib, job)
    assert job.status == "done", job.message
    after = song_of(lib)
    assert after["first_beat"] % per == wanted and after["beats"] == before["beats"]
    settings = json.loads((lib.root / "pop.woodshed" / MANIFEST).read_text(encoding="utf-8"))["settings"]
    assert settings["bar_phase"] == wanted  # kept: a later rebuild by the library keeps it
    assert app.beats_key(after) == app.beats_key(before)  # typed chords stay
    assert library.live.payload()["moved"] == {"pop.woodshed": 1}  # the band's other devices load it again


def test_moving_the_bar_lines_is_refused_when_it_cannot_be_done(library: app.AppServer) -> None:
    lib = library.library
    with pytest.raises(ValueError, match=r"^the bar phase is out of range$"):
        lib.move_bars({"page": "pop.woodshed", "bar_phase": 9})
    job = lib.move_bars({"page": "pop.woodshed", "bar_phase": 1})
    with pytest.raises(PermissionError, match="already being worked on"):
        lib.move_bars({"page": "pop.woodshed", "bar_phase": 2})
    wait(lib, job)
    library.live.state = {"leader": "dev-12345678", "song": "pop.woodshed", "playing": True, "at": time.time()}
    with pytest.raises(PermissionError, match="playing"):
        lib.move_bars({"page": "pop.woodshed", "bar_phase": 2}, playing=library.live.playing)
    library.live.state["at"] = time.time() - 60  # a leader that vanished while playing does not block it
    assert not library.live.playing("pop.woodshed")
    library.live.state = {"leader": None}
    (lib.songs / "pop.wav").unlink()  # the original is gone: only the command line can do it
    with pytest.raises(ValueError, match=r"^the recording is no longer in the library: the command line moves them$"):
        lib.move_bars({"page": "pop.woodshed", "bar_phase": 2})


def test_a_page_with_parts_is_never_rebuilt_without_them(
    library: app.AppServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    lib = library.library
    manifest = lib.root / "pop.woodshed" / MANIFEST
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["settings"]["stems"] = True
    manifest.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(app, "stems_extra_installed", lambda: False)
    with pytest.raises(ValueError, match=r"^the bar lines of this song need the stems extra$"):
        lib.move_bars({"page": "pop.woodshed", "bar_phase": 1})
    monkeypatch.setattr(app, "stems_extra_installed", lambda: True)
    monkeypatch.setattr(stems, "cached", lambda src: None)
    with pytest.raises(ValueError, match=r"^the separated tracks are no longer in the cache: add the song again$"):
        lib.move_bars({"page": "pop.woodshed", "bar_phase": 1})
    queued: list[Any] = []
    monkeypatch.setattr(stems, "cached", lambda src: object())
    monkeypatch.setattr(lib.queue, "put", queued.append)
    lib.move_bars({"page": "pop.woodshed", "bar_phase": 1})
    assert queued[0][2].use_stems is True  # even when the library itself runs without the stems


def test_the_bar_lines_endpoint_needs_the_token_and_starts_a_job(library: app.AppServer) -> None:
    body = json.dumps({"page": "pop.woodshed", "bar_phase": 1}).encode()
    status, _, _ = request(library, "POST", "/api/bars", body, {"Content-Type": "application/json"})
    assert status == 403
    headers = {app.TOKEN_HEADER: library.token, "Content-Type": "application/json"}
    status, _, answer = request(library, "POST", "/api/bars", body, headers)
    assert status == 202 and json.loads(answer)["kind"] == "bars"
    wait(library.library, library.library.jobs[json.loads(answer)["id"]])


def test_a_phone_cannot_move_the_bar_lines(library: app.AppServer, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app.Handler, "_from_this_computer", lambda self: False)
    body = json.dumps({"page": "pop.woodshed", "bar_phase": 1}).encode()
    headers = {app.TOKEN_HEADER: library.token, "Content-Type": "application/json"}
    status, _, answer = request(library, "POST", "/api/bars", body, headers)
    assert status == 403 and b"computer that runs the app" in answer
    assert library.library.jobs == {}


@pytest.mark.parametrize("error", [WoodshedError, RuntimeError])
def test_bar_lines_that_did_not_move_leave_the_page_as_it_was(
    library: app.AppServer, monkeypatch: pytest.MonkeyPatch, error: type[Exception]
) -> None:
    lib = library.library
    page = lib.root / "pop.woodshed"
    before = {p.name: p.read_bytes() for p in (page / "index.html", page / MANIFEST)}

    def broken(*args: Any, **kwargs: Any) -> None:
        raise error(f"cannot read {lib.root / 'songs' / 'pop.wav'} with {cache_dir() / 'stems'}")

    monkeypatch.setattr(app, "first_pass", broken)
    monkeypatch.setattr(traceback, "print_exc", lambda: None)
    job = lib.move_bars({"page": "pop.woodshed", "bar_phase": 1})
    wait(lib, job)
    assert job.status == "failed"
    assert str(lib.root) not in job.message and str(cache_dir()) not in job.message  # no path told to the phones
    assert {p.name: p.read_bytes() for p in (page / "index.html", page / MANIFEST)} == before
    assert not app.Library.attempt(lib.songs / "pop.wav").exists()  # nothing to skip at the next start
    assert "moved" not in library.live.payload()
