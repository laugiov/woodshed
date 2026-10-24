"""Splitting a line and joining two lines of the words on the sheet (spec 028 B, R13, R14).

A split line stays one fix, kept under its index in lyrics.json, with two to four lines placed together in
the line's window; a join places two lines as one in the window of both, the second kept as "joined". The
risk is the line numbers: the sheet shows more (or fewer) lines than the placement holds, while every fix,
window and Undo names a line by its index in the placement. The speech model is never run here."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tests.test_band import post
from tests.test_exports import pop  # noqa: F401  (the fixture)
from tests.test_lyrics import voice
from tests.test_word_fixes import (
    CHART,
    LENGTH,
    LINES,
    PAGE,
    SUNG,
    F,
    fix,
    hand,
    library,  # noqa: F401  (the fixture)
    read,
    starts_sung,
    stored,
    write_page,
)
from woodshed import app, exports, lyrics, stems
from woodshed.run import Options

SPLIT = ["the radio hums", "what the night forgot"]  # LINES[1] in two


def near(words: list[dict[str, Any]], truth: list[float]) -> bool:
    """Each word within two frames of when the synthetic voice sings it."""
    return len(words) == len(truth) and all(
        abs(w["start"] - t) <= 2 * F + 1e-9 for w, t in zip(words, truth, strict=True)
    )


def spy_on_align(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    seen: list[int] = []
    align = lyrics.ctc_align

    def spy(log_probs: Any, tokens: Any, blank: int) -> Any:
        seen.append(log_probs.shape[0])
        return align(log_probs, tokens, blank)

    monkeypatch.setattr(lyrics, "ctc_align", spy)
    return seen


# Placing a split and a join (A20).


def test_a_split_is_placed_in_one_window_a_wildcard_between_its_lines(monkeypatch: pytest.MonkeyPatch) -> None:
    v = voice(SUNG, LENGTH)
    data = hand(SUNG)
    seen = spy_on_align(monkeypatch)
    pieces = lyrics.place_pieces(v, data["lines"], 1, SPLIT, CHART)
    a, b = lyrics.line_window(data["lines"], 1, data["lines"][1], CHART, v.emission.shape[0], False)
    assert seen == [b - a]  # one alignment over the line's window, not one per half
    assert [p["text"] for p in pieces] == SPLIT
    truth = starts_sung(*SUNG[1])
    assert near(pieces[0]["words"], truth[:3]) and near(pieces[1]["words"], truth[3:])
    assert pieces[0]["words"][-1]["end"] <= pieces[1]["words"][0]["start"]


def test_a_join_is_placed_as_one_line_in_the_window_of_both(monkeypatch: pytest.MonkeyPatch) -> None:
    v = voice(SUNG, LENGTH)
    data = hand(SUNG)
    own = lyrics.joined(data["lines"], 1, 1)
    assert own["words"][0] == data["lines"][1]["words"][0] and own["words"][-1] == data["lines"][2]["words"][-1]
    lines = lyrics.edited_lines(data, {"2": {"was": LINES[2], "gone": "joined"}})
    a, b = lyrics.line_window(lines, 1, own, CHART, v.emission.shape[0], False)
    assert a == round((SUNG[1][1] - lyrics.MARGIN_FIRST) / F) and b == round(SUNG[3][1] / F)  # up to line 4
    seen = spy_on_align(monkeypatch)
    (line,) = lyrics.place_pieces(v, lines, 1, [LINES[1] + " " + LINES[2]], CHART, own)
    assert seen == [b - a]
    assert near(line["words"], starts_sung(*SUNG[1]) + starts_sung(*SUNG[2]))


def test_without_the_voice_heard_before_a_split_is_spread_over_the_lines_time() -> None:
    data = hand(SUNG)
    pieces = lyrics.spread_pieces(data["lines"][1], SPLIT)
    assert [p["text"] for p in pieces] == SPLIT
    assert pieces[0]["words"][0]["start"] == SUNG[1][1] and pieces[1]["words"][-1]["end"] == SUNG[1][2]
    assert pieces[0]["words"][-1]["end"] == pieces[1]["words"][0]["start"]
    assert {p["check"] for p in pieces} == {lyrics.SPREAD_CHECK}


# The words with the fixes: more rows than the placement, every fix still by its index (R12, R13).


def split_entry(data: dict[str, Any], i: int, texts: list[str], v: lyrics.Voice) -> dict[str, Any]:
    return {"was": data["lines"][i]["text"], "lines": lyrics.place_pieces(v, data["lines"], i, texts, CHART)}


def test_a_split_line_shows_as_rows_and_the_lines_around_it_keep_theirs() -> None:
    v = voice(SUNG, LENGTH)
    data = {**hand(SUNG), "markers": [{"before": 2, "tag": "Solo"}, {"before": 4, "tag": "Outro"}]}
    fixed0 = lyrics.place_line(v, data["lines"], 0, "Morning comes in on the harbor road", CHART)
    fixed3 = lyrics.place_line(v, data["lines"], 3, "we are only halfway through the nights", CHART)
    entries = {
        "0": {"was": LINES[0], "lines": [fixed0]},
        "1": split_entry(data, 1, SPLIT, v),
        "3": {"was": LINES[3], "lines": [fixed3]},
    }
    rows = lyrics.apply_edits(data, entries)["lines"]
    assert [r["text"] for r in rows] == [fixed0["text"], *SPLIT, LINES[2], fixed3["text"]]
    assert [r.get("piece") for r in rows] == [None, None, 1, None, None]  # the second row continues line 2
    assert rows[2]["edited"] is True and rows[2]["block"] == rows[1]["block"]
    no_split = lyrics.apply_edits(data, {k: e for k, e in entries.items() if k != "1"})["lines"]
    assert [rows[0], rows[3], rows[4]] == [no_split[0], no_split[2], no_split[3]]  # nothing else changed
    # Markers name the line they come before: the same lines, one row further down.
    assert lyrics.apply_edits(data, entries)["markers"] == [{"before": 3, "tag": "Solo"}, {"before": 5, "tag": "Outro"}]
    # By its index again (the windows of the lines around it): one line, its pieces' words.
    by_index = lyrics.edited_lines(data, entries)
    assert len(by_index) == 4 and by_index[1]["words"] == rows[1]["words"] + rows[2]["words"]
    assert by_index[3] == rows[4]


def test_a_joined_line_is_no_longer_sung_and_its_rows_stay_in_place() -> None:
    v = voice(SUNG, LENGTH)
    data = hand(SUNG)
    own = lyrics.joined(data["lines"], 1, 1)
    lines = lyrics.edited_lines(data, {"2": {"was": LINES[2], "gone": "joined"}})
    (line,) = lyrics.place_pieces(v, lines, 1, [LINES[1] + " " + LINES[2]], CHART, own)
    entries = {"1": {"was": LINES[1], "lines": [line]}, "2": {"was": LINES[2], "gone": "joined"}}
    rows = lyrics.apply_edits(data, entries)["lines"]
    assert len(rows) == 4 and rows[2]["sung"] is False and rows[2]["edited"] == "joined"
    assert rows[1]["text"] == LINES[1] + " " + LINES[2] and [rows[0], rows[3]] == [data["lines"][0], data["lines"][3]]


# The library: a split, a join, the line numbers of the fixes around them (R11, R13).


def test_a_split_line_is_kept_as_one_fix_and_the_lines_after_it_are_fixed_by_their_own_index(
    library: app.AppServer,  # noqa: F811
) -> None:
    status, answer = fix(library, {"1": {"text": "the radio hums\nwhat the night forgot"}})
    assert status == 200, answer
    pieces = answer["lines"]["1"]["lines"]
    assert [p["text"] for p in pieces] == SPLIT and answer["lines"]["1"]["was"] == LINES[1]
    truth = starts_sung(*SUNG[1])
    assert near(pieces[0]["words"], truth[:3]) and near(pieces[1]["words"], truth[3:])
    # Line 3 and line 4 are still lines 3 and 4 of the placement, their windows between their own neighbours,
    # though the sheet shows a row more before them.
    status, answer = fix(library, {"2": {"text": "Hold on, hold on to the northern light"}})
    assert status == 200, answer
    assert near(answer["lines"]["2"]["lines"][0]["words"], starts_sung(*SUNG[2]))
    status, answer = fix(library, {"3": {"text": "We are only halfway through the night!"}})
    assert status == 200, answer
    assert near(answer["lines"]["3"]["lines"][0]["words"], starts_sung(*SUNG[3]))
    status, answer = fix(library, {"0": {"text": "Morning comes in on the harbour road!"}})
    assert status == 200, answer
    assert near(answer["lines"]["0"]["lines"][0]["words"], starts_sung(*SUNG[0]))
    assert set(read(library)["words"]["lines"]) == {"0", "1", "2", "3"}


def test_a_split_line_written_back_as_one_line_is_one_line_again(library: app.AppServer) -> None:  # noqa: F811
    fix(library, {"1": {"text": "the radio hums\nwhat the night forgot"}})
    _, answer = fix(library, {"1": {"text": LINES[1]}})
    assert "1" not in answer["lines"]  # the placement's words again
    _, answer = fix(library, {"1": {"text": "the radio\nhums what\nthe night\nforgot"}})
    assert len(answer["lines"]["1"]["lines"]) == 4


def test_a_join_places_both_lines_in_the_window_of_the_two(library: app.AppServer) -> None:  # noqa: F811
    status, answer = fix(library, {"1": {"text": LINES[1] + " " + LINES[2]}, "2": {"gone": "joined"}})
    assert status == 200, answer
    assert answer["lines"]["2"] == {"was": LINES[2], "gone": "joined"}
    (line,) = answer["lines"]["1"]["lines"]
    assert near(line["words"], starts_sung(*SUNG[1]) + starts_sung(*SUNG[2]))
    # The line after a join keeps its own window: it starts after the joined line ends.
    status, answer = fix(library, {"3": {"text": "We are only halfway through the night!"}})
    assert status == 200 and near(answer["lines"]["3"]["lines"][0]["words"], starts_sung(*SUNG[3]))
    # The joined line written again (a typo fixed) keeps the line it holds.
    status, answer = fix(library, {"1": {"text": LINES[1] + ", " + LINES[2] + "!"}})
    assert status == 200 and answer["lines"]["2"]["gone"] == "joined"
    assert len(answer["lines"]["1"]["lines"][0]["words"]) == len((LINES[1] + " " + LINES[2]).split())


def test_taking_back_a_joined_line_brings_back_the_line_it_held(library: app.AppServer) -> None:  # noqa: F811
    fix(library, {"1": {"text": LINES[1] + " " + LINES[2]}, "2": {"gone": "joined"}})
    _, answer = fix(library, {"1": None})
    assert answer["lines"] == {} and set(answer["removed"]) == {"1", "2"}
    fix(library, {"1": {"text": LINES[1] + " " + LINES[2]}, "2": {"gone": "joined"}})
    _, answer = fix(library, {"1": {"gone": "not-sung"}})  # out of this recording: the held line is its own again
    assert set(answer["lines"]) == {"1"}


@pytest.mark.parametrize(
    "lines",
    [
        {"2": {"gone": "joined"}},  # into a line the band has not fixed
        {"1": {"gone": "not-sung"}, "2": {"gone": "joined"}},  # into a line taken out
        {"0": {"text": LINES[0]}, "1": {"gone": "joined"}},  # into the placement's own words: nothing joined
        {"1": {"text": "a\nb\nc\nd\ne"}},  # four lines at most
        {"1": {"text": "the radio hums\n\nwhat the night forgot"}},  # an empty line in between
        {"1": {"text": "the radio hums\n\u043c\u0438\u0440"}},
    ],
)
def test_a_join_or_a_split_the_page_cannot_ask_is_refused(
    library: app.AppServer,  # noqa: F811
    lines: dict[str, Any],
) -> None:
    status, _ = fix(library, lines)
    assert status == 400
    assert stored(library) == {}


def test_a_join_stays_within_one_part(library: app.AppServer) -> None:  # noqa: F811
    data = hand(SUNG)
    data["lines"][2]["block"] = 1  # the chorus: another part
    write_page(library.library.root / PAGE, data)
    status, answer = fix(library, {"1": {"text": LINES[1] + " " + LINES[2]}, "2": {"gone": "joined"}})
    assert status == 400 and "part" in answer["error"]
    data["lines"][2]["block"], data["lines"][2]["sung"] = 0, False  # not sung: nothing to join
    write_page(library.library.root / PAGE, data)
    status, _ = fix(library, {"1": {"text": LINES[1] + " " + LINES[2]}, "2": {"gone": "joined"}})
    assert status == 400


# Undo of a split or a join: the whole of it, and never over another device's fix (the if-match rule).


def test_undo_of_a_split_takes_back_the_whole_split_unless_another_device_changed_it(
    library: app.AppServer,  # noqa: F811
) -> None:
    _, mine = fix(library, {"1": {"text": "the radio hums\nwhat the night forgot"}})
    _, theirs = fix(library, {"1": {"text": "the radio hums\nwhat the night forgets"}})  # another device
    before = stored(library)
    status, answer = fix(library, {"1": None}, expect={"1": mine["lines"]["1"]})
    assert status == 409 and answer["changed"] == ["1"] and stored(library) == before
    status, answer = fix(library, {"1": None}, expect={"1": theirs["lines"]["1"]})
    assert status == 200 and answer["lines"] == {}


def test_undo_of_a_join_brings_both_lines_back_unless_another_device_changed_one(
    library: app.AppServer,  # noqa: F811
) -> None:
    _, joined = fix(library, {"1": {"text": LINES[1] + " " + LINES[2]}, "2": {"gone": "joined"}})
    expect = {"1": joined["lines"]["1"], "2": joined["lines"]["2"]}
    _, theirs = fix(library, {"1": {"text": LINES[1] + " " + LINES[2] + "!"}})  # another device, the joined line
    before = stored(library)
    status, answer = fix(library, {"1": None, "2": None}, expect=expect)
    assert status == 409 and answer["changed"] == ["1"] and stored(library) == before
    expect["1"] = theirs["lines"]["1"]
    status, answer = fix(library, {"1": None, "2": None}, expect=expect)
    assert status == 200 and answer["lines"] == {}
    # Undo of that take-back: the join again, as it was.
    status, answer = fix(
        library,
        {"1": {"text": LINES[1] + " " + LINES[2] + "!"}, "2": {"gone": "joined"}},
        expect={"1": None, "2": None},
    )
    assert status == 200 and answer["lines"]["1"] == theirs["lines"]["1"] and answer["lines"]["2"]["gone"] == "joined"


def test_a_split_and_a_join_survive_a_chord_save_and_a_reread(library: app.AppServer) -> None:  # noqa: F811
    fix(library, {"0": {"text": "morning comes in\non the harbour road"}})
    _, answer = fix(library, {"1": {"text": LINES[1] + " " + LINES[2]}, "2": {"gone": "joined"}})
    post(library, "/api/corrections", {"page": PAGE, "key": "a1b2c3", "fixes": {"3": [9, "m"]}})
    assert read(library)["words"]["lines"] == answer["lines"]  # read back through the file's own checks


# Carrying a split and a join over a new placement (R16).


def place_on(text_lines: list[str]) -> tuple[dict[str, Any], lyrics.Voice]:
    sung = [(t, 1.0 + 5 * k, 5.0 + 5 * k) for k, t in enumerate(text_lines)]
    return hand(sung), voice(sung, 40.0)


def test_a_split_follows_its_line_to_a_new_placement() -> None:
    old, v_old = place_on(LINES)
    new, v_new = place_on([LINES[0], "a line pasted in between", *LINES[1:]])
    entries = {"1": split_entry(old, 1, SPLIT, v_old)}
    carried, left = lyrics.carry_edits(old, new, entries, v_new, CHART)
    assert left == 0 and set(carried) == {"2"}
    pieces = carried["2"]["lines"]
    assert [p["text"] for p in pieces] == SPLIT
    truth = starts_sung(LINES[1], 11.0, 15.0)  # placed again in its new window
    assert near(pieces[0]["words"], truth[:3]) and near(pieces[1]["words"], truth[3:])


def test_a_join_follows_its_lines_or_is_left_out_whole() -> None:
    old, v_old = place_on(LINES)
    own = lyrics.joined(old["lines"], 1, 1)
    lines = lyrics.edited_lines(old, {"2": {"was": LINES[2], "gone": "joined"}})
    (line,) = lyrics.place_pieces(v_old, lines, 1, [LINES[1] + " " + LINES[2]], CHART, own)
    entries = {"1": {"was": LINES[1], "lines": [line]}, "2": {"was": LINES[2], "gone": "joined"}}
    new, v_new = place_on(["a new first line", *LINES])
    carried, left = lyrics.carry_edits(old, new, entries, v_new, CHART)
    assert left == 0 and set(carried) == {"2", "3"} and carried["3"] == {"was": LINES[2], "gone": "joined"}
    assert near(
        carried["2"]["lines"][0]["words"], starts_sung(LINES[1], 11.0, 15.0) + starts_sung(LINES[2], 16.0, 20.0)
    )
    # The held line changed in the new paste: the join cannot stand, both are left out.
    changed, v_changed = place_on([LINES[0], LINES[1], "hold on to the southern light", LINES[3]])
    carried, left = lyrics.carry_edits(old, changed, entries, v_changed, CHART)
    assert carried == {} and left == 2


# The songbook file of the page, rewritten with the fixes after each change (R14).


@pytest.fixture
def songbook(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, pop: dict[str, Any]) -> Any:  # noqa: F811
    """A library whose page has a real chart (pop), its exports folder, and words placed on it."""
    monkeypatch.setenv("WOODSHED_CACHE", str(tmp_path / "cache"))
    lib = app.Library(tmp_path / "library", Options(use_stems=False, open_page=False))
    starts = [b["start"] for b in pop["bars"]]
    sung = [
        ("morning comes in on the harbour road", starts[0] + 0.1, starts[2] - 0.2),
        ("the radio hums what the night forgot", starts[2] + 0.1, starts[4] - 0.2),
        ("hold on to the northern light", starts[4] + 0.1, starts[6] - 0.2),
    ]
    data = hand(sung)
    page = lib.root / PAGE
    write_page(page, data, chart=pop)
    (page / "exports").mkdir()
    exports.write_chordpro(pop, page / "exports", data)
    heard = voice(sung, float(pop["duration"]) + 1)
    monkeypatch.setattr(app.Library, "_voice", lambda self, folder: heard)
    return lib, page / "exports" / f"{exports.file_stem(pop)}.cho", pop, sung


def test_the_songbook_file_is_written_with_the_fixes_after_each_change(songbook: Any) -> None:
    lib, cho, chart, _ = songbook
    key = lyrics.words_key(json.loads((lib.root / PAGE / lyrics.LYRICS).read_text(encoding="utf-8")))
    saved = lib.set_words({"page": PAGE, "key": key, "lines": {"1": {"text": "the radio hums\nwhat the night forgot"}}})
    text = cho.read_text(encoding="utf-8")
    placed = json.loads((lib.root / PAGE / lyrics.LYRICS).read_text(encoding="utf-8"))
    assert text == exports.chordpro(chart, lyrics.apply_edits(placed, saved["lines"]))
    rows = [r for r in text.splitlines() if "radio" in r or "forgot" in r]
    assert len(rows) == 2 and "forgot" not in rows[0]  # two rows of the songbook
    lib.set_words({"page": PAGE, "key": key, "lines": {"2": {"gone": "not-sung"}}})
    assert "northern" not in cho.read_text(encoding="utf-8")
    lib.set_words({"page": PAGE, "key": key, "lines": {"1": None, "2": None}})
    assert cho.read_text(encoding="utf-8") == exports.chordpro(chart, placed)  # the placement's words again
    assert not [p for p in cho.parent.iterdir() if p.name.startswith(".")]  # written whole, no leftover


def test_placing_the_words_again_writes_the_songbook_with_the_fixes_carried(
    songbook: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    lib, cho, chart, sung = songbook
    key = lyrics.words_key(json.loads((lib.root / PAGE / lyrics.LYRICS).read_text(encoding="utf-8")))
    lib.set_words({"page": PAGE, "key": key, "lines": {"1": {"text": "the radio hums\nwhat the night forgot"}}})
    monkeypatch.setattr(lyrics, "listen", lambda *args, **kwargs: voice(sung, float(chart["duration"]) + 1))
    monkeypatch.setattr(lyrics, "stems_folder", lambda page: page)
    monkeypatch.setattr(lib.queue, "task_done", lambda: None)
    job = app.Job("j", PAGE, page=PAGE, kind="words")
    lib._place_words(job, lib.root / PAGE, "\n".join(t for t, _, _ in sung), lib.opts)
    assert job.status == "done", job.message
    rows = [r for r in cho.read_text(encoding="utf-8").splitlines() if "radio" in r or "forgot" in r]
    assert len(rows) == 2  # the split carried to the new placement, in the songbook too


def test_a_rebuild_keeps_the_fixes_in_the_songbook_file(
    songbook: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from woodshed import build

    lib, cho, chart, _ = songbook
    monkeypatch.setattr(stems, "fingerprint", lambda path: "abc")
    old = lib.root / PAGE
    key = lyrics.words_key(json.loads((old / lyrics.LYRICS).read_text(encoding="utf-8")))
    lib.set_words({"page": PAGE, "key": key, "lines": {"1": {"text": "the radio hums\nwhat the night forgot"}}})
    new = tmp_path / "rebuilt"
    (new / "exports").mkdir(parents=True)
    build._keep_lyrics(old, new, chart, old / "index.html")
    rows = [
        r
        for r in (new / "exports" / cho.name).read_text(encoding="utf-8").splitlines()
        if "radio" in r or "forgot" in r
    ]
    assert len(rows) == 2
