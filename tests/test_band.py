"""The band in the room: one device leads, the others follow its song and position; the set list."""

from __future__ import annotations

import http.client
import json
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from tests.test_app import request
from woodshed import app
from woodshed.run import Options

LEADER = "leader-device-1"
OTHER = "other-device-22"


@pytest.fixture
def server(tmp_path: Path) -> Iterator[app.AppServer]:
    library = app.Library(tmp_path / "library", Options(use_stems=False, open_page=False))
    for name in ("One.woodshed", "Two.woodshed", "Three.woodshed"):
        page = library.root / name
        page.mkdir()
        (page / "index.html").write_text("<!doctype html>")
        summary = {"title": name.split(".")[0], "folder": name, "key": "C", "bpm": 100, "meter": "4/4",
                   "duration": 60, "doubts": 0, "stems": False}  # fmt: skip
        (page / "woodshed.json").write_text(json.dumps({"settings": {}, "summary": summary, "complete": True}))
    srv = app.AppServer(library)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()
    srv.server_close()


def post(srv: app.AppServer, path: str, data: Any, token: str | None = None) -> tuple[int, Any]:
    body = json.dumps(data).encode()
    headers = {app.TOKEN_HEADER: srv.token if token is None else token, "Content-Type": "application/json"}
    status, _, answer = request(srv, "POST", path, body, headers)
    return status, json.loads(answer)


def live(who: str = LEADER, **fields: Any) -> dict[str, Any]:
    return {"id": who, "song": "One.woodshed", "playing": True, "time": 12.5, "rate": 1.0, "loop": None, **fields}


class Stream:
    """A follower: reads the server-sent events of /api/live."""

    def __init__(self, srv: app.AppServer) -> None:
        self.conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=10)
        self.conn.request("GET", f"/api/live?t={srv.token}", headers={"Host": f"127.0.0.1:{srv.port}"})
        self.response = self.conn.getresponse()

    def next(self) -> dict[str, Any] | str:
        """The next event's data, or "ping" for a keep-alive comment."""
        lines = []
        while True:
            line = self.response.readline().decode()
            if line in ("\n", ""):
                break
            lines.append(line.rstrip("\n"))
        if lines and lines[0].startswith(":"):
            return "ping"
        data: dict[str, Any] = json.loads(lines[0].removeprefix("data: "))
        return data

    def close(self) -> None:
        self.response.close()  # the response holds the socket: closing only the connection keeps it open
        self.conn.close()


def test_a_song_page_gets_the_token_from_its_own_server(server: app.AppServer) -> None:
    status, headers, body = request(server, "GET", "/api/token")
    assert status == 200 and json.loads(body) == {"token": server.token}
    assert "access-control-allow-origin" not in headers  # another site's page cannot read it
    status, _, _ = request(server, "GET", "/api/token", host="evil.example:80")
    assert status == 421


def test_the_leader_moves_and_followers_hear_it(server: app.AppServer) -> None:
    follower = Stream(server)
    try:
        assert follower.response.getheader("Content-Type", "").startswith("text/event-stream")
        assert follower.next() == {"leader": None, "now": pytest.approx(time.time(), abs=5)}
        status, state = post(server, "/api/live", live(lead=True))
        assert status == 200 and state["leader"] == LEADER and state["song"] == "One.woodshed"
        event = follower.next()
        assert isinstance(event, dict)
        assert (event["leader"], event["time"], event["playing"]) == (LEADER, 12.5, True)
        assert event["at"] <= event["now"]  # the follower adds the time since `at`
        post(server, "/api/live", live(time=40.0, playing=False, loop=[4, 7]))
        event = follower.next()
        assert isinstance(event, dict) and (event["time"], event["playing"], event["loop"]) == (40.0, False, [4, 7])
    finally:
        follower.close()


def test_only_the_leader_moves_the_band_until_another_device_takes_the_lead(server: app.AppServer) -> None:
    post(server, "/api/live", live(lead=True))
    status, answer = post(server, "/api/live", live(OTHER, time=99.0))
    assert status == 409 and "another device" in answer["error"]
    status, state = post(server, "/api/live", live(OTHER, lead=True, time=99.0))
    assert status == 200 and state["leader"] == OTHER
    status, _ = post(server, "/api/live", live(time=1.0))  # the old leader now follows
    assert status == 409
    status, state = post(server, "/api/live", {"id": OTHER, "release": True})
    assert status == 200 and state == {"leader": None}


