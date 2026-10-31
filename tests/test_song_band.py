"""The band's own words on a song (spec 031): its notes, on several lines, and its own title and artist, kept with
the corrections, shown on every device, never renaming the page folder."""

from __future__ import annotations

import json
from typing import Any

import pytest

from tests.test_app import request
from tests.test_band import post, server  # noqa: F401  (the fixture)
from woodshed import app


def band(srv: app.AppServer, page: str = "One.woodshed") -> dict[str, Any]:
    got: dict[str, Any] = srv.library.corrections(page, "a1")["band"]
    return got


def test_a_note_keeps_its_lines(server: app.AppServer) -> None:  # noqa: F811
    note = "Start:  drums count 4,   then guitar\n\n  End: stop on the 1  \r\nwatch the singer"
    status, saved = post(server, "/api/band", {"page": "One.woodshed", "note": note})
    assert status == 200
    assert saved["band"]["note"] == "Start: drums count 4, then guitar\nEnd: stop on the 1\nwatch the singer"


@pytest.mark.parametrize(
    ("note", "ok"),
    [("x" * 1000, True), ("x" * 1001, False), ("\n".join(["l"] * 12), True), ("\n".join(["l"] * 13), False)],
)
def test_a_note_holds_a_thousand_characters_on_twelve_lines(server: app.AppServer, note: str, ok: bool) -> None:  # noqa: F811
    status, _ = post(server, "/api/band", {"page": "One.woodshed", "note": note})
    assert status == (200 if ok else 400)


def test_the_band_names_a_song_its_own_way(server: app.AppServer) -> None:  # noqa: F811
    status, saved = post(
        server,
        "/api/band",
        {"page": "Two.woodshed", "artist": "  Presidents of the USA ", "title": "Video Killed the Radio Star"},
    )
    assert status == 200 and saved["band"] == {
        "artist": "Presidents of the USA",
        "title": "Video Killed the Radio Star",
    }
    rows = {r["folder"]: r for r in json.loads(request(server, "GET", "/api/songs")[2])["songs"]}
    assert rows["Two.woodshed"]["band"]["title"] == "Video Killed the Radio Star"  # every library sees it
    assert (server.library.root / "Two.woodshed").is_dir()  # the folder keeps its name: it keys the rest
    _, saved = post(server, "/api/band", {"page": "Two.woodshed", "artist": "", "title": None})
    assert "artist" not in saved["band"] and "title" not in saved["band"]  # back to the recording's


@pytest.mark.parametrize("data", [{"title": "x" * 121}, {"artist": "bad‮name"}, {"title": 3}])
def test_a_bad_title_or_artist_is_refused(server: app.AppServer, data: dict[str, Any]) -> None:  # noqa: F811
    status, answer = post(server, "/api/band", {"page": "One.woodshed", **data})
    assert status == 400 and answer["error"]
    assert band(server) == {}
