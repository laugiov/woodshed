"""The set's name (spec 030): kept beside the songs in setlist.json, read and written through /api/setlist, its
revision carried by the polled /api/songs answer so every open library sees a new name."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from tests.test_app import request
from tests.test_band import post, server  # noqa: F401  (the fixture)
from woodshed import app

CASES = json.loads((Path(__file__).parent / "set_name_cases.json").read_text(encoding="utf-8"))


def get(srv: app.AppServer, path: str) -> Any:
    return json.loads(request(srv, "GET", path)[2])


@pytest.mark.parametrize(("given", "kept"), CASES)
def test_a_name_is_normalised_or_refused(given: Any, kept: Any) -> None:
    if kept == "refused":
        with pytest.raises(ValueError):
            app.normalise_set_title(given)
    else:
        assert app.normalise_set_title(given) == kept


def test_a_name_is_kept_beside_the_songs(server: app.AppServer) -> None:  # noqa: F811
    assert get(server, "/api/setlist") == {"songs": [], "title": None, "rev": ""}
    status, answer = post(server, "/api/setlist", {"title": "  Les   Imprévus  "})
    assert status == 200 and answer["title"] == "Les Imprévus" and answer["songs"] == [] and answer["rev"]
    _, answer = post(server, "/api/setlist", {"songs": ["Two.woodshed", "One.woodshed"]})
    assert answer["title"] == "Les Imprévus"  # saving the songs keeps the name
    _, answer = post(server, "/api/setlist", {"title": "Les Imprévus · saison 2026-2027"})
    assert answer["songs"] == ["Two.woodshed", "One.woodshed"]  # saving the name keeps the songs
    assert get(server, "/api/setlist") == answer
    saved = json.loads((server.library.root / app.SETLIST).read_text(encoding="utf-8"))
    assert saved == {"title": "Les Imprévus · saison 2026-2027", "songs": ["Two.woodshed", "One.woodshed"]}


@pytest.mark.parametrize("gone", ["", None, "   "])
def test_an_empty_name_removes_it(server: app.AppServer, gone: Any) -> None:  # noqa: F811
    post(server, "/api/setlist", {"songs": ["One.woodshed"], "title": "Les Imprévus"})
    _, answer = post(server, "/api/setlist", {"title": gone})
    assert answer["title"] is None and answer["songs"] == ["One.woodshed"]
    assert "title" not in json.loads((server.library.root / app.SETLIST).read_text(encoding="utf-8"))


@pytest.mark.parametrize("data", [{"title": "a" * 81}, {"title": 42}, {"title": "bad‮name"}, {"other": 1}])
def test_a_bad_name_is_refused_and_nothing_is_written(server: app.AppServer, data: Any) -> None:  # noqa: F811
    status, answer = post(server, "/api/setlist", data)
    assert status == 400 and answer["error"]
    assert not (server.library.root / app.SETLIST).exists()


def test_a_name_alone_is_refused_when_the_set_cannot_be_read(server: app.AppServer) -> None:  # noqa: F811
    setlist = server.library.root / app.SETLIST
    setlist.write_text("{not json", encoding="utf-8")
    status, answer = post(server, "/api/setlist", {"title": "Les Imprévus"})
    assert status == 409 and answer["error"]
    assert setlist.read_text(encoding="utf-8") == "{not json"  # the set is not emptied
    status, answer = post(server, "/api/setlist", {"songs": ["One.woodshed"], "title": "Les Imprévus"})
    assert status == 200 and answer["songs"] == ["One.woodshed"]  # a whole set may replace it


def test_keys_woodshed_does_not_know_are_kept(server: app.AppServer) -> None:  # noqa: F811
    setlist = server.library.root / app.SETLIST
    setlist.write_text(json.dumps({"songs": ["One.woodshed"], "venue": "Le Bar"}), encoding="utf-8")
    post(server, "/api/setlist", {"title": "Les Imprévus"})
    post(server, "/api/setlist", {"songs": ["Two.woodshed"]})
    saved = json.loads(setlist.read_text(encoding="utf-8"))
    assert saved == {"songs": ["Two.woodshed"], "venue": "Le Bar", "title": "Les Imprévus"}


def test_the_set_is_written_under_the_file_lock(server: app.AppServer, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    locked: list[Path] = []
    real = app.corrections_lock

    def watch(path: Path) -> Any:
        locked.append(path)
        return real(path)

    monkeypatch.setattr(app, "corrections_lock", watch)
    post(server, "/api/setlist", {"title": "Les Imprévus"})
    assert server.library.root / f".{app.SETLIST}" in locked  # a hidden lock file beside it


def test_the_revision_follows_the_file(server: app.AppServer) -> None:  # noqa: F811
    assert get(server, "/api/songs")["set"] == {"rev": "", "title": None}
    _, answer = post(server, "/api/setlist", {"title": "Les Imprévus"})
    first = answer["rev"]
    assert get(server, "/api/songs")["set"] == {"rev": first, "title": "Les Imprévus"}
    _, again = post(server, "/api/setlist", {"title": "Les Imprévus"})
    assert again["rev"] == first  # same content, same revision
    # A hand edit, or another woodshed on the library: a new revision without this process saving.
    setlist = server.library.root / app.SETLIST
    setlist.write_text(json.dumps({"title": "Les Imprévistes", "songs": []}), encoding="utf-8")
    stat = setlist.stat()
    os.utime(setlist, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
    state = get(server, "/api/songs")["set"]
    assert state["title"] == "Les Imprévistes" and state["rev"] not in ("", first)


def test_the_revision_is_read_from_the_disk_only_when_the_file_changed(
    server: app.AppServer,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    post(server, "/api/setlist", {"title": "Les Imprévus"})
    server.library.set_rev()
    reads: list[Path] = []
    real = Path.read_bytes

    def counted(self: Path) -> bytes:
        reads.append(self)
        return real(self)

    monkeypatch.setattr(Path, "read_bytes", counted)
    for _ in range(3):
        server.library.set_rev()
    assert not reads  # a stat each time, no read
