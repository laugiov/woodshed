"""woodshed app: the library server, its upload and processing queue, and its security rules."""

from __future__ import annotations

import http.client
import json
import signal
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.parse import quote

import pytest

from tests import synth
from tests.test_commands import install_full_length_demucs
from woodshed import app
from woodshed.errors import WoodshedError
from woodshed.run import Options, Reporter, first_pass


@pytest.fixture
def cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    folder = tmp_path / "cache"
    monkeypatch.setenv("WOODSHED_CACHE", str(folder))
    return folder


@pytest.fixture
def server(tmp_path: Path, cache: Path) -> Iterator[app.AppServer]:
    library = app.Library(tmp_path / "library", Options(use_stems=False, open_page=False))
    srv = app.AppServer(library)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield srv
    srv.shutdown()
    srv.server_close()


def request(
    srv: app.AppServer,
    method: str,
    path: str,
    body: bytes | None = None,
    headers: dict[str, str] | None = None,
    host: str | None = None,
) -> tuple[int, dict[str, str], bytes]:
    conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=30)
    sent = {"Host": host or f"127.0.0.1:{srv.port}", **(headers or {})}
    conn.request(method, path, body=body, headers=sent)
    r = conn.getresponse()
    data = r.read()
    conn.close()
    return r.status, {k.lower(): v for k, v in r.getheaders()}, data


def upload(srv: app.AppServer, name: str, data: bytes, query: str = "", token: str | None = None) -> tuple[int, Any]:
    headers = {app.TOKEN_HEADER: srv.token if token is None else token, "Content-Type": "application/octet-stream"}
    status, _, body = request(srv, "POST", f"/api/songs?name={quote(name)}{query}", data, headers)
    return status, json.loads(body)


def wait_done(srv: app.AppServer, timeout: float = 120) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        _, _, body = request(srv, "GET", "/api/songs")
        state: dict[str, Any] = json.loads(body)
        if state["jobs"] and all(j["status"] in ("done", "failed") for j in state["jobs"]):
            return state
        time.sleep(0.2)
    raise AssertionError("the job did not finish")


def test_the_home_page_carries_its_token_and_a_strict_policy(server: app.AppServer) -> None:
    status, headers, body = request(server, "GET", "/")
    assert status == 200 and server.token in body.decode()
    assert (
        "default-src 'self'" in headers["content-security-policy"]
        and "frame-ancestors 'none'" in headers["content-security-policy"]
    )


def test_the_home_page_says_the_library_s_version_and_links_its_changelog(server: app.AppServer) -> None:
    from woodshed import __version__

    body = request(server, "GET", "/")[2].decode()
    assert f'data-testid="version">woodshed {__version__}</span>' in body and "{{" not in body
    for href in (
        "https://github.com/laugiov/woodshed/blob/main/CHANGELOG.md",
        "https://github.com/laugiov/woodshed#install",
    ):
        assert f'<a href="{href}" target="_blank" rel="noopener"' in body


def test_an_uploaded_song_becomes_a_page_in_the_list(server: app.AppServer, tmp_path: Path) -> None:
    wav = synth.write("pop", tmp_path / "src").wav
    status, job = upload(server, "My Song.wav", wav.read_bytes())
    assert status == 202 and job["status"] == "queued"
    state = wait_done(server)
    assert state["jobs"][0]["status"] == "done", state["jobs"][0]["message"]
    [song] = state["songs"]
    assert song["title"] == "My Song" and song["folder"] == "My Song.woodshed" and song["complete"]
    status, _, page = request(server, "GET", "/My%20Song.woodshed/index.html")
    assert status == 200 and b"woodshed-data" in page


def test_upload_options_reach_the_analysis(server: app.AppServer, tmp_path: Path) -> None:
    wav = synth.write("waltz", tmp_path / "src").wav
    upload(server, "waltz.wav", wav.read_bytes(), "&beats_per_bar=3&sevenths=1")
    wait_done(server)
    manifest = json.loads((server.library.root / "waltz.woodshed" / "woodshed.json").read_text())
    assert manifest["settings"]["beats_per_bar"] == 3 and manifest["settings"]["sevenths"] is True


