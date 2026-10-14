"""woodshed app: the library server, its upload and processing queue, and its security rules."""

from __future__ import annotations

import http.client
import json
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
from woodshed.run import Options


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
            if state["songs"]:
                break
            time.sleep(0.2)
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
    files = sorted(server.library.songs.iterdir())
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