@pytest.mark.parametrize(
    "fields",
    [
        {"song": "../secret.woodshed"},
        {"song": "Missing.woodshed"},
        {"song": ".hidden.woodshed"},
        {"time": "12"},
        {"time": -1},
        {"time": True},
        {"rate": 5},
        {"loop": [1]},
        {"loop": [1, "2"]},
        {"id": "x"},
    ],
)
def test_live_updates_are_checked(server: app.AppServer, fields: dict[str, Any]) -> None:
    status, answer = post(server, "/api/live", live(lead=True, **fields))
    assert status == 400 and answer["error"]


def test_a_live_update_needs_the_token_and_a_small_body(server: app.AppServer, monkeypatch: pytest.MonkeyPatch) -> None:
    assert post(server, "/api/live", live(lead=True), token="wrong")[0] == 403
    monkeypatch.setattr(app, "LIVE_MAX", 10)
    assert post(server, "/api/live", live(lead=True))[0] == 413
    status, _, _ = request(server, "POST", "/api/live", b"{not json", {app.TOKEN_HEADER: server.token})
    assert status == 400


def test_a_quiet_stream_stays_open_with_pings(server: app.AppServer, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app, "LIVE_PING", 0.2)
    follower = Stream(server)
    try:
        follower.next()  # the state at once
        assert follower.next() == "ping"
    finally:
        follower.close()


def test_a_band_not_an_audience(server: app.AppServer, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app, "LIVE_FOLLOWERS", 1)
    first = Stream(server)
    try:
        first.next()
        status, _, _ = request(server, "GET", f"/api/live?t={server.token}")
        assert status == 503
    finally:
        first.close()


def test_closing_the_app_ends_the_streams(server: app.AppServer) -> None:
    follower = Stream(server)
    follower.next()
    server.live.close()
    started = time.monotonic()
    while follower.response.readline():
        assert time.monotonic() - started < 5
    follower.close()


@pytest.mark.parametrize(
    ("host", "ok"),
    [
        ("192.168.1.20:{port}", True),
        ("[fe80::1]:{port}", True),
        ("192.168.1.20:8090", True),  # Docker publishes the app on another port
        ("band.local:{port}", False),  # a name: DNS rebinding stays refused
    ],
)
def test_on_the_network_phones_use_the_computer_address(server: app.AppServer, host: str, ok: bool) -> None:
    server.network = True  # as with --host 0.0.0.0 --allow-network
    status, _, _ = request(server, "GET", "/api/songs", host=host.format(port=server.port))
    assert (status == 200) is ok


def test_this_computer_on_another_port_is_accepted(server: app.AppServer) -> None:
    # docker run -p 8090:8000: the browser says localhost:8090, the app listens on 8000.
    for host in ("localhost:8090", "127.0.0.1:8090", "[::1]:8090"):
        assert request(server, "GET", "/api/songs", host=host)[0] == 200


