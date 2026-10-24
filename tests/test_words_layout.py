"""A whole text laid by tapping along (spec 029-2): the pasted words read by the library's one reader
(lyrics.read), each line started where a tap fell (snapped to the nearest quarter beat, sent as a beat index),
its words spread by syllables, every time computed by the library. A layout is one change (one Undo), kept as
typed lines marked `by: "layout"`, so laying again replaces only its own lines. And `--no-words-model`."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from tests import test_word_fixes, woodshed_051
from tests.test_app import request
from tests.test_band import post
from tests.test_word_fixes import CHART, PAGE, fix, placement, read
from woodshed import app, cli, lyrics, typed

library = test_word_fixes.library  # one page, its words placed, its voice in the cache

TEXT = "[Verse 1]\nWhen you walk on\nhold on to the light\n\n[Chorus]\nla la la la (ooh)\n"


# Snapping and the spread (pure: the library's).


@pytest.mark.parametrize(("tap", "at"), [(10.1, 10.0), (10.12, 10.0), (10.13, 10.25), (10.4, 10.5), (10.9, 11.0)])
def test_a_tap_snaps_to_the_nearest_quarter_beat(tap: float, at: float) -> None:
    assert typed.snap(tap) == at


def test_each_tapped_line_starts_on_its_tap_and_spreads_its_syllables_one_a_beat() -> None:
    lines = [("When you walk on", "Verse 1"), ("hold on to the light", "Verse 1"), ("la la la la (ooh)", "Chorus")]
    got = typed.tapped_lines(lines, [2, 10.25, 24], CHART)
    assert [[w["at"] for w in ln["words"]] for ln in got] == [
        [2, 3, 4, 5],
        [10.25, 11.25, 12.25, 13.25, 14.25],
        [24, 25, 26, 27],
    ]
    assert [w["start"] for w in got[0]["words"]] == [1.0, 1.5, 2.0, 2.5]  # from the beats, 0.5 s each
    assert got[0]["words"][-1]["end"] == 3.0  # the last word ends with its syllable
    assert got[2]["backing"] == ["ooh"] and got[2]["text"] == "la la la la" and got[2]["tag"] == "Chorus"
    assert all(w["start"] == typed.beat_time(CHART, w["at"]) for ln in got for w in ln["words"])


def test_a_line_with_more_syllables_than_beats_takes_halves_then_quarters_then_even_time() -> None:
    six = typed.tapped_lines([("one two three four five six", ""), ("next", "")], [0, 4], CHART)[0]
    assert [w["at"] for w in six["words"]] == [0, 0.5, 1, 1.5, 2, 2.5]
    eight = typed.tapped_lines([("a b c d e f g h", ""), ("next", "")], [0, 2.5], CHART)[0]
    assert [w["at"] for w in eight["words"]] == [k / 4 for k in range(8)]
    nine = typed.tapped_lines([("a b c d e f g h i", ""), ("next", "")], [0, 2], CHART)[0]
    assert [w["at"] for w in nine["words"]] == pytest.approx([k * 2 / 9 for k in range(9)])
    assert nine["words"][-1]["end"] <= typed.beat_time(CHART, 2)  # never past the next line's start


def test_a_word_of_two_syllables_takes_two_beats_and_a_hold_one_more() -> None:
    got = typed.tapped_lines([("morning comes _ in", "")], [4], CHART)[0]
    assert [w["at"] for w in got["words"]] == [4, 6, 8]  # mor-ning, comes held a beat, in
    assert got["words"][1]["end"] == typed.beat_time(CHART, 8)


def test_taps_out_of_order_or_out_of_the_song_are_refused() -> None:
    two = [("la la", ""), ("li li", "")]
    for taps in ([4, 4], [8, 4], [-1, 4], [4, 48]):
        with pytest.raises(typed.TypedError):
            typed.tapped_lines(two, taps, CHART)
    with pytest.raises(typed.TypedError):
        typed.tapped_lines(two[:1], [1, 2], CHART)  # more taps than lines


# The library: one change, by:"layout", replaced by laying again, one Undo.


def lay(srv: app.AppServer, text: str, taps: Sequence[float], key: str | None = None) -> tuple[int, Any]:
    body = {"page": PAGE, "key": key or lyrics.words_key(placement(srv)), "layout": {"text": text, "taps": taps}}
    return post(srv, "/api/words", body)


def test_the_page_reads_the_text_with_the_librarys_reader(library: app.AppServer) -> None:
    text = "[Chorus]\nla la la (ooh)\n\nG D Em C\nПривет мой друг\n\n[Chorus]\n"  # noqa: RUF001
    status, answer = post(library, "/api/words-text", {"text": text})
    assert status == 200, answer
    assert [(ln["text"], ln["tag"]) for ln in answer["lines"]] == [
        ("la la la (ooh)", "Chorus"), ("Привет мой друг", ""), ("la la la (ooh)", "Chorus"),
    ]  # fmt: skip


def test_a_layout_is_laid_from_the_taps_and_marked_as_a_layout(library: app.AppServer) -> None:
    status, answer = lay(library, TEXT, [2.1, 10.2, 24])
    assert status == 200, answer
    assert len(answer["laid"]) == 3 and answer["left"] == 0 and answer["gone"] == []
    entries = [answer["lines"][k] for k in answer["laid"]]
    assert all(e["by"] == "layout" and e["typed"] is True and e["src"] == "abc" for e in entries)
    assert [e["lines"][0]["words"][0]["at"] for e in entries] == [2, 10.25, 24]  # snapped by the library too
    assert [e["lines"][0]["tag"] for e in entries] == ["Verse 1", "Verse 1", "Chorus"]
    assert read(library)["words"]["lines"] == answer["lines"]


def test_laying_again_replaces_only_its_own_lines(library: app.AppServer) -> None:
    fix(library, {"t00000001": {"typed": {"text": "la la", "at": 40}}})  # typed by hand: never replaced
    _, first = lay(library, TEXT, [2, 10, 24])
    status, again = lay(library, "one two three\nfour five six\nseven eight", [4, 20, 38])
    assert status == 200, again
    assert sorted(again["gone"]) == sorted(first["laid"])
    assert len(again["laid"]) == 2 and again["left"] == 1  # the last line would be sung over the hand-typed one
    assert set(again["lines"]) == {"t00000001", *again["laid"]}
    assert again["lines"]["t00000001"]["notation"] == "la la"


def test_a_layout_is_undone_in_one_step(library: app.AppServer, monkeypatch: pytest.MonkeyPatch) -> None:
    # The lines laid first sort before the ones laid again: brought back first, they would meet those still there.
    made = iter(["t0000000a", "t0000000b", "t0000000c", "tfffffff1", "tfffffff2"])
    monkeypatch.setattr(app, "_typed_key", lambda: next(made))
    _, first = lay(library, TEXT, [2, 10, 24])
    _, again = lay(library, "one two three\nfour five six", [4, 20])
    keys = again["laid"] + again["gone"]
    expect = {k: again["lines"].get(k) for k in keys}
    status, back = fix(library, {k: {"undo": True} for k in keys}, expect=expect)
    assert status == 200, back
    assert {k: (e["by"], e["lines"]) for k, e in back["lines"].items()} == {
        k: (e["by"], e["lines"]) for k, e in first["lines"].items()
    }


def test_a_layout_the_song_cannot_hold_is_refused_and_writes_nothing(library: app.AppServer) -> None:
    before = read(library)["words"]
    for taps in ([4, 4, 8], [2, 10, 24, 30], [2, 10, 400]):
        status, answer = lay(library, TEXT, taps)
        assert status == 400, answer
    assert read(library)["words"] == before


def test_an_older_woodshed_keeps_a_layout_as_it_was(library: app.AppServer) -> None:
    _, answer = lay(library, TEXT, [2, 10, 24])
    path = library.library.root / app.CORRECTIONS_DIR / f"{PAGE}.json"
    key = lyrics.words_key(placement(library))
    old = woodshed_051.read_words(path)
    assert not [k for k in old.get(key, {}).get("lines", {}) if k.startswith("t")]  # it never sees them
    woodshed_051.write_words(path, old)
    assert read(library)["words"]["lines"] == answer["lines"]  # all back, by:"layout" included


# A library that never uses the speech model.


def test_a_library_without_the_model_refuses_it_with_its_own_403(library: app.AppServer) -> None:
    library.library.words_model = False
    songs = json.loads(request(library, "GET", "/api/songs")[2])
    assert songs["words_model"] is False
    status, answer = post(library, "/api/lyrics", {"page": PAGE, "text": "la la la"})
    assert status == 403 and answer["code"] == "no-words-model"
    assert "type the words" in answer["error"]
    status, refused = post(library, "/api/lyrics", {"page": PAGE, "text": "la la la"}, token="wrong")
    assert status == 403 and "code" not in refused  # the token's 403 is another one
    assert lay(library, TEXT, [2, 10, 24])[0] == 200  # tapping along needs no model


def test_a_library_with_the_model_says_so(library: app.AppServer) -> None:
    assert json.loads(request(library, "GET", "/api/songs")[2])["words_model"] is True


@pytest.mark.parametrize(
    ("argv", "env", "want"), [([], None, True), (["--no-words-model"], None, False), ([], "1", False)]
)
def test_the_app_starts_without_the_model_by_flag_or_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, argv: list[str], env: str | None, want: bool
) -> None:
    seen: dict[str, Any] = {}
    monkeypatch.setattr("woodshed.app.serve", lambda *a, **k: seen.update(k))
    if env is not None:
        monkeypatch.setenv("WOODSHED_NO_WORDS_MODEL", env)
    else:
        monkeypatch.delenv("WOODSHED_NO_WORDS_MODEL", raising=False)
    assert cli.main(["app", str(tmp_path), "--no-open", *argv]) == 0
    assert seen["words_model"] is want
