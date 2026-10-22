"""The band's typed chords and part names, kept by the library and shared like the picks."""

from __future__ import annotations

import json
import math
from typing import Any

import pytest

from tests.test_app import request
from tests.test_band import post, server  # noqa: F401  (the fixture)
from woodshed import app, build

KEY = "b1e2a3"


def edits(**fields: Any) -> dict[str, Any]:
    return {"page": "One.woodshed", "key": KEY, **fields}


def read(srv: app.AppServer, key: str = KEY) -> dict[str, Any]:
    body = request(srv, "GET", f"/api/corrections?page=One.woodshed&key=a1b2c3&edits={key}")[2]
    answer: dict[str, Any] = json.loads(body)
    return answer


def test_typed_bars_are_kept_and_merged_bar_by_bar(server: app.AppServer) -> None:  # noqa: F811
    status, answer = post(server, "/api/edits", edits(bars={"4": {"chords": [[2, "D/F#"], [2, "G"]], "t": 1.5}}))
    assert status == 200 and answer["bars"] == {"4": {"chords": [[2, "D/F#"], [2, "G"]], "t": 1.5}}
    post(server, "/api/edits", edits(bars={"8": {"chords": [[4, "Asus4"]], "t": 3.0}}))  # another device, another bar
    got = read(server)["edits"]
    assert set(got["bars"]) == {"4", "8"} and got["parts"] == {} and got["removed_bars"] == {}
    _, answer = post(server, "/api/edits", edits(bars={"4": {"chords": [[4, "Em7"]], "t": 1.5}}))  # a later one wins
    assert answer["bars"]["4"]["chords"] == [[4, "Em7"]]


def test_a_bar_taken_back_is_remembered_with_what_it_took_back(server: app.AppServer) -> None:  # noqa: F811
    post(server, "/api/edits", edits(bars={"4": {"chords": [[4, "G"]], "t": 1.5}}))
    _, answer = post(server, "/api/edits", edits(bars={"4": None}))
    assert answer["bars"] == {} and answer["removed_bars"] == {"4": {"chords": [[4, "G"]], "t": 1.5}}
    _, answer = post(server, "/api/edits", edits(bars={"4": None}))  # said twice: the first removal is kept
    assert answer["removed_bars"]["4"]["chords"] == [[4, "G"]]


def test_part_names_and_joins_are_kept_part_by_part(server: app.AppServer) -> None:  # noqa: F811
    post(server, "/api/edits", edits(parts={"0": {"name": "Intro riff"}}))
    _, answer = post(server, "/api/edits", edits(parts={"16": {"join": True}, "24": {"name": "Tag‮"}}))
    assert answer["parts"] == {"0": {"name": "Intro riff"}, "16": {"join": True}, "24": {"name": "Tag"}}
    _, answer = post(server, "/api/edits", edits(parts={"0": None}))
    assert "0" not in answer["parts"] and answer["removed_parts"] == {"0": {"name": "Intro riff"}}


@pytest.mark.parametrize(
    "bad",
    [
        {"bars": {"4": {"chords": [[4, "Hxyz"]], "t": 1}}},  # not a chord
        {"bars": {"4": {"chords": [[0, "G"]], "t": 1}}},  # no beats
        {"bars": {"x": {"chords": [[4, "G"]], "t": 1}}},  # not a beat
        {"bars": {"4": {"chords": [[4, "G" * 30]], "t": 1}}},  # too long
        {"parts": {"0": {"name": "x" * 41}}},
        {"parts": {"0": {"name": "‮\u0007 "}}},  # nothing left once cleaned
        {"parts": {"0": {"colour": "red"}}},
        {"key": "no spaces allowed"},
    ],
)
def test_what_a_page_cannot_have_typed_is_refused(server: app.AppServer, bad: dict[str, Any]) -> None:  # noqa: F811
    status, _ = post(server, "/api/edits", edits(**bad))
    assert status == 400


def test_edits_need_the_token_and_push_a_revision(server: app.AppServer) -> None:  # noqa: F811
    status, _ = post(server, "/api/edits", edits(bars={"4": {"chords": [[4, "G"]], "t": 1}}), token="wrong")
    assert status == 403
    before = server.live.fixes.get("One.woodshed", 0)
    post(server, "/api/edits", edits(bars={"4": {"chords": [[4, "G"]], "t": 1}}))
    assert server.live.fixes["One.woodshed"] > before  # every open device reads the chart again


def test_the_picks_and_edits_live_side_by_side(server: app.AppServer) -> None:  # noqa: F811
    post(server, "/api/corrections", {"page": "One.woodshed", "key": "a1b2c3", "fixes": {"3": [9, "m"]}})
    post(server, "/api/edits", edits(bars={"4": {"chords": [[4, "G"]], "t": 1}}))
    got = read(server)
    assert got["fixes"] == {"3": [9, "m"]} and got["edits"]["bars"]["4"]["chords"] == [[4, "G"]]
    assert "edits" not in json.loads(request(server, "GET", "/api/corrections?page=One.woodshed&key=a1b2c3")[2])


def test_a_typed_bar_settles_the_doubts_it_covers_in_the_count(server: app.AppServer) -> None:  # noqa: F811
    def chord(doubt_id: int | None, beats: int = 4) -> dict[str, Any]:
        doubt = None if doubt_id is None else {"id": doubt_id, "why": "", "alternatives": [], "kind": "chord"}
        return {"pc": 0, "quality": "", "beats": beats, "doubt": doubt}

    beats = [0.5 * i for i in range(20)]
    song = {
        "bars": [{"chords": [chord(None)]}, {"chords": [chord(0, 2), chord(1, 2)]}, {"chords": [chord(2)]}],
        "beats": beats,
        "first_beat": 2,
        "beats_per_bar": 4,
    }
    page = server.library.root / "One.woodshed"
    (page / "index.html").write_text(
        f'<script type="application/json" id="woodshed-data">{build.script_json({"song": song, "view": {}})}</script>'
    )

    def count() -> int:
        left: int = {s["folder"]: s["doubts"] for s in server.library.pages()}["One.woodshed"]
        return left

    assert count() == 3
    key = app.beats_key(song)
    post(server, "/api/edits", {"page": "One.woodshed", "key": key, "bars": {"6": {"chords": [[2, "G"]], "t": 3}}})
    assert count() == 2  # bar 1 starts on beat 2 + 4: its first two beats typed, doubt 0 settled
    post(server, "/api/edits", {"page": "One.woodshed", "key": key, "bars": {"9": {"chords": [[2, "E"]], "t": 4.5}}})
    assert count() == 0  # one beat of doubt 1 and one of doubt 2: both settled
    post(server, "/api/edits", {"page": "One.woodshed", "key": "other", "bars": {"10": {"chords": [[4, "A"]], "t": 5}}})
    assert count() == 0  # edits of another beat grid do not count here


def test_the_beats_key_is_the_one_the_page_computes() -> None:
    song = {"beats": [0.1, 0.6005, 1.1004999, 2.0]}  # whole milliseconds, as Math.floor(t * 1000 + 0.5)
    text = json.dumps([math.floor(t * 1000 + 0.5) for t in song["beats"]], separators=(",", ":"))
    h = 0x811C9DC5
    for ch in text:
        h = ((h ^ ord(ch)) * 0x01000193) & 0xFFFFFFFF
    assert app.beats_key(song) == format(h, "x")