def test_in_a_container_the_phones_are_told_what_to_type(
    server: app.AppServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    server.network = True
    monkeypatch.setenv("WOODSHED_CONTAINER", "1")  # the container's own address means nothing to a phone
    server._addresses = None
    state = json.loads(request(server, "GET", "/api/songs")[2])
    assert state["addresses"] == [] and state["container"] is True
    monkeypatch.setenv("WOODSHED_PUBLIC_URL", "http://192.168.1.20:8000/, http://studio.local:8000")
    server._addresses = None
    state = json.loads(request(server, "GET", "/api/songs")[2])
    assert state["addresses"] == ["http://192.168.1.20:8000/", "http://studio.local:8000/"]


def test_only_loopback_names_without_the_network(server: app.AppServer) -> None:
    status, _, _ = request(server, "GET", "/api/songs", host=f"192.168.1.20:{server.port}")
    assert status == 421


def test_the_home_lists_the_addresses_for_the_phones_only_on_the_network(server: app.AppServer) -> None:
    assert json.loads(request(server, "GET", "/api/songs")[2])["addresses"] == []
    server.network = True
    addresses = json.loads(request(server, "GET", "/api/songs")[2])["addresses"]
    assert all(a.startswith("http://") and a.endswith(f":{server.port}/") for a in addresses)
    assert all("127.0.0.1" not in a for a in addresses)


def test_the_set_list_keeps_its_order_and_forgets_removed_pages(server: app.AppServer) -> None:
    assert json.loads(request(server, "GET", "/api/setlist")[2]) == {"songs": []}
    status, answer = post(server, "/api/setlist", {"songs": ["Two.woodshed", "One.woodshed"]})
    assert status == 200 and answer == {"songs": ["Two.woodshed", "One.woodshed"]}
    (server.library.root / "Two.woodshed" / "woodshed.json").unlink()  # the page is gone
    assert json.loads(request(server, "GET", "/api/setlist")[2]) == {"songs": ["One.woodshed"]}


@pytest.mark.parametrize(
    "data",
    [{"songs": ["Nope.woodshed"]}, {"songs": ["One.woodshed", "One.woodshed"]}, {"songs": "One.woodshed"}, [], {}],
)
def test_the_set_list_takes_only_pages_of_the_library(server: app.AppServer, data: Any) -> None:
    status, answer = post(server, "/api/setlist", data)
    assert status == 400 and answer["error"]
    assert not (server.library.root / app.SETLIST).exists()


def test_the_stream_needs_the_token_and_a_page_of_this_app(server: app.AppServer) -> None:
    # Another site's page cannot read the stream, but without these checks it could hold the
    # band's stream slots open.
    assert request(server, "GET", "/api/live")[0] == 403
    assert request(server, "GET", "/api/live?t=wrong")[0] == 403
    cross = {"Sec-Fetch-Site": "cross-site"}
    assert request(server, "GET", f"/api/live?t={server.token}", headers=cross)[0] == 403


def test_a_device_that_leaves_frees_its_place(server: app.AppServer, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app, "LIVE_FOLLOWERS", 1)
    monkeypatch.setattr(app, "LIVE_PING", 0.1)
    first = Stream(server)
    first.next()
    first.close()  # the phone went to sleep, or its page closed
    deadline = time.monotonic() + 5
    while server.live.followers and time.monotonic() < deadline:
        time.sleep(0.05)
    second = Stream(server)
    try:
        assert second.response.status == 200
    finally:
        second.close()


def test_a_stalled_device_does_not_hold_up_the_others(server: app.AppServer) -> None:
    stalled = Stream(server)  # opened, never read
    reader = Stream(server)
    try:
        reader.next()
        post(server, "/api/live", live(lead=True, time=33.0))
        event = reader.next()
        assert isinstance(event, dict) and event["time"] == 33.0
    finally:
        stalled.close()
        reader.close()


def test_on_the_network_songs_are_added_from_this_computer_only(
    server: app.AppServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(app.Handler, "_from_this_computer", lambda self: False)  # a phone
    headers = {app.TOKEN_HEADER: server.token, "Content-Type": "application/octet-stream"}
    status, _, body = request(server, "POST", "/api/songs?name=x.wav", b"data", headers)
    assert status == 403 and b"computer that runs the app" in body
    assert json.loads(request(server, "GET", "/api/songs")[2])["can_upload"] is False  # the page hides the upload
    assert post(server, "/api/live", live(lead=True))[0] == 200  # leading the band is fine


def test_a_long_set_list_can_be_saved(server: app.AppServer) -> None:
    names = []
    for k in range(90):
        name = f"{k:02d} " + "A very long song title from a live recording, take " * 2 + ".woodshed"
        page = server.library.root / name
        page.mkdir()
        (page / "index.html").write_text("x")
        summary = {"title": name, "folder": name, "key": "C", "bpm": 1, "meter": "4/4", "duration": 1, "doubts": 0,
                   "stems": False}  # fmt: skip
        (page / "woodshed.json").write_text(json.dumps({"settings": {}, "summary": summary, "complete": True}))
        names.append(name)
    status, answer = post(server, "/api/setlist", {"songs": names})
    assert status == 200 and answer["songs"] == names


def test_in_a_container_uploads_from_the_network_are_an_explicit_choice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(app.Handler, "_from_this_computer", lambda self: False)  # the Docker bridge
    srv = app.AppServer(
        app.Library(tmp_path / "lib", Options(use_stems=False, open_page=False)), uploads_from_network=True
    )
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        assert json.loads(request(srv, "GET", "/api/songs")[2])["can_upload"] is True
        headers = {app.TOKEN_HEADER: srv.token, "Content-Type": "application/octet-stream"}
        assert request(srv, "POST", "/api/songs?name=x.wav", b"data", headers)[0] == 202
    finally:
        srv.shutdown()
        srv.server_close()


# Corrections: a chord picked by ear on one device is the band's chart.


def fixes(page: str = "One.woodshed", **extra: Any) -> dict[str, Any]:
    return {"page": page, "key": "a1b2c3", "fixes": {"3": [9, "m"], "7": [7, ""]}, **extra}


def test_corrections_are_kept_by_the_library_for_every_device(server: app.AppServer) -> None:
    status, _, body = request(server, "GET", "/api/corrections?page=One.woodshed&key=a1b2c3")
    assert status == 200 and json.loads(body) == {"key": "a1b2c3", "fixes": {}, "rev": 0}
    status, answer = post(server, "/api/corrections", fixes())
    assert status == 200 and answer["fixes"] == {"3": [9, "m"], "7": [7, ""]} and answer["rev"] > 0
    status, _, body = request(server, "GET", "/api/corrections?page=One.woodshed&key=a1b2c3")
    assert json.loads(body) == answer  # another device reads them
    assert not (server.library.root / "One.woodshed" / "corrections.json").exists()  # kept by the library


def test_two_devices_correcting_at_once_keep_both_chords(server: app.AppServer) -> None:
    post(server, "/api/corrections", fixes(fixes={"3": [9, "m"]}))
    _, answer = post(server, "/api/corrections", fixes(fixes={"7": [7, ""]}))  # did not hear of 3 yet
    assert answer["fixes"] == {"3": [9, "m"], "7": [7, ""]}
    _, answer = post(server, "/api/corrections", fixes(fixes={"3": [0, ""]}))  # a later choice wins
    assert answer["fixes"]["3"] == [0, ""]


def test_a_page_of_another_analysis_does_not_hide_the_corrections_of_this_one(server: app.AppServer) -> None:
    post(server, "/api/corrections", fixes())
    post(server, "/api/corrections", fixes(key="old999", fixes={"1": [2, ""]}))  # a tab left open before a rebuild
    _, _, body = request(server, "GET", "/api/corrections?page=One.woodshed&key=a1b2c3")
    assert json.loads(body)["fixes"] == {"3": [9, "m"], "7": [7, ""]}


def test_the_revision_keeps_growing_when_the_app_restarts(server: app.AppServer) -> None:
    _, first = post(server, "/api/corrections", fixes())
    again = app.Library(server.library.root, server.library.opts)  # the app started again
    assert again.set_corrections(fixes(fixes={"9": [4, "m"]}))["rev"] > first["rev"]


def test_the_stream_never_tells_an_older_revision(server: app.AppServer) -> None:
    server.live.corrected("One.woodshed", 6)
    server.live.corrected("One.woodshed", 5)  # two corrections answered in the other order
    assert server.live.fixes["One.woodshed"] == 6


@pytest.mark.parametrize(
    "data",
    [
        fixes(page="Nope.woodshed"),
        fixes(page="../One.woodshed"),
        fixes(fixes={"3": [12, "m"]}),
        fixes(fixes={"3": [9, "maj9"]}),
        fixes(fixes={"3": "Am"}),
        fixes(fixes=[1, 2]),
        fixes(key=7),
        fixes(fixes={str(k): [0, ""] for k in range(5000)}),
    ],
)
def test_corrections_are_checked(server: app.AppServer, data: dict[str, Any]) -> None:
    status, _ = post(server, "/api/corrections", data)
    assert status in (400, 413)
    assert not list((server.library.root / app.CORRECTIONS_DIR).glob("*"))


def test_corrections_need_the_token(server: app.AppServer) -> None:
    status, _ = post(server, "/api/corrections", fixes(), token="wrong")
    assert status == 403
    status, _, _ = request(server, "GET", "/api/corrections?page=../etc&key=a1")
    assert status == 400


def test_followers_hear_that_the_chart_was_corrected(server: app.AppServer) -> None:
    follower = Stream(server)
    try:
        follower.next()
        post(server, "/api/live", live(lead=True))
        first = follower.next()
        assert isinstance(first, dict) and "fixes" not in first  # nothing corrected yet
        _, saved = post(server, "/api/corrections", fixes())
        event = follower.next()
        assert isinstance(event, dict) and event["fixes"] == {"One.woodshed": saved["rev"]}
    finally:
        follower.close()


def test_a_damaged_entry_does_not_lose_the_others(server: app.AppServer) -> None:
    post(server, "/api/corrections", fixes())
    post(server, "/api/corrections", fixes(key="other1", fixes={"1": [2, ""]}))
    store = server.library.root / app.CORRECTIONS_DIR / "One.woodshed.json"
    data = json.loads(store.read_text())
    data["by_key"]["other1"]["fixes"] = {"1": [99, "?"]}  # edited by hand
    store.write_text(json.dumps(data))
    _, _, body = request(server, "GET", "/api/corrections?page=One.woodshed&key=a1b2c3")
    assert json.loads(body)["fixes"] == {"3": [9, "m"], "7": [7, ""]} and json.loads(body)["rev"] == data["rev"]


class FakeRoute:
    """A UDP socket: connect() finds the route out, or there is none."""

    found: str | None = "192.168.1.20"

    def __init__(self, *args: object) -> None: ...
    def __enter__(self) -> FakeRoute:
        return self

    def __exit__(self, *args: object) -> None: ...
    def connect(self, address: object) -> None:
        if self.found is None:
            raise OSError("network is unreachable")

    def getsockname(self) -> tuple[str, int]:
        return (self.found or "", 50000)


def test_the_address_for_the_phones_needs_no_name_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    def slow(name: str) -> tuple[str, list[str], list[str]]:
        raise AssertionError("a name lookup: seconds on a Mac without a DNS answer")

    monkeypatch.setattr("woodshed.app.socket.gethostbyname_ex", slow)
    monkeypatch.setattr("woodshed.app.socket.socket", FakeRoute)
    assert app.lan_addresses() == ["192.168.1.20"]


def test_without_a_route_out_the_name_of_the_computer_gives_its_address(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(FakeRoute, "found", None)
    monkeypatch.setattr("woodshed.app.socket.socket", FakeRoute)
    monkeypatch.setattr("woodshed.app.socket.gethostbyname_ex", lambda name: (name, [], ["127.0.0.1", "10.0.0.7"]))
    assert app.lan_addresses() == ["10.0.0.7"]


def test_the_library_counts_what_is_left_to_check_after_the_band_corrected(server: app.AppServer) -> None:
    from woodshed import build

    def chord(doubt_id: int, kind: str) -> dict[str, Any]:
        doubt = {"id": doubt_id, "why": "", "alternatives": [], "kind": kind}
        return {"pc": 0, "quality": "", "beats": 4, "doubt": doubt}

    song = {"bars": [{"chords": [chord(0, "chord")]}, {"chords": [chord(1, "chord"), chord(2, "timing")]}], "beats": []}
    page = server.library.root / "One.woodshed"
    data = build.script_json({"song": song, "view": {}})
    (page / "index.html").write_text(f'<script type="application/json" id="woodshed-data">{data}</script>')

    def count() -> int:
        left: int = {s["folder"]: s["doubts"] for s in server.library.pages()}["One.woodshed"]
        return left

    assert count() == 2  # a timing doubt is not a chord to check
    assert post(server, "/api/corrections", fixes(key="0ld", fixes={"0": [7, ""]}))[0] == 200
    assert count() == 2  # corrections of another analysis of the page: their ids are not these
    key = app.analysis_key(song)
    assert post(server, "/api/corrections", fixes(key=key, fixes={"1": [7, ""]}))[0] == 200
    assert count() == 1  # as the page says after the band's correction