def test_the_same_name_twice_gets_two_pages(server: app.AppServer, tmp_path: Path) -> None:
    wav = synth.write("pop", tmp_path / "src").wav
    upload(server, "pop.wav", wav.read_bytes())
    upload(server, "pop.mp3.wav", wav.read_bytes())
    upload(server, "POP.flac", wav.read_bytes())  # a different extension, the same name
    wait_done(server)
    names = sorted(p.name for p in server.library.songs.iterdir())
    assert names == ["POP (2).flac", "pop.mp3.wav", "pop.wav"]


def test_a_failed_song_is_reported_and_the_queue_goes_on(server: app.AppServer, tmp_path: Path) -> None:
    upload(server, "broken.wav", b"not audio at all")
    wav = synth.write("pop", tmp_path / "src").wav
    upload(server, "pop.wav", wav.read_bytes())
    state = wait_done(server)
    by_name = {j["name"]: j for j in state["jobs"]}
    assert by_name["broken.wav"]["status"] == "failed" and by_name["broken.wav"]["message"]
    assert by_name["pop.wav"]["status"] == "done"


def test_with_stems_the_page_is_listed_before_the_separation_ends(
    tmp_path: Path, cache: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_full_length_demucs(monkeypatch)
    gate = threading.Event()
    real = __import__("woodshed.stems", fromlist=["separate"]).separate

    def slow(*args: Any, **kwargs: Any) -> Any:
        gate.wait(10)
        return real(*args, **kwargs)

    monkeypatch.setattr("woodshed.stems.separate", slow)
    library = app.Library(tmp_path / "library", Options(open_page=False))
    srv = app.AppServer(library)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        upload(srv, "pop.wav", synth.write("pop", tmp_path / "src").wav.read_bytes())
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            state = json.loads(request(srv, "GET", "/api/songs")[2])
            # The page is listed a moment before the job says it separates: both are waited for.
            if state["songs"] and state["jobs"][0]["status"] == "separating":
                break
            time.sleep(0.2)
        # The separation is held at the gate: the page is there, not complete, while it runs.
        assert state["songs"][0]["complete"] is False and state["jobs"][0]["status"] == "separating"
        gate.set()
        state = wait_done(srv)
        assert state["songs"][0]["complete"] is True and state["songs"][0]["stems"] is True
    finally:
        gate.set()
        srv.shutdown()
        srv.server_close()


# Serving: audio seeking needs ranges; nothing outside the library is ever served.


def test_audio_is_served_in_ranges(server: app.AppServer) -> None:
    track = server.library.root / "x.woodshed" / "audio" / "mix.flac"
    track.parent.mkdir(parents=True)
    track.write_bytes(bytes(range(256)) * 4)
    status, headers, body = request(server, "GET", "/x.woodshed/audio/mix.flac", headers={"Range": "bytes=10-19"})
    assert status == 206 and body == bytes(range(10, 20)) and headers["content-range"] == "bytes 10-19/1024"
    assert headers["content-type"] == "audio/flac" and headers["accept-ranges"] == "bytes"
    status, _, body = request(server, "GET", "/x.woodshed/audio/mix.flac", headers={"Range": "bytes=-4"})
    assert status == 206 and body == bytes(range(252, 256))
    status, headers, _ = request(server, "GET", "/x.woodshed/audio/mix.flac", headers={"Range": "bytes=5000-"})
    assert status == 416 and headers["content-range"] == "bytes */1024"


@pytest.mark.parametrize(
    "path",
    [
        "/../secret.txt",
        "/%2e%2e/secret.txt",
        "/songs/../../secret.txt",
        "/link/secret.txt",
        "/.hidden",
        "/app/../../secret.txt",
    ],
)
def test_nothing_outside_the_library_is_served(server: app.AppServer, path: str) -> None:
    secret = server.library.root.parent / "secret.txt"
    secret.write_text("private")
    (server.library.root / "link").symlink_to(server.library.root.parent)
    (server.library.root / ".hidden").write_text("hidden")
    status, _, body = request(server, "GET", path)
    assert status == 404 and b"private" not in body


# Security: the browser lets any web page send requests to this server.


def test_an_upload_without_the_token_is_refused(server: app.AppServer, tmp_path: Path) -> None:
    for token in ("", "wrong"):
        status, _ = upload(server, "x.wav", b"data", token=token)
        assert status == 403
    assert list(server.library.songs.iterdir()) == []


def test_another_host_name_is_refused(server: app.AppServer) -> None:
    # DNS rebinding: a site whose name now points to 127.0.0.1 still sends its own Host.
    status, _, _ = request(server, "GET", "/api/songs", host="evil.example:80")
    assert status == 421
    status, _, _ = request(server, "GET", "/api/songs", host=f"evil.example:{server.port}")
    assert status == 421
    status, _, _ = request(
        server, "POST", "/api/songs?name=x.wav", b"data", {app.TOKEN_HEADER: server.token}, host="evil.example"
    )
    assert status == 421


def test_cross_origin_preflights_are_refused(server: app.AppServer) -> None:
    status, headers, _ = request(server, "OPTIONS", "/api/songs", headers={"Origin": "https://evil.example"})
    assert status == 405 and "access-control-allow-origin" not in headers


@pytest.mark.parametrize(
    ("name", "reason"), [("notes.txt", "not an audio"), ("", "not an audio"), ("../../x.wav", None)]
)
def test_upload_names_are_checked(server: app.AppServer, name: str, reason: str | None) -> None:
    status, answer = upload(server, name, b"data")
    if reason:
        assert status == 400 and reason in answer["error"]
    else:  # a path is reduced to its file name, inside the library
        assert status == 202 and (server.library.songs / "x.wav").exists()


def test_a_too_large_upload_is_refused_before_reading(server: app.AppServer, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app, "MAX_UPLOAD", 10)
    status, _ = upload(server, "big.wav", b"x" * 11)
    assert status == 413 and list(server.library.songs.iterdir()) == []


def test_bad_options_are_refused(server: app.AppServer) -> None:
    status, answer = upload(server, "x.wav", b"data", "&bpm=5")
    assert status == 400 and "BPM" in answer["error"]


# Findings of the review of the app, each with the request that showed it.


def raw(srv: app.AppServer, data: bytes, timeout: float = 5) -> bytes:
    """Send bytes as they are and read everything until the server closes the connection."""
    import socket

    with socket.create_connection(("127.0.0.1", srv.port), timeout=timeout) as s:
        s.sendall(data)
        out = b""
        try:
            while chunk := s.recv(65536):
                out += chunk
        except TimeoutError:
            pass
    return out


def test_a_refused_upload_body_is_never_read_as_a_second_request(server: app.AppServer) -> None:
    host = f"127.0.0.1:{server.port}"
    smuggled = f"GET /api/songs HTTP/1.1\r\nHost: {host}\r\n\r\n".encode()
    request_ = (
        f"POST /api/songs?name=x.wav HTTP/1.1\r\nHost: {host}\r\nContent-Length: {len(smuggled)}\r\n\r\n".encode()
    )
    answer = raw(server, request_ + smuggled)
    assert answer.count(b"HTTP/1.1 ") == 1 and answer.startswith(b"HTTP/1.1 403")


def test_two_uploads_of_one_name_at_once_keep_both_files(server: app.AppServer) -> None:
    results: list[int] = []

    def send(content: bytes) -> None:
        results.append(upload(server, "dup.wav", content)[0])

    threads = [threading.Thread(target=send, args=(bytes([i]) * 3_000_000,)) for i in (1, 2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results == [202, 202]
    files = sorted(p for p in server.library.songs.iterdir() if not p.name.startswith("."))
    assert [p.name for p in files] == ["dup (2).wav", "dup.wav"]
    assert {p.read_bytes()[:1] for p in files} == {b"\x01", b"\x02"} and all(
        len(set(p.read_bytes())) == 1 for p in files
    )


def test_a_stalled_upload_times_out_and_leaves_nothing(server: app.AppServer, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app.Handler, "timeout", 1)
    host = f"127.0.0.1:{server.port}"
    head = (
        f"POST /api/songs?name=slow.wav HTTP/1.1\r\nHost: {host}\r\n"
        f"{app.TOKEN_HEADER}: {server.token}\r\nContent-Length: 100\r\n\r\n"
    )
    answer = raw(server, head.encode() + b"abc", timeout=5)
    assert b"400" in answer.split(b"\r\n")[0]
    assert list(server.library.songs.iterdir()) == []  # no part file, no reserved name


@pytest.mark.parametrize(("length", "status"), [("abc", 413), ("-5", 413), ("9" * 40, 413)])
def test_a_bad_content_length_is_refused(server: app.AppServer, length: str, status: int) -> None:
    host = f"127.0.0.1:{server.port}"
    head = (
        f"POST /api/songs?name=x.wav HTTP/1.1\r\nHost: {host}\r\n"
        f"{app.TOKEN_HEADER}: {server.token}\r\nContent-Length: {length}\r\n\r\n"
    )
    assert raw(server, head.encode()).startswith(f"HTTP/1.1 {status}".encode())


def test_chunked_uploads_are_refused(server: app.AppServer) -> None:
    host = f"127.0.0.1:{server.port}"
    head = (
        f"POST /api/songs?name=x.wav HTTP/1.1\r\nHost: {host}\r\n{app.TOKEN_HEADER}: {server.token}\r\n"
        "Transfer-Encoding: chunked\r\n\r\n3\r\nabc\r\n0\r\n\r\n"
    )
    assert raw(server, head.encode()).startswith(b"HTTP/1.1 411")


def test_odd_headers_and_paths_get_answers_not_crashes(server: app.AppServer) -> None:
    host = f"127.0.0.1:{server.port}"
    token = (
        f"POST /api/songs?name=x.wav HTTP/1.1\r\nHost: {host}\r\n{app.TOKEN_HEADER}: \xe9\r\nContent-Length: 1\r\n\r\nx"
    )
    assert raw(server, token.encode("latin-1")).startswith(b"HTTP/1.1 403")
    assert request(server, "GET", "/a%00b")[0] == 404


@pytest.mark.parametrize(
    ("header", "status", "body"),
    [
        ("bytes=-", 200, 1024),
        ("bytes=5-3", 200, 1024),
        ("bytes=" + "9" * 5000 + "-", 200, 1024),
        ("bytes=0-", 206, 1024),
    ],
)
def test_odd_ranges(server: app.AppServer, header: str, status: int, body: int) -> None:
    track = server.library.root / "x.woodshed" / "audio" / "mix.flac"
    track.parent.mkdir(parents=True, exist_ok=True)
    track.write_bytes(bytes(1024))
    got_status, _, got = request(server, "GET", "/x.woodshed/audio/mix.flac", headers={"Range": header})
    assert (got_status, len(got)) == (status, body)


def test_a_page_folder_without_its_slash_redirects(server: app.AppServer) -> None:
    (server.library.root / "x.woodshed").mkdir()
    (server.library.root / "x.woodshed" / "index.html").write_text("page")
    status, headers, _ = request(server, "GET", "/x.woodshed")
    assert status == 301 and headers["location"] == "/x.woodshed/"


def test_a_failed_upload_does_not_keep_its_name(server: app.AppServer, tmp_path: Path) -> None:
    upload(server, "song.wav", b"not audio")
    wait_done(server)
    assert list(server.library.songs.iterdir()) == []


def test_the_worker_survives_an_unexpected_error(
    server: app.AppServer, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = []
    from woodshed.run import first_pass as real

    def flaky(*args: Any, **kwargs: Any) -> Any:
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("a bug")
        return real(*args, **kwargs)

    monkeypatch.setattr("woodshed.app.first_pass", flaky)
    wav = synth.write("pop", tmp_path / "src").wav
    upload(server, "a.wav", wav.read_bytes())
    upload(server, "b.wav", wav.read_bytes())
    jobs = {j["name"]: j["status"] for j in wait_done(server)["jobs"]}
    assert jobs["a.wav"] == "failed" and len(calls) == 2  # the second song was still processed


def test_no_space_left_is_said_before_reading(server: app.AppServer, monkeypatch: pytest.MonkeyPatch) -> None:
    import shutil
    from collections import namedtuple

    usage = namedtuple("usage", "total used free")
    monkeypatch.setattr(shutil, "disk_usage", lambda _path: usage(10, 10, 0))
    status, answer = upload(server, "x.wav", b"data")
    assert status == 507 and "disk space" in answer["error"]


def test_the_network_needs_an_explicit_choice(capsys: pytest.CaptureFixture[str]) -> None:
    from woodshed import cli

    with pytest.raises(SystemExit) as exc:
        cli.main(["app", "--host", "0.0.0.0"])
    assert exc.value.code == 2 and "--allow-network" in capsys.readouterr().err


def test_a_symlinked_page_folder_is_not_listed(server: app.AppServer, tmp_path: Path) -> None:
    outside = tmp_path / "elsewhere.woodshed"
    outside.mkdir()
    (outside / "woodshed.json").write_text(json.dumps({"summary": {"title": "x", "folder": "x"}, "complete": True}))
    (server.library.root / "linked.woodshed").symlink_to(outside)
    assert json.loads(request(server, "GET", "/api/songs")[2])["songs"] == []


# Resume: a stop during a job must not leave a song half done for ever.


def song_file(srv: app.AppServer, tmp_path: Path, name: str = "pop", as_name: str = "pop.wav") -> Path:
    target = srv.library.songs / as_name
    target.write_bytes(synth.write(name, tmp_path / "src").wav.read_bytes())
    return target


def test_a_song_left_without_a_page_is_resumed(server: app.AppServer, tmp_path: Path) -> None:
    song_file(server, tmp_path)
    [job] = server.library.resume()
    assert job.name == "pop.wav"
    state = wait_done(server)
    assert state["jobs"][0]["status"] == "done" and [s["folder"] for s in state["songs"]] == ["pop.woodshed"]
    assert state["songs"][0]["complete"]


def test_a_page_waiting_for_its_stems_is_resumed_with_its_upload_options(server: app.AppServer, tmp_path: Path) -> None:
    src = song_file(server, tmp_path, "waltz", "waltz.wav")
    first_pass(src, server.library.options(3, True, 90), Reporter(), server.library.root)
    manifest = server.library.root / "waltz.woodshed" / "woodshed.json"
    data = json.loads(manifest.read_text())
    manifest.write_text(json.dumps({**data, "complete": False}))  # as a stop before the stems leaves it
    assert len(server.library.resume()) == 1
    assert wait_done(server)["jobs"][0]["status"] == "done"
    data = json.loads(manifest.read_text())
    assert data["complete"] is True
    assert (data["settings"]["beats_per_bar"], data["settings"]["sevenths"], data["settings"]["bpm"]) == (3, True, 90)


def test_finished_pages_are_not_resumed(server: app.AppServer, tmp_path: Path) -> None:
    src = song_file(server, tmp_path)
    first_pass(src, server.library.options(), Reporter(), server.library.root)
    (server.library.songs / "notes.txt").write_text("not a song")
    (server.library.songs / ".pop.wav.1234.part").write_bytes(b"cut short")
    assert server.library.resume() == []


@pytest.mark.parametrize(
    ("settings", "beats"),
    [
        ({"beats_per_bar": "x"}, 4),
        ({"beats_per_bar": True}, 4),
        ({"beats_per_bar": 3, "bpm": 5000}, 3),  # each field on its own
        ({"beats_per_bar": 3, "bpm": 10**400}, 3),  # too big for a float
        ({"beats_per_bar": 3, "bpm": "NaN"}, 3),
        ("nonsense", 4),
    ],
)
def test_a_page_edited_by_hand_resumes_with_its_good_fields(
    server: app.AppServer, tmp_path: Path, settings: Any, beats: int
) -> None:
    song_file(server, tmp_path)
    page = server.library.root / "pop.woodshed"
    page.mkdir()
    (page / "woodshed.json").write_text(json.dumps({"settings": settings, "complete": False}))
    assert len(server.library.resume()) == 1
    assert wait_done(server)["jobs"][0]["status"] == "done"
    data = json.loads((page / "woodshed.json").read_text())
    assert data["settings"]["beats_per_bar"] == beats and data["settings"]["bpm"] is None


def test_a_manifest_that_cannot_be_read_does_not_stop_the_start(server: app.AppServer, tmp_path: Path) -> None:
    song_file(server, tmp_path)
    song_file(server, tmp_path, as_name="other.wav")
    page = server.library.root / "other.woodshed"
    page.mkdir()
    (page / "woodshed.json").write_text("[" * 100_000 + "]" * 100_000)  # too deep for the parser
    jobs = server.library.resume()
    assert sorted(j.name for j in jobs) == ["other.wav", "pop.wav"]


def test_a_resumed_song_that_fails_keeps_its_file(server: app.AppServer) -> None:
    broken = server.library.songs / "broken.wav"
    broken.write_bytes(b"not audio at all")
    server.library.resume()
    assert wait_done(server)["jobs"][0]["status"] == "failed"
    assert broken.exists()  # the user's own file: only a failed upload is removed


def stems_library(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> app.AppServer:
    install_full_length_demucs(monkeypatch)
    srv = app.AppServer(app.Library(tmp_path / "library", Options(open_page=False)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def test_a_mix_only_page_gets_its_stems_when_resumed(
    tmp_path: Path, cache: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    srv = stems_library(tmp_path, monkeypatch)
    try:
        src = song_file(srv, tmp_path, "waltz", "waltz.wav")
        done = first_pass(src, srv.library.options(3), Reporter(), srv.library.root)
        assert done.stems_to_come  # the app stopped here: a mix-only page
        assert len(srv.library.resume()) == 1
        assert wait_done(srv)["jobs"][0]["status"] == "done"
        data = json.loads((done.page / "woodshed.json").read_text())
        assert data["complete"] is True and data["settings"]["stems"] is True and data["summary"]["stems"] is True
        assert data["settings"]["beats_per_bar"] == 3
    finally:
        srv.shutdown()
        srv.server_close()


def test_a_song_whose_separation_failed_is_not_tried_at_every_start(
    tmp_path: Path, cache: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    srv = stems_library(tmp_path, monkeypatch)

    def broken(*args: Any, **kwargs: Any) -> Any:
        raise WoodshedError("no model in the cache")

    monkeypatch.setattr("woodshed.stems.separate", broken)
    try:
        upload(srv, "pop.wav", synth.write("pop", tmp_path / "src").wav.read_bytes())
        assert wait_done(srv)["jobs"][0]["status"] == "failed"
        assert (srv.library.songs / "pop.wav").exists()  # its mix-only page is kept, and its file
        again = app.Library(srv.library.root, srv.library.opts)  # the next start
        [job] = again.resume()
        assert job.status == "failed" and "no model in the cache" in job.message and again.queue.empty()
        assert f"remove {Path('songs', 'pop.wav')} and add it again" in job.message  # songs\pop.wav on Windows
    finally:
        srv.shutdown()
        srv.server_close()


def test_a_song_that_killed_the_app_is_not_tried_again(server: app.AppServer, tmp_path: Path) -> None:
    src = song_file(server, tmp_path)
    app.Library.attempt(src).write_text("")  # the process died during it: no error written
    [job] = server.library.resume()
    assert job.status == "failed" and "stopped during it" in job.message and server.library.queue.empty()


def test_a_song_stopped_by_the_user_is_resumed(
    server: app.AppServer, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    started, stopped = threading.Event(), threading.Event()

    def decode_killed_by_ctrl_c(*args: Any, **kwargs: Any) -> Any:
        started.set()
        stopped.wait(10)
        raise WoodshedError("ffmpeg: interrupted")  # Ctrl-C reaches ffmpeg too

    monkeypatch.setattr("woodshed.app.first_pass", decode_killed_by_ctrl_c)
    upload(server, "new.wav", b"fresh upload")
    upload(server, "next.wav", b"waiting in the queue")
    assert started.wait(10)
    server.library.interrupted()  # Ctrl-C or docker stop during it
    stopped.set()
    deadline = time.monotonic() + 10
    while server.library.running is not None and time.monotonic() < deadline:
        time.sleep(0.05)
    songs = server.library.songs
    assert (songs / "new.wav").exists() and (songs / "next.wav").exists()  # nothing deleted
    assert not any(p.name.endswith(".attempt") for p in songs.iterdir())  # no failure recorded
    monkeypatch.undo()
    again = app.Library(server.library.root, Options(use_stems=False, open_page=False))
    assert [j.name for j in again.resume()] == ["new.wav", "next.wav"]


def test_a_failed_song_finished_by_hand_is_not_reported(server: app.AppServer, tmp_path: Path) -> None:
    src = song_file(server, tmp_path)
    app.Library.attempt(src).write_text("no model in the cache")
    first_pass(src, server.library.options(), Reporter(), server.library.root)  # e.g. the command line
    assert server.library.resume() == []


def test_two_files_of_one_name_copied_in_by_hand_make_one_page(server: app.AppServer, tmp_path: Path) -> None:
    song_file(server, tmp_path)
    song_file(server, tmp_path, as_name="POP.flac")
    jobs = server.library.resume()
    failed = [j for j in jobs if j.status == "failed"]  # the other one may already be running
    assert len(jobs) == 2 and len(failed) == 1 and "another file" in failed[0].message


def test_a_symlinked_page_folder_is_not_written_through(server: app.AppServer, tmp_path: Path) -> None:
    song_file(server, tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (server.library.root / "pop.woodshed").symlink_to(elsewhere)
    assert server.library.resume() == []


def test_song_options_keep_the_library_settings(tmp_path: Path) -> None:
    library = app.Library(tmp_path / "library", Options(use_stems=False, offline=True, out=tmp_path, title="x"))
    opts = library.options(3, True, 100)
    assert (opts.use_stems, opts.offline, opts.out, opts.title, opts.open_page) == (False, True, None, None, False)
    assert (opts.beats_per_bar, opts.sevenths, opts.bpm) == (3, True, 100)


def test_the_app_resumes_at_start_and_stops_cleanly(
    tmp_path: Path, cache: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "library"
    (root / "songs").mkdir(parents=True)
    (root / "songs" / "pop.wav").write_bytes(synth.write("pop", tmp_path / "src").wav.read_bytes())
    handlers: list[int] = []
    monkeypatch.setattr("woodshed.app.signal.signal", lambda signum, handler: handlers.append(signum))
    seen: list[app.Library] = []

    def stop_at_once(self: app.AppServer) -> None:
        seen.append(self.library)
        raise KeyboardInterrupt

    monkeypatch.setattr(app.AppServer, "serve_forever", stop_at_once)
    with pytest.raises(KeyboardInterrupt):
        app.serve(root, Options(use_stems=False, open_page=False), port=0, open_browser=False)
    assert handlers == [signal.SIGTERM, signal.SIGTERM]  # set, then put back
    assert [j.name for j in seen[0].jobs.values()] == ["pop.wav"]


def test_a_taken_port_still_puts_the_stop_signal_back(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    handlers: list[int] = []
    monkeypatch.setattr("woodshed.app.signal.signal", lambda signum, handler: handlers.append(signum))
    busy = app.AppServer(app.Library(tmp_path / "other", Options(use_stems=False, open_page=False)))
    try:
        with pytest.raises(OSError):
            app.serve(
                tmp_path / "library", Options(use_stems=False, open_page=False), port=busy.port, open_browser=False
            )
    finally:
        busy.server_close()
    assert handlers == [signal.SIGTERM, signal.SIGTERM]


def test_in_docker_a_library_the_container_cannot_write_says_what_to_do(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from woodshed import cli

    def refused(*args: Any, **kwargs: Any) -> None:
        raise PermissionError(13, "Permission denied", "/library/songs")

    monkeypatch.setattr("woodshed.app.serve", refused)
    monkeypatch.setenv("WOODSHED_CONTAINER", "1")
    assert cli.main(["app", "/library", "--no-open"]) != 0
    err = capsys.readouterr().err
    assert "Permission denied" in err and "mkdir" in err and "chown" in err


def test_started_again_while_it_runs_it_shows_the_running_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    opened: list[str] = []
    monkeypatch.setattr("webbrowser.open", opened.append)
    running = app.AppServer(app.Library(tmp_path / "library", Options(use_stems=False, open_page=False)))
    threading.Thread(target=running.serve_forever, daemon=True).start()
    work = running.library.songs / ".song.mp3.1a2b3c4d.part"
    work.write_bytes(b"x")  # a song the running app is receiving
    store = running.library.root / app.CORRECTIONS_DIR / "One.woodshed.json"
    store.parent.mkdir()
    kept = json.dumps({"rev": 1, "by_key": {}, "band": {"note": "out of the set"}})
    store.write_text(kept, encoding="utf-8")  # the running app's to clear, under its own lock
    try:
        app.serve(tmp_path / "library", Options(use_stems=False, open_page=False), port=running.port)
    finally:
        running.shutdown()
        running.server_close()
    assert opened == [f"http://127.0.0.1:{running.port}/"]
    assert "already running" in capsys.readouterr().out
    assert work.exists()  # its work in progress is left alone
    assert store.read_text(encoding="utf-8") == kept  # and its band choices


def test_a_start_clears_the_notes_left_out_of_the_set(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app.AppServer, "serve_forever", lambda self: None)  # started, then stopped at once
    store = tmp_path / "library" / app.CORRECTIONS_DIR / "One.woodshed.json"
    store.parent.mkdir(parents=True)
    store.write_text(json.dumps({"rev": 1, "by_key": {}, "band": {"note": "out of the set"}}), encoding="utf-8")
    app.serve(tmp_path / "library", Options(use_stems=False, open_page=False), port=0, open_browser=False)
    assert "band" not in json.loads(store.read_text(encoding="utf-8"))


def test_another_service_on_the_port_is_not_taken_for_woodshed(tmp_path: Path) -> None:
    import http.server

    other = http.server.ThreadingHTTPServer(("127.0.0.1", 0), http.server.SimpleHTTPRequestHandler)
    threading.Thread(target=other.serve_forever, daemon=True).start()
    try:
        assert not app.running_here(other.server_address[1])
        with pytest.raises(OSError):
            app.serve(
                tmp_path / "library",
                Options(use_stems=False, open_page=False),
                port=other.server_address[1],
                open_browser=False,
            )
    finally:
        other.shutdown()
        other.server_close()


def test_a_proxy_in_the_environment_does_not_hide_the_running_app(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9")  # nothing there: a proxied request would fail
    monkeypatch.setenv("NO_PROXY", "")
    running = app.AppServer(app.Library(tmp_path / "library", Options(use_stems=False, open_page=False)))
    threading.Thread(target=running.serve_forever, daemon=True).start()
    try:
        assert app.running_here(running.port)
    finally:
        running.shutdown()
        running.server_close()
