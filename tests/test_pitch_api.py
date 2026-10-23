"""The singer's key through the library (spec 007): GET and POST /api/pitch, the band's key, the static files."""

from __future__ import annotations

import json
import sys
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests import test_pitch_worker as worker
from tests.test_app import request
from woodshed import app, pitch
from woodshed.run import MANIFEST, Options

pytestmark = worker.pytestmark
fake_ffmpeg = worker.fake_ffmpeg  # an ffmpeg on PATH that copies instead of rendering
library = worker.library


@pytest.fixture
def server(tmp_path: Path, fake_ffmpeg: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[app.AppServer]:
    monkeypatch.setenv("WOODSHED_CACHE", str(tmp_path / "cache"))
    root = library(tmp_path / "lib")
    summary = {"title": "One", "key": "C", "bpm": 120, "meter": "4/4", "duration": 1, "doubts": 0, "stems": True}
    (root / "One.woodshed" / "index.html").write_text("<!doctype html>", encoding="utf-8")
    (root / "One.woodshed" / MANIFEST).write_text(json.dumps({"settings": {}, "summary": summary, "complete": True}))
    srv = app.AppServer(app.Library(root, Options(use_stems=False, open_page=False)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.library.interrupted()
    srv.shutdown()
    srv.server_close()


def post(srv: app.AppServer, body: object) -> tuple[int, dict[str, object]]:
    headers = {app.TOKEN_HEADER: srv.token, "Content-Type": "application/json"}
    status, _, answer = request(srv, "POST", "/api/pitch", json.dumps(body).encode(), headers)
    return status, json.loads(answer)


def state(srv: app.AppServer) -> dict[str, object]:
    status, _, answer = request(srv, "GET", "/api/pitch?page=One.woodshed")
    assert status == 200
    data: dict[str, object] = json.loads(answer)
    return data


def test_a_page_asks_for_a_track_in_another_key_and_gets_it(server: app.AppServer) -> None:
    assert state(server)["can"] is True
    status, answer = post(server, {"page": "One.woodshed", "track": "mix", "semitones": 2})
    assert status == 202 and answer["state"] in ("queued", "running", "ready")
    deadline = time.monotonic() + 10
    while state(server)["keys"] != {"up2": {"mix": "ready"}}:
        assert time.monotonic() < deadline
        time.sleep(0.1)
    status, headers, body = request(server, "GET", "/One.woodshed/audio/key/up2/mix.flac")
    assert status == 200 and headers["content-type"] == "audio/flac" and body[:4] == b"fLaC"
    assert headers["cache-control"] == "no-cache"  # rendered again under the same name: never an old copy
    assert ("One.woodshed", "up2") in server.library.renders.used if server.library.renders else False


@pytest.mark.parametrize(
    "body",
    [
        {"page": "One.woodshed", "track": "mix", "semitones": True},
        {"page": "One.woodshed", "track": "mix", "semitones": 7},
        {"page": "One.woodshed", "track": "mix", "semitones": 0},
        {"page": "One.woodshed", "track": "mix", "semitones": "2"},
        {"page": "Other.woodshed", "track": "mix", "semitones": 2},
        {"page": "One.woodshed", "track": "solo-drums", "semitones": 2},
        {"page": "One.woodshed", "track": "solo-kazoo", "semitones": 2},
        {"page": "One.woodshed", "track": "../mix", "semitones": 2},
    ],
)
def test_what_is_refused(server: app.AppServer, body: dict[str, object]) -> None:
    assert post(server, body)[0] == 400


def test_a_phone_may_ask_but_not_without_the_token(server: app.AppServer, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app.Handler, "_from_this_computer", lambda self: False)  # a singer's phone
    assert post(server, {"page": "One.woodshed", "track": "mix", "semitones": -1})[0] == 202
    status, _, _ = request(server, "POST", "/api/pitch", b"{}", {"Content-Type": "application/json"})
    assert status == 403


def test_a_temporary_render_is_never_served(server: app.AppServer) -> None:
    folder = server.library.root / "One.woodshed" / "audio" / "key" / "up2"
    folder.mkdir(parents=True)
    (folder / ".mix.1234.part").write_bytes(b"half a file")
    assert request(server, "GET", "/One.woodshed/audio/key/up2/.mix.1234.part")[0] == 404


def test_too_many_asks_are_answered_later(server: app.AppServer, monkeypatch: pytest.MonkeyPatch) -> None:
    def full(*args: object, **kwargs: object) -> str:
        raise pitch.Full("too many renders asked: try again in a minute")

    assert server.library.renders is not None
    monkeypatch.setattr(server.library.renders, "ask", full)
    assert post(server, {"page": "One.woodshed", "track": "mix", "semitones": 2})[0] == 429


def test_the_band_s_key_is_prepared_for_every_device(server: app.AppServer, monkeypatch: pytest.MonkeyPatch) -> None:
    asked: list[tuple[str, int, list[str]]] = []
    assert server.library.renders is not None
    monkeypatch.setattr(server.library.renders, "set_band_key", lambda p, n, t: asked.append((p, n, t)))
    headers = {app.TOKEN_HEADER: server.token, "Content-Type": "application/json"}
    body = json.dumps({"page": "One.woodshed", "transpose": 2, "key": "D"}).encode()
    assert request(server, "POST", "/api/band", body, headers)[0] == 200
    assert asked == [("One.woodshed", 2, ["mix", "solo-vocals", "minus-vocals"])]


def test_without_the_filter_or_the_program_or_with_no_pitch_nothing_is_rendered(
    tmp_path: Path, fake_ffmpeg: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = library(tmp_path / "lib")
    off = app.Library(root, Options(use_stems=False, open_page=False, pitch=False))
    assert off.renders is None
    monkeypatch.setenv("FAKE_RUBBERBAND", "0")
    pitch.available.cache_clear()
    monkeypatch.setattr(pitch, "program", lambda: None)  # nor the Rubber Band program (spec 017)
    assert app.Library(root, Options(use_stems=False, open_page=False)).renders is None


def test_without_the_filter_the_program_renders(
    tmp_path: Path, fake_ffmpeg: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_RUBBERBAND", "0")
    pitch.available.cache_clear()
    monkeypatch.setattr(pitch, "program", lambda: "rubberband")
    library_ = app.Library(library(tmp_path / "lib"), Options(use_stems=False, open_page=False))
    assert library_.renders is not None
    library_.interrupted()


def test_the_library_says_what_stands_in_the_way(
    server: app.AppServer, fake_ffmpeg: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # An ffmpeg without the filter (Linux: rubberband-cli then), a program the system blocks (not the installer).
    assert state(server)["ffmpeg"] is True
    monkeypatch.setattr(pitch, "has_ffmpeg", lambda: False)
    assert state(server)["ffmpeg"] is False
    assert state(server)["blocked"] is False
    monkeypatch.setattr(pitch, "blocked", lambda: True)
    assert state(server)["blocked"] is True


@pytest.mark.parametrize(("platform", "system"), [("darwin", "mac"), ("win32", "windows"), ("linux", "linux")])
def test_the_library_says_its_system_for_the_one_step_that_adds_the_key(
    server: app.AppServer, monkeypatch: pytest.MonkeyPatch, platform: str, system: str
) -> None:
    monkeypatch.setattr(pitch, "has_ffmpeg", lambda: True)  # no PATH lookup on a pretended system
    monkeypatch.setattr(pitch, "blocked", lambda: False)
    monkeypatch.setattr(sys, "platform", platform)
    assert state(server)["system"] == system  # the page names the installer (Mac, Windows) or the package (Linux)


def test_after_a_restart_the_band_s_key_is_prepared_again_at_the_first_ask(
    server: app.AppServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    headers = {app.TOKEN_HEADER: server.token, "Content-Type": "application/json"}
    body = json.dumps({"page": "One.woodshed", "transpose": 2, "key": "D"}).encode()
    assert request(server, "POST", "/api/band", body, headers)[0] == 200
    renders = server.library.renders
    assert renders is not None
    asked: list[tuple[str, int, list[str]]] = []
    monkeypatch.setattr(renders, "band", {})  # the app restarted: the band's key lives in the corrections file only
    monkeypatch.setattr(renders, "set_band_key", lambda p, n, t: asked.append((p, n, t)))
    post(server, {"page": "One.woodshed", "track": "solo-bass", "semitones": 2})  # a bassist's page asks first
    assert asked == [("One.woodshed", 2, ["mix", "solo-vocals", "minus-vocals"])]
