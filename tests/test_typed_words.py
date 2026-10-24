"""The words typed by hand (spec 029-1): a line typed with `|` bar lines, read by the library (woodshed.typed, the
twin of the page's core/typed-words.js on one shared case file), kept in 028's store beside the band's fixes,
over the placed lines it covers, moved half a beat at a time, carried only within the same recording."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import pytest

from tests import test_word_fixes, woodshed_051
from tests.test_band import post
from tests.test_word_fixes import CHART, LINES, PAGE, fix, placement, read, stored
from woodshed import app, build, lyrics, stems, typed

library = test_word_fixes.library  # 028's library: one page, its words placed, its voice in the cache

CASES = json.loads((Path(__file__).parent / "words_typed_cases.json").read_text(encoding="utf-8"))
SONG = CASES["song"]


# The notation and the syllables (shared with the page: tests/page/test_words_by_hand.py).


@pytest.mark.parametrize("case", CASES["lines"], ids=[c["name"] for c in CASES["lines"]])
def test_a_typed_line_is_read_as_the_case_file_says(case: dict[str, Any]) -> None:
    until = typed.beat_time(SONG, case["until_at"]) if "until_at" in case else None
    if "error" in case:
        with pytest.raises(typed.TypedError) as err:
            typed.typed_line(case["text"], case["at"], SONG, case.get("old"), until)
        assert err.value.code == case["error"]
        if "bar" in case:
            assert err.value.bar == case["bar"]
        return
    got = typed.typed_line(case["text"], case["at"], SONG, case.get("old"), until)
    assert [w["at"] for w in got["words"]] == case["ats"]
    assert got["text"] == case["line"]
    assert got["backing"] == case.get("backing", [])
    kept = case.get("kept", [])
    for k, w in enumerate(got["words"]):
        if k in kept:  # a bar whose text did not change keeps its words where they were put
            assert w == case["old"]["words"][k]
        else:  # every time computed by the library from the beats
            assert w["start"] == typed.beat_time(SONG, w["at"])
    if "ends" in case:
        assert [w["end"] for w in got["words"]] == [typed.beat_time(SONG, a) for a in case["ends"]]
    starts = [w["start"] for w in got["words"]]
    assert starts == sorted(starts) and all(w["end"] >= w["start"] for w in got["words"])
    assert got["notation"] == case.get("notation", " ".join(case["text"].split()))


@pytest.mark.parametrize(("at", "t"), CASES["beats"])
def test_beats_to_times_with_the_bars_after_the_first_tracked_beat_and_past_the_last(at: float, t: float) -> None:
    assert typed.beat_time(SONG, at) == pytest.approx(t, abs=1e-9)
    if t > 0:
        assert typed.beat_at(SONG, t) == pytest.approx(at, abs=1e-6)  # and back


@pytest.mark.parametrize(("word", "n"), CASES["syllables"])
def test_syllables(word: str, n: int) -> None:
    assert typed.syllables(word) == n


def test_moving_the_bar_lines_keeps_a_typed_words_time_and_changes_its_bar() -> None:
    line = typed.typed_line("When you walk", 10, SONG)  # bar 3 of the case song (first beat 2)
    entry = {"typed": True, "src": None, "notation": line["notation"], "lines": [{**line, "tag": "", "check": None}]}
    shown = lyrics.apply_edits({"version": 1, "lines": []}, {"t0a1b2c3d": entry})["lines"][0]
    assert [w["start"] for w in shown["words"]] == [5.2, 5.7, 6.2]
    moved = {**SONG, "first_beat": 1}  # the bar lines a beat earlier: the beats stay, the bars move
    assert [w["start"] for w in shown["words"]] == [typed.beat_time(moved, a) for a in (10, 11, 12)]  # times kept
    assert typed.bar_of(SONG, line["words"][0]["at"]) == 2 and typed.bar_of(moved, line["words"][0]["at"]) == 2
    assert typed.bar_of(moved, line["words"][2]["at"]) == 2 and typed.bar_of(SONG, 13) == 2
    assert typed.bar_of(moved, 13) == 3  # beat 13 is the next bar's beat one now: the word is where it is sung


# Typed over placed (B4), in the one apply shared with the page.


def a_typed(text: str, at: float, song: dict[str, Any] = CHART) -> dict[str, Any]:
    line = typed.typed_line(text, at, song)
    return {"typed": True, "src": None, "notation": line["notation"], "lines": [{**line, "tag": "", "check": None}]}


def placed(*spans: tuple[float, float]) -> dict[str, Any]:
    line: dict[str, Any] = {"tag": None, "block": 0, "backing": [], "sung": True, "check": None}
    return {
        "version": 1,
        "lines": [
            {**line, "text": f"line {k}", "words": [{"text": "a", "start": s, "end": (s + e) / 2},
                                                   {"text": "b", "start": (s + e) / 2, "end": e}]}
            for k, (s, e) in enumerate(spans)
        ],
    }  # fmt: skip


def test_a_typed_line_covers_the_placed_lines_it_intersects_and_only_those() -> None:
    data = placed((1.0, 5.0), (6.0, 10.0), (11.0, 15.0))
    entries = {"t00000001": a_typed("the radio hums", 12)}  # 6.0 to 8.0 s
    out = lyrics.apply_edits(data, entries)["lines"]
    assert [ln.get("covered", False) for ln in out[:3]] == [False, True, False]
    assert out[1]["sung"] is False and out[3]["typed"] is True and out[3]["sung"] is True
    assert out[3]["key"] == "t00000001" and out[3]["text"] == "the radio hums"
    touching = lyrics.apply_edits(placed((1.0, 6.0)), entries)["lines"]  # ends where the typed line starts
    assert "covered" not in touching[0]
    tail = lyrics.apply_edits(placed((4.0, 6.5)), entries)["lines"]  # only its held tail inside: covered too
    assert tail[0]["covered"] is True
    assert lyrics.apply_edits(data, {})["lines"] == data["lines"]  # nothing typed: the placement as it was


def test_the_typed_entries_never_shift_the_placed_lines_index() -> None:
    data = placed((1.0, 5.0), (6.0, 10.0))
    entries = {"t00000002": a_typed("late words", 40), "t00000001": a_typed("early words", 0)}
    out = lyrics.apply_edits(data, entries)["lines"]
    assert [ln["text"] for ln in out] == ["line 0", "line 1", "early words", "late words"]  # in time order after


# Moving a word half a beat, without dragging.


def words_at(*ats: float) -> list[dict[str, Any]]:
    return [{"text": f"w{k}", "at": a, "start": typed.beat_time(CHART, a), "end": 0.0} for k, a in enumerate(ats)]


def test_a_word_moved_pushes_the_words_it_overtakes_half_a_beat_apart() -> None:
    ws = words_at(4, 5, 6, 8)
    out = typed.move(ws, 0, 6, CHART, 0.0, 20.0)
    assert [w["at"] for w in out] == [6, 6.5, 7, 8]
    assert [w["start"] for w in out] == [typed.beat_time(CHART, a) for a in (6, 6.5, 7, 8)]
    back = typed.move(ws, 3, 4.5, CHART, 0.0, 20.0)  # earlier: the words before it pushed back
    assert [w["at"] for w in back] == [3, 3.5, 4, 4.5]
    assert [w["at"] for w in typed.move(ws, 1, 5.5, CHART, 0.0, 20.0)] == [4, 5.5, 6, 8]  # overtaken only


def test_a_move_into_the_next_line_or_the_line_before_is_refused() -> None:
    ws = words_at(4, 5, 6)
    with pytest.raises(typed.TypedError) as err:
        typed.move(ws, 0, 7.5, CHART, 0.0, typed.beat_time(CHART, 8))  # pushes "w2" onto the next line's start
    assert err.value.code == "next"
    with pytest.raises(typed.TypedError) as err:
        typed.move(ws, 0, 1.5, CHART, typed.beat_time(CHART, 2), 20.0)
    assert err.value.code == "before"
    assert [w["at"] for w in typed.move(ws, 0, 6, CHART, 0.0, typed.beat_time(CHART, 8))] == [6, 6.5, 7]


def test_a_moved_word_keeps_its_length_and_the_others_their_times() -> None:
    ws = [
        {"text": "a", "start": 1.0, "end": 1.4},
        {"text": "b", "start": 1.6, "end": 2.3},
        {"text": "c", "start": 3.1, "end": 3.9},
    ]
    out = typed.move(ws, 1, 4, CHART, 0.0, 20.0)  # "b" to beat 4 (2.0 s)
    assert out[0] == ws[0] and out[2] == ws[2]  # byte-identical
    assert out[1]["start"] == 2.0 and out[1]["end"] == pytest.approx(2.7)


# The library: typed lines in 028's store.


def typed_fix(srv: app.AppServer, lines: dict[str, Any], **extra: Any) -> tuple[int, Any]:
    return fix(srv, lines, **extra)


def test_a_typed_line_is_read_timed_and_kept_by_the_library(library: app.AppServer) -> None:
    before = library.live.fixes.get(PAGE, 0)
    status, answer = typed_fix(library, {"t1a2b3c4d": {"typed": {"text": "When you | walk", "at": 40, "tag": "Outro"}}})
    assert status == 200, answer
    e = answer["lines"]["t1a2b3c4d"]
    assert e["typed"] is True and e["notation"] == "When you | walk" and e["src"] == "abc"
    line = e["lines"][0]
    assert line["text"] == "When you walk" and line["tag"] == "Outro" and line["check"] is None
    assert [(w["text"], w["at"], w["start"], w["end"]) for w in line["words"]] == [
        ("When", 40, 20.0, 21.0), ("you", 42, 21.0, 22.0), ("walk", 44, 22.0, 24.0),
    ]  # fmt: skip
    assert library.live.fixes[PAGE] > before
    assert read(library)["words"]["lines"] == answer["lines"]
    assert placement(library)["lines"][3]["text"] == LINES[3]  # the placement itself untouched


def test_saving_the_line_again_keeps_the_bars_that_did_not_change(library: app.AppServer) -> None:
    typed_fix(library, {"t1a2b3c4d": {"typed": {"text": "When you | walk", "at": 40}}})
    status, moved = typed_fix(library, {"t1a2b3c4d": {"timed": [[1, 41]]}})  # "you" half a bar earlier
    assert status == 200, moved
    assert moved["lines"]["t1a2b3c4d"]["notation"] == "When you | walk"
    status, answer = typed_fix(library, {"t1a2b3c4d": {"typed": {"text": "When you | walk on", "at": 40}}})
    assert status == 200, answer
    words = answer["lines"]["t1a2b3c4d"]["lines"][0]["words"]
    assert [w["at"] for w in words] == [40, 41, 44, 46]  # bar 11 kept as moved, bar 12 read again


@pytest.mark.parametrize(
    "value",
    [
        {"typed": {"text": " ".join(["la"] * 41), "at": 0}},  # 40 words at most
        {"typed": {"text": "a" * 201, "at": 0}},  # 200 characters
        {"typed": {"text": "la", "at": 48}},  # past the song's beats
        {"typed": {"text": "la", "at": 2}},  # not a bar's beat one
        {"typed": {"text": "la", "at": 0.5}},
        {"typed": {"text": "la", "at": True}},
        {"typed": {"text": "la\nla", "at": 0}},
        {"typed": {"text": "la", "at": 0, "words": [["la", 0, 0.1]]}},  # the library computes every time
        {"typed": {"text": "la", "at": 0, "start": 1.0}},
        {"typed": {"text": "la", "at": 0, "tag": "x" * 41}},
        {"typed": {"text": " ".join(["la"] * 17), "at": 0}},  # more than four syllables a beat
        {"timed": [[0, 0.2]]},  # half beats only
        {"timed": [[0, 4], [1, 5]]},  # one word a request
        {"timed": [[9, 4]]},  # no such word
        {"text": "la"},
    ],
)
def test_what_a_typed_line_cannot_be_is_refused(library: app.AppServer, value: dict[str, Any]) -> None:
    if "timed" in value and value["timed"] != [[9, 4]]:
        typed_fix(library, {"t1a2b3c4d": {"typed": {"text": "When you | walk", "at": 40}}})
    before = stored(library)
    status, _ = typed_fix(library, {"t1a2b3c4d": value})
    assert status == 400
    assert stored(library) == before


@pytest.mark.parametrize("key", ["t1a2b3c4", "T1a2b3c4d", "t1a2b3c4g", "tt1a2b3c4d"])
def test_a_typed_key_is_t_and_eight_hex_digits(library: app.AppServer, key: str) -> None:
    status, _ = typed_fix(library, {key: {"typed": {"text": "la", "at": 40}}})
    assert status == 400


def test_any_script_is_typed_and_control_characters_are_dropped(library: app.AppServer) -> None:
    status, answer = typed_fix(library, {"t00000001": {"typed": {"text": "Как‮ дела | 東京", "at": 40}}})
    assert status == 200, answer
    assert answer["lines"]["t00000001"]["lines"][0]["text"] == "Как дела 東京"


def test_typed_lines_never_overlap_each_other(library: app.AppServer) -> None:
    typed_fix(library, {"t00000001": {"typed": {"text": "When you | walk", "at": 40}}})  # bars 11 and 12
    before = stored(library)
    status, answer = typed_fix(library, {"t00000002": {"typed": {"text": "_ _ _ late", "at": 40}}})
    assert status == 400 and answer["error"] == typed.OVERLAP
    assert stored(library) == before
    status, answer = typed_fix(library, {"t00000003": {"typed": {"text": "just before", "at": 36}}})
    assert status == 200, answer  # bar 10: its last word ends where the other line starts
    assert answer["lines"]["t00000003"]["lines"][0]["words"][-1]["end"] == 20.0


def test_a_typed_line_over_a_placed_one_hides_it_and_taking_it_back_shows_it(library: app.AppServer) -> None:
    status, answer = typed_fix(library, {"t00000001": {"typed": {"text": "the radio sings", "at": 12}}})
    assert status == 200, answer
    out = lyrics.apply_edits(placement(library), answer["lines"])["lines"]
    assert out[1]["covered"] is True and out[1]["sung"] is False
    _, answer = typed_fix(library, {"t00000001": None})
    out = lyrics.apply_edits(placement(library), answer["lines"])["lines"]
    assert out[1]["sung"] is True and "covered" not in out[1]
    assert answer["removed"]["t00000001"]["typed"] is True  # remembered as taken back


def test_a_placed_word_moved_is_a_fixed_line_with_its_other_words_as_they_were(
    library: app.AppServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    def never(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("a word moved by hand is never aligned again")

    monkeypatch.setattr(lyrics, "place_line", never)
    monkeypatch.setattr(lyrics, "spread_line", never)
    words = placement(library)["lines"][1]["words"]
    status, answer = typed_fix(library, {"1": {"timed": [[2, 15]]}})  # "hums" to beat 15 (7.5 s)
    assert status == 200, answer
    e = answer["lines"]["1"]
    assert e["was"] == LINES[1] and "typed" not in e
    got = e["lines"][0]["words"]
    assert got[2]["start"] == 7.5
    for k, (w, was) in enumerate(zip(got, words, strict=True)):
        if k not in (1, 2):
            assert w == was  # byte-identical
    assert got[1]["end"] <= 7.5  # the word before it ends where it now starts
    out = lyrics.apply_edits(placement(library), answer["lines"])["lines"][1]
    assert out["edited"] is True and "typed" not in out


def test_a_move_refused_says_why_and_writes_nothing(library: app.AppServer) -> None:
    before = stored(library)
    status, answer = typed_fix(library, {"1": {"timed": [[0, 22]]}})  # "the" pushes the line into line 2 (11 s)
    assert status == 400 and answer["error"] == typed.NEXT
    assert stored(library) == before


def test_undo_of_a_typed_line_another_device_changed_is_refused(library: app.AppServer) -> None:
    _, mine = typed_fix(library, {"t00000001": {"typed": {"text": "When you | walk", "at": 40}}})
    typed_fix(library, {"t00000001": {"typed": {"text": "When you | run", "at": 40}}})  # another device
    status, answer = typed_fix(library, {"t00000001": None}, expect={"t00000001": mine["lines"]["t00000001"]})
    assert status == 409 and answer["changed"] == ["t00000001"]


# A page without words placed, the library's list, the carry (same recording only).


def test_a_page_with_no_placement_takes_typed_lines_under_the_empty_key(library: app.AppServer) -> None:
    (library.library.root / PAGE / lyrics.LYRICS).unlink()
    key = lyrics.words_key({"lines": []})
    assert not next(s for s in library.library.pages() if s["folder"] == PAGE)["words"]
    status, answer = typed_fix(library, {"t00000001": {"typed": {"text": "la la", "at": 0}}}, key=key)
    assert status == 200, answer
    assert read(library, key)["words"]["lines"] == answer["lines"]
    assert next(s for s in library.library.pages() if s["folder"] == PAGE)["words"] is True  # R17


def test_placing_the_words_with_the_model_carries_the_typed_lines_unchanged(
    library: app.AppServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.test_word_fixes import place_again

    (library.library.root / PAGE / lyrics.LYRICS).unlink()
    empty = lyrics.words_key({"lines": []})
    _, answer = typed_fix(library, {"t00000001": {"typed": {"text": "la la", "at": 44}}}, key=empty)
    job, new_key = place_again(library, monkeypatch, LINES)
    assert job.status == "done", job.message
    assert read(library, new_key)["words"]["lines"]["t00000001"] == answer["lines"]["t00000001"]


def test_typed_lines_of_another_recording_are_neither_answered_nor_carried(
    library: app.AppServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.test_word_fixes import place_again

    (library.library.root / PAGE / lyrics.LYRICS).unlink()
    empty = lyrics.words_key({"lines": []})
    typed_fix(library, {"t00000001": {"typed": {"text": "la la", "at": 44}}}, key=empty)
    path = library.library.root / app.CORRECTIONS_DIR / f"{PAGE}.json"
    body = json.loads(path.read_text(encoding="utf-8"))
    body["words_more"][empty]["lines"]["t00000001"]["src"] = "another"  # typed before the page was rebuilt from another
    path.write_text(json.dumps(body))
    assert read(library, empty)["words"]["lines"] == {}
    assert not next(s for s in library.library.pages() if s["folder"] == PAGE)["words"]
    job, new_key = place_again(library, monkeypatch, LINES)
    assert job.status == "done", job.message
    assert read(library, new_key)["words"]["lines"] == {}


def test_a_rebuild_from_another_recording_never_brings_typed_lines_back(
    library: app.AppServer, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, answer = typed_fix(library, {"t00000001": {"typed": {"text": "la la", "at": 44}}})
    monkeypatch.setattr(stems, "fingerprint", lambda path: "another")
    old = library.library.root / PAGE
    new = tmp_path / "rebuilt"
    new.mkdir()
    build._keep_lyrics(old, new, CHART, old / "index.html")
    assert (new / "lyrics.previous.json").exists() and not (new / lyrics.LYRICS).exists()
    carried, left = lyrics.carry_edits(placement(library), {"lines": []}, answer["lines"], None, CHART)
    assert carried == {"t00000001": answer["lines"]["t00000001"]} and left == 0  # carry_edits itself is pure
    notes: list[str] = []
    st = app.read_corrections(library.library.root / app.CORRECTIONS_DIR / f"{PAGE}.json")
    assert not app.carry_fixes(st, placement(library), {"version": 1, "lines": []}, None, CHART, notes, src="other")


def test_an_older_corrections_file_with_a_damaged_typed_entry_skips_it(library: app.AppServer) -> None:
    _, answer = typed_fix(library, {"t00000001": {"typed": {"text": "la la", "at": 44}}})
    path = library.library.root / app.CORRECTIONS_DIR / f"{PAGE}.json"
    body = json.loads(path.read_text(encoding="utf-8"))
    key = lyrics.words_key(placement(library))
    body["words_more"][key]["lines"]["t00000002"] = {"typed": True, "lines": [{"text": "x", "words": [{"text": "x"}]}]}
    body["words_more"][key]["lines"]["t00000003"] = {**answer["lines"]["t00000001"], "notation": 3}
    path.write_text(json.dumps(body))
    assert set(read(library)["words"]["lines"]) == {"t00000001"}


def test_no_time_from_the_client_is_ever_kept(library: app.AppServer) -> None:
    lines = {"t00000001": {"typed": {"text": "la", "at": 40}, "start": 3}}
    status, _ = post(library, "/api/words", {"page": PAGE, "key": lyrics.words_key(placement(library)), "lines": lines})
    assert status == 400
    assert math.isfinite(typed.beat_time(CHART, 40))


def test_undo_gives_back_the_line_as_it_was_before_its_last_change(library: app.AppServer) -> None:
    _, first = typed_fix(library, {"t00000001": {"typed": {"text": "When you | walk", "at": 40}}})
    _, moved = typed_fix(library, {"t00000001": {"timed": [[1, 41]]}})
    status, back = typed_fix(library, {"t00000001": {"undo": True}}, expect={"t00000001": moved["lines"]["t00000001"]})
    assert status == 200, back
    was = first["lines"]["t00000001"]
    assert back["lines"]["t00000001"] == {k: v for k, v in was.items() if k != "prev"}  # the word where it was
    typed_fix(library, {"t00000001": None})  # taken off
    status, again = typed_fix(library, {"t00000001": {"undo": True}})
    assert status == 200 and again["lines"]["t00000001"]["lines"] == first["lines"]["t00000001"]["lines"]
    status, _ = typed_fix(library, {"t00000009": {"undo": True}})  # nothing to undo
    assert status == 400


def test_undo_of_a_placed_word_moved_gives_back_its_line(library: app.AppServer) -> None:
    status, answer = typed_fix(library, {"1": {"timed": [[2, 15]]}})
    assert status == 200, answer
    status, back = typed_fix(library, {"1": {"undo": True}}, expect={"1": answer["lines"]["1"]})
    assert status == 200 and "1" not in back["lines"]  # the placement's line again
    _, fixed = fix(library, {"1": {"text": "the radio hums what the knight forgot"}})
    _, moved = typed_fix(library, {"1": {"timed": [[0, 12]]}})
    _, back = typed_fix(library, {"1": {"undo": True}})
    assert back["lines"]["1"] == fixed["lines"]["1"] and moved["lines"]["1"]["prev"] == fixed["lines"]["1"]


def test_typed_lines_of_another_recording_never_block_this_ones(library: app.AppServer) -> None:
    typed_fix(library, {"t00000001": {"typed": {"text": "When you | walk", "at": 40}}})
    manifest = library.library.root / PAGE / "woodshed.json"
    body = json.loads(manifest.read_text())
    body["settings"]["source"] = "another-recording"  # the page rebuilt from another recording
    manifest.write_text(json.dumps(body))
    assert not [k for k in read(library)["words"]["lines"] if k.startswith("t")]  # not shown here
    status, answer = typed_fix(library, {"t00000002": {"typed": {"text": "la la | la", "at": 40}}})
    assert status == 200, answer  # an invisible line does not block it
    status, answer = typed_fix(library, {"t00000002": {"timed": [[2, 47]]}})  # nor a move
    assert status == 200, answer
    status, answer = typed_fix(library, {"3": {"text": "we are only halfway through the nights"}})  # nor a fix
    assert status == 200, answer
    assert stored(library)["words_more"][lyrics.words_key(placement(library))]["lines"]["t00000001"]["src"] == "abc"


def test_undo_never_brings_back_a_line_over_another_devices_typed_line(library: app.AppServer) -> None:
    typed_fix(library, {"t00000001": {"typed": {"text": "When you | walk", "at": 40}}})
    _, gone = typed_fix(library, {"t00000001": None})  # taken off here
    typed_fix(library, {"t00000002": {"typed": {"text": "la la", "at": 40}}})  # another device types there
    before = stored(library)
    status, answer = typed_fix(library, {"t00000001": {"undo": True}})
    assert status == 400 and answer["error"] == typed.OVERLAP
    assert stored(library) == before
    assert "t00000001" in gone["removed"]


# An older woodshed (0.5.1) on the same library: it reads and writes back `words` only, keeps `words_more` as it is
# (spec 028 B's scheme). Lines typed by hand, typed lines taken back and `prev` live in `words_more` only.


def test_an_older_woodshed_saving_keeps_every_typed_line_and_moved_word(library: app.AppServer) -> None:
    from tests.test_split_join import sung_words

    fix(library, {"2": {"text": "a corrected line two"}})
    typed_fix(library, {"t1a2b3c4d": {"typed": {"text": "When you | walk", "at": 40}}})
    typed_fix(library, {"1": {"timed": [[2, 15]]}})  # a placed word moved: its line keeps `prev`
    typed_fix(library, {"t00000002": {"typed": {"text": "la la", "at": 12}}})
    _, answer = typed_fix(library, {"t00000002": None})  # a typed line taken back, remembered
    path = library.library.root / app.CORRECTIONS_DIR / f"{PAGE}.json"
    key = lyrics.words_key(placement(library))
    old = woodshed_051.read_words(path)
    assert not [k for k in old[key]["lines"] if k.startswith("t")]  # it never sees a typed line...
    assert sorted(old[key]["lines"]) == ["1", "2"] and "prev" not in old[key]["lines"]["1"]
    words = sung_words(placement(library), old[key]["lines"])
    assert words.count("radio") == 1 and "When" not in words  # ...and never shows a word twice
    woodshed_051.write_words(path, old)  # it saves a chord
    got = read(library)["words"]
    assert got["lines"] == answer["lines"] and got["removed"] == answer["removed"]  # all back, exactly


def test_what_an_older_woodshed_changed_on_a_moved_line_wins(library: app.AppServer) -> None:
    _, moved = typed_fix(library, {"1": {"timed": [[2, 15]]}})
    path = library.library.root / app.CORRECTIONS_DIR / f"{PAGE}.json"
    key = lyrics.words_key(placement(library))
    old = woodshed_051.read_words(path)
    old[key]["lines"]["1"]["lines"][0]["text"] = "the radio hums what the night forgets"  # fixed on the older one
    woodshed_051.write_words(path, old)
    got = read(library)["words"]["lines"]["1"]
    assert got["lines"][0]["text"] == "the radio hums what the night forgets" and "prev" not in got
    assert moved["lines"]["1"]["prev"] is None
