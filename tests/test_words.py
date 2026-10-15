"""Words pasted on a song page of `woodshed app`: placed in the background, one job at a time."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pytest

from tests.test_band import post, server  # noqa: F401  (the fixture)
from woodshed import app, lyrics

WORDS = "[Verse]\nfirst line of the song\nsecond line of the song\n"


def wait(srv: app.AppServer, job_id: str) -> dict[str, Any]:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        jobs: dict[str, dict[str, Any]] = {j["id"]: j for j in srv.library.state()["jobs"]}
        if jobs[job_id]["status"] in ("done", "failed"):
            return jobs[job_id]
        time.sleep(0.02)
    raise AssertionError("the job did not end")


def fake_placement(monkeypatch: pytest.MonkeyPatch, calls: list[tuple[Path, str]]) -> None:
    def add_to_page(
        page: Path, text: str, offline: bool = False, say: Any = print, progress: Any = None
    ) -> dict[str, Any]:
        calls.append((page, text))
        say(lyrics.LISTENING)
        data = {"version": 1, "text": text, "lines": [{"sung": True}, {"sung": False}]}
        (page / lyrics.LYRICS).write_text(json.dumps(data), encoding="utf-8")
        return data

    monkeypatch.setattr(lyrics, "add_to_page", add_to_page)


def test_pasted_words_are_placed_in_the_background(server: app.AppServer, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    calls: list[tuple[Path, str]] = []
    fake_placement(monkeypatch, calls)
    assert not {s["folder"]: s for s in server.library.pages()}["One.woodshed"]["words"]
    status, job = post(server, "/api/lyrics", {"page": "One.woodshed", "text": WORDS})
    assert status == 202 and job["kind"] == "words" and job["page"] == "One.woodshed"
    done = wait(server, job["id"])
    assert done["status"] == "done" and done["message"] == "1 of 2 lines placed on the voice"
    assert calls == [(server.library.root / "One.woodshed", WORDS)]
    assert {s["folder"]: s for s in server.library.pages()}["One.woodshed"]["words"]


def test_a_failed_placement_says_why_without_the_library_path(
    server: app.AppServer,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def refused(page: Path, text: str, offline: bool = False, say: Any = print, progress: Any = None) -> dict[str, Any]:
        raise lyrics.LyricsError(f"{page}: the instrument tracks of this song are not in the cache")

    monkeypatch.setattr(lyrics, "add_to_page", refused)
    status, job = post(server, "/api/lyrics", {"page": "Two.woodshed", "text": WORDS})
    assert status == 202
    done = wait(server, job["id"])
    assert done["status"] == "failed"  # read by every phone of the band: the folder, not the path
    assert done["message"] == "Two.woodshed: the instrument tracks of this song are not in the cache"


def test_a_job_is_shown_a_while_after_it_ends_not_after_it_starts(server: app.AppServer) -> None:  # noqa: F811
    long_ago = time.time() - 600  # placing the words took ten minutes (the model downloaded first)
    server.library.jobs["slow"] = app.Job("slow", "One.woodshed", status="done", started=long_ago, ended=time.time())
    server.library.jobs["old"] = app.Job("old", "Two.woodshed", status="done", started=long_ago, ended=long_ago)
    assert [j["id"] for j in server.library.state()["jobs"]] == ["slow"]


@pytest.mark.parametrize(
    ("data", "code"),
    [
        ({"page": "Nope.woodshed", "text": WORDS}, 400),
        ({"page": "../One.woodshed", "text": WORDS}, 400),
        ({"page": "One.woodshed", "text": "   \n"}, 400),
        ({"page": "One.woodshed", "text": 12}, 400),
        ({"page": "One.woodshed", "text": "la " * 12000}, 400),  # 36 KB: not the words of one song
        ({"page": "One.woodshed", "text": "la " * 25000}, 413),  # a body over 64 KB is not even read
        (["One.woodshed", WORDS], 400),
    ],
)
def test_words_are_checked(server: app.AppServer, data: Any, code: int) -> None:  # noqa: F811
    status, _ = post(server, "/api/lyrics", data)
    assert status == code
    assert server.library.state()["jobs"] == []


def test_one_job_at_a_time_for_a_song(server: app.AppServer) -> None:  # noqa: F811
    server.library.jobs["busy"] = app.Job("busy", "One.woodshed", status="analysing", page="One.woodshed")
    status, answer = post(server, "/api/lyrics", {"page": "One.woodshed", "text": WORDS})
    assert status == 409 and "already being worked on" in answer["error"]


def test_words_need_the_token_and_this_computer(server: app.AppServer, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    assert post(server, "/api/lyrics", {"page": "One.woodshed", "text": WORDS}, token="wrong")[0] == 403
    monkeypatch.setattr(app.Handler, "_from_this_computer", lambda self: False)  # a phone of the band
    status, answer = post(server, "/api/lyrics", {"page": "One.woodshed", "text": WORDS})
    assert status == 403 and "computer that runs the app" in answer["error"]
    assert server.library.state()["jobs"] == []
