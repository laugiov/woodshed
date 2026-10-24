"""Fixing a line of the words on the sheet (spec 028 A): only that line placed again, in its own window,
on the voice heard before; kept by the library beside the chord corrections, shared with the band.

The speech model is never run here: the synthetic voice of test_lyrics gives each letter at a known time."""

from __future__ import annotations

import contextlib
import json
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from tests.test_app import request
from tests.test_band import post
from tests.test_lyrics import LABELS, song, voice
from woodshed import app, build, cli, corrections, lyrics, stems
from woodshed.fnv import fnv1a
from woodshed.run import Options

F = lyrics.FRAME
PAGE = "Song.woodshed"
CHART = song(12, [(7, ""), (0, ""), (2, ""), (7, "")])  # 120 BPM, four beats: a bar is 2 s
BAR = 2.0
LINES = [
    "morning comes in on the harbour road",
    "the radio hums what the night forgot",
    "hold on hold on to the northern light",
    "we are only halfway through the night",
]
SUNG = [(t, 1.0 + 5 * k, 5.0 + 5 * k) for k, t in enumerate(LINES)]  # four seconds each, a second apart
LENGTH = 24.0


def starts_sung(text: str, start: float, end: float) -> list[float]:
    """When each word of a line is sung by the synthetic voice: its first letter's frame."""
    letters = "".join(lyrics.letters_of(w) for w in text.split())
    a, b = int(start / F), int(end / F)
    step = (b - a) / len(letters)
    out, at = [], 0
    for w in text.split():
        out.append(round((a + int(at * step)) * F, 3))
        at += len(lyrics.letters_of(w))
    return out


def hand(sung: list[tuple[str, float, float]], check: str | None = None) -> dict[str, Any]:
    """A placement written by hand: each word where the synthetic voice sings it."""
    lines = []
    for text, start, end in sung:
        starts = starts_sung(text, start, end)
        ends = [*starts[1:], end]
        words = [{"text": w, "start": s, "end": e} for w, s, e in zip(text.split(), starts, ends, strict=True)]
        line: dict[str, Any] = {"text": text, "tag": None, "block": 0, "backing": [], "sung": True, "check": check}
        lines.append({**line, "words": words})
    return {"version": 1, "language": "en", "text": "\n".join(t for t, _, _ in sung), "lines": lines, "chords": []}


def entry(data: dict[str, Any], i: int, line: dict[str, Any]) -> dict[str, Any]:
    return {"was": data["lines"][i]["text"], "lines": [line]}


# The key of a placement: the same in Python and in the page (A7).


def test_the_key_of_a_placement_is_its_lines_and_word_times_in_whole_milliseconds() -> None:
    data = hand(SUNG[:2])
    same = json.loads(json.dumps(data))
    same["lines"][0]["words"][0]["start"] += 0.0001  # under half a millisecond: the same placement
    assert lyrics.words_key(data) == lyrics.words_key(same)
    moved = json.loads(json.dumps(data))
    moved["lines"][1]["words"][2]["start"] += 0.02
    assert lyrics.words_key(moved) != lyrics.words_key(data)
    other = json.loads(json.dumps(data))
    other["lines"][0]["text"] = other["lines"][0]["text"].upper()
    assert lyrics.words_key(other) != lyrics.words_key(data)


def test_half_a_millisecond_goes_up_as_the_page_rounds_it() -> None:
    # 1.0625 s is exact in binary: floor(1062.5 + 0.5) = 1063 in both languages, where round() would say 1062.
    def at(t: float) -> str:
        return lyrics.words_key({"lines": [{"text": "x", "words": [{"text": "x", "start": t, "end": 2.0}]}]})

    assert at(1.0625) == at(1.063) != at(1.062)


def test_the_key_holds_accents_apostrophes_and_words_without_a_time() -> None:
    data = {
        "lines": [
            {"text": "Je ne fait pourtant de tort à personne", "words": [{"text": "Je", "start": 17.72, "end": 18.0}]},
            {"text": "Le jour du 14 juillet", "words": [{"text": "14", "start": None, "end": None}]},
            {"text": "Qu\u2019je m\u2019démène", "words": [{"text": "Qu\u2019je", "start": 3.5, "end": 3.9}]},
        ]
    }
    key = lyrics.words_key(data)
    assert key == fnv1a(
        '[["Je ne fait pourtant de tort à personne",[17720]],["Le jour du 14 juillet",[null]],'
        '["Qu\u2019je m\u2019démène",[3500]]]'
    )


def test_the_same_words_placed_again_on_the_same_voice_keep_their_key() -> None:
    v = voice(SUNG, LENGTH)
    assert lyrics.words_key(lyrics.place("\n".join(LINES), v, CHART)) == lyrics.words_key(
        lyrics.place("\n".join(LINES), v, CHART)
    )


# One line placed again in its own window (A1, A2, A5).


def test_only_the_fixed_line_is_placed_again_in_its_own_window(monkeypatch: pytest.MonkeyPatch) -> None:
    v = voice(SUNG, LENGTH)
    pasted = [*LINES]
    pasted[1] = "the radio hums what the knight forgot"  # a typo in the paste
    data = lyrics.place("\n".join(pasted), v, CHART)
    seen: list[int] = []
    align = lyrics.ctc_align

    def spy(log_probs: Any, tokens: Any, blank: int) -> Any:
        seen.append(log_probs.shape[0])
        return align(log_probs, tokens, blank)

    monkeypatch.setattr(lyrics, "ctc_align", spy)
    line = lyrics.place_line(v, data["lines"], 1, LINES[1], CHART)
    a, b = lyrics.line_window(data["lines"], 1, data["lines"][1], CHART, v.emission.shape[0], False)
    assert seen == [b - a]  # one alignment, over the line's window only
    truth = starts_sung(*SUNG[1])
    assert [w["text"] for w in line["words"]] == LINES[1].split()
    assert all(abs(w["start"] - t) <= 2 * F + 1e-9 for w, t in zip(line["words"], truth, strict=True))
    fixed = lyrics.apply_edits(data, {"1": entry(data, 1, line)})
    assert [fixed["lines"][j] for j in (0, 2, 3)] == [data["lines"][j] for j in (0, 2, 3)]  # nothing else moves
    assert fixed["lines"][1]["text"] == LINES[1] and fixed["lines"][1]["edited"] is True


def test_the_window_of_a_line() -> None:
    data = hand([("morning comes in", 2.0, 6.0), ("hold on to the light", 10.0, 14.0), ("we are here", 20.0, 22.0)])
    lines, own = data["lines"], data["lines"][1]
    frames = int(LENGTH / F)
    # Its own start less 0.3 s (a bar when the first word changed), its end plus a bar.
    assert lyrics.line_window(lines, 1, own, CHART, frames, False) == (round(9.7 / F), round(16.0 / F))
    assert lyrics.line_window(lines, 1, own, CHART, frames, True) == (round((10.0 - BAR) / F), round(16.0 / F))
    # Never over the lines around it.
    close = hand([("morning comes in", 2.0, 9.9), ("hold on to the light", 10.0, 14.0), ("we are here", 15.0, 17.0)])
    assert lyrics.line_window(close["lines"], 1, close["lines"][1], CHART, frames, True) == (
        round(9.9 / F),
        round(15.0 / F),
    )
    # A line not sung there (taken out of the sheet) leaves its time to the line beside it.
    close["lines"][0]["sung"] = False
    assert lyrics.line_window(close["lines"], 1, close["lines"][1], CHART, frames, True)[0] == round(8.0 / F)


def test_a_backing_word_before_an_anchored_line_does_not_pull_it() -> None:
    sung = [("morning comes in on the harbour road", 1.0, 5.0), ("hold on to the northern light", 10.0, 14.0)]
    data = hand(sung)
    v = voice([*sung, ("holdon", 8.3, 8.9)], LENGTH)  # "hold on" sung by a backing voice 1.7 s before
    # The lead's "hold on" is barely heard (backing vocals over it): the backing one is clearer.
    for f in range(int(10.0 / F), int(11.0 / F)):
        v.emission[f, 2:] = np.where(v.emission[f, 2:] == 0.0, -4.0, -8.0)
        v.emission[f, LABELS.index("-")] = 0.0
    line = lyrics.place_line(v, data["lines"], 1, "hold on to the northern lights", CHART)
    assert abs(line["words"][0]["start"] - 10.0) < 0.35  # within the 0.3 s before the line, not at 8.3 s


def test_a_line_heard_as_written_loses_its_check_another_text_gets_one() -> None:
    v = voice(SUNG, LENGTH)
    data = hand(SUNG, check="placed by the order of the text: listen to it")
    assert lyrics.place_line(v, data["lines"], 1, LINES[1].capitalize() + ".", CHART)["check"] is None
    other = lyrics.place_line(v, data["lines"], 1, "the river runs where the morning goes", CHART)
    assert other["check"] == lyrics.LINE_CHECK == "placed in this line's time: listen to it"


def test_a_short_line_keeps_the_placements_check_when_nothing_moved() -> None:
    sung = [("morning comes in on the harbour road", 1.0, 5.0), ("hold on", 6.0, 7.0), ("we are here", 9.0, 10.5)]
    v = voice(sung, LENGTH)
    for check in (None, "placed by the order of the text: listen to it"):
        data = hand(sung, check=check)
        assert lyrics.place_line(v, data["lines"], 1, "Hold on!", CHART)["check"] == check  # under 15 letters
    data = hand(sung)
    moved = lyrics.place_line(v, data["lines"], 1, "hold on a while", CHART)  # words that moved: listen to it
    assert moved["check"] == lyrics.LINE_CHECK


def test_a_number_is_kept_without_a_time_and_elisions_as_typed() -> None:
    sung = [("le jour du juillet", 2.0, 4.0), ("je suis la", 5.0, 6.5)]
    v = voice(sung, LENGTH)
    data = hand(sung)
    line = lyrics.place_line(v, data["lines"], 0, "Le jour du 14 juillet", CHART)
    assert [(w["text"], w["start"] is None) for w in line["words"]] == [
        ("Le", False),
        ("jour", False),
        ("du", False),
        ("14", True),
        ("juillet", False),
    ]
    line = lyrics.place_line(v, data["lines"], 1, "J'suis là", CHART)
    assert [w["text"] for w in line["words"]] == ["J'suis", "là"]


def test_backing_vocals_in_brackets_stay_apart() -> None:
    v = voice(SUNG, LENGTH)
    data = hand(SUNG)
    line = lyrics.place_line(v, data["lines"], 1, "the radio hums (radio hums) what the night forgot", CHART)
    assert line["backing"] == ["radio hums"] and len(line["words"]) == 7


def test_no_room_for_the_words_says_between_when() -> None:
    sung = [("morning comes in", 2.0, 9.9), ("abc", 10.0, 10.5), ("we are here", 10.6, 12.0)]
    v = voice(sung, LENGTH)
    with pytest.raises(lyrics.NoRoom) as caught:
        lyrics.place_line(v, hand(sung)["lines"], 1, "a much longer line that cannot be sung there at all", CHART)
    assert caught.value.start == pytest.approx(9.9) and caught.value.end == pytest.approx(10.6)
    assert "between 0:09 and 0:10" in str(caught.value)


@pytest.mark.parametrize("text", ["мир", "", "   ", "G D Em"])
def test_a_line_with_nothing_the_voice_can_sing_is_refused(text: str) -> None:
    with pytest.raises(ValueError):
        lyrics.line_words(text)


def test_spread_by_syllables_over_the_lines_own_time() -> None:
    data = hand(SUNG)
    line = lyrics.spread_line(data["lines"][1], "the radio hums what the night forgot")
    starts = [w["start"] for w in line["words"]]
    assert starts[0] == SUNG[1][1] and starts == sorted(starts) and line["words"][-1]["end"] == SUNG[1][2]
    # "radio": two syllables (vowel groups), "the": one.
    assert starts[2] - starts[1] == pytest.approx(2 * (starts[1] - starts[0]), abs=0.002)
    assert line["check"] == lyrics.SPREAD_CHECK == "spread over the line's time, not heard: listen to it"


# The words with the fixes applied: one function, for the exports, the stage and the chords (R12).


def test_a_line_not_in_this_recording_leaves_its_chords_to_the_placement_rule() -> None:
    data = hand(SUNG)
    gone = lyrics.apply_edits(data, {"1": {"was": LINES[1], "gone": "not-sung"}})
    assert gone["lines"][1]["sung"] is False and gone["lines"][1]["edited"] == "not-sung"
    words = {
        li: [(w["start"], w["end"]) for w in ln["words"]] for li, ln in enumerate(gone["lines"]) if ln["sung"]
    }  # as the exports read them
    placed = lyrics.place_chords(lyrics.chord_changes(CHART), words, 120.0, 4)
    assert all(p["line"] != 1 for p in placed)
    other = lyrics.apply_edits(data, {"2": {"was": LINES[2], "voice": "other"}})
    assert other["lines"][2]["voice"] == "other" and other["lines"][2]["sung"] is True
    assert lyrics.apply_edits(data, {"9": {"was": "x", "gone": "not-sung"}})["lines"] == data["lines"]


# Carrying the fixes over a new placement (A8).


def carried(old_lines: list[str], new_lines: list[str], fixes: dict[str, dict[str, Any]]) -> tuple[Any, int]:
    sung_old = [(t, 1.0 + 5 * k, 5.0 + 5 * k) for k, t in enumerate(old_lines)]
    sung_new = [(t, 1.0 + 5 * k, 5.0 + 5 * k) for k, t in enumerate(new_lines)]
    return lyrics.carry_edits(hand(sung_old), hand(sung_new), fixes, voice(sung_new, 40.0), CHART)


def a_fix(i: int, text: str, was: str) -> dict[str, dict[str, Any]]:
    return {str(i): {"was": was, "lines": [{"text": text, "backing": [], "words": [], "check": None}]}}


def test_a_new_placement_of_the_same_text_keeps_the_fixes() -> None:
    entries, left = carried(LINES, LINES, a_fix(1, "the radio hums what the knight forgot", LINES[1]))
    assert left == 0 and set(entries) == {"1"}
    assert [w["text"] for w in entries["1"]["lines"][0]["words"]][-2] == "knight"  # placed again: words in time
    assert all(w["start"] is not None for w in entries["1"]["lines"][0]["words"])


def test_a_fix_follows_its_line_not_its_index() -> None:
    new = [LINES[0], "a line pasted in between", *LINES[1:]]
    entries, left = carried(LINES, new, a_fix(1, "the radio hums what the knight forgot", LINES[1]))
    assert left == 0 and set(entries) == {"2"} and entries["2"]["was"] == LINES[1]


def test_a_fix_whose_line_changed_in_the_text_is_left_out() -> None:
    new = [*LINES]
    new[1] = "the radio sings what the night forgot"
    entries, left = carried(LINES, new, a_fix(1, "the radio hums what the knight forgot", LINES[1]))
    assert entries == {} and left == 1


def test_a_fix_the_paste_already_has_is_dropped_quietly() -> None:
    new = [*LINES]
    new[1] = "the radio hums what the knight forgot"
    entries, left = carried(LINES, new, a_fix(1, "the radio hums what the knight forgot", LINES[1]))
    assert entries == {} and left == 0


def test_lines_sung_twice_are_told_apart_by_their_occurrence() -> None:
    old = [LINES[0], LINES[2], LINES[1], LINES[2]]
    new = [LINES[0], LINES[1], LINES[2], LINES[1], LINES[2]]
    gone = {"3": {"was": LINES[2], "gone": "not-sung"}}  # the second chorus line, not in this recording
    entries, left = carried(old, new, gone)
    assert left == 0 and entries == {"4": {"was": LINES[2], "gone": "not-sung"}}


# The voice heard before, from the cache only (B4): every gap falls back, the model never runs.


def write_flac(path: Path, spans: list[tuple[float, float]], length: float = LENGTH) -> None:
    import soundfile

    sr = 16000
    wave = np.zeros(int(length * sr), np.float32)
    rng = np.random.default_rng(3)
    for a, b in spans:
        wave[int(a * sr) : int(b * sr)] = 0.3 * rng.standard_normal(int(b * sr) - int(a * sr))
    path.parent.mkdir(parents=True, exist_ok=True)
    soundfile.write(path, wave, sr, format="FLAC")


def write_npz(folder: Path, v: lyrics.Voice) -> None:
    np.savez_compressed(folder / lyrics.CACHE, emission=v.emission.astype(np.float16), labels=np.array(v.labels))


def test_the_cached_voice_is_read_and_every_gap_is_none(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def never(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("the speech model must not run for a line")

    monkeypatch.setattr(lyrics, "_run_model", never)
    folder = tmp_path / "stems"
    assert lyrics.cached_voice(folder) is None  # nothing at all
    write_flac(folder / "vocals.flac", [(t[1], t[2]) for t in SUNG])
    assert lyrics.cached_voice(folder) is None  # no emission
    (folder / lyrics.CACHE).write_bytes(b"PK\x03\x04 damaged")
    assert lyrics.cached_voice(folder) is None
    write_npz(folder, voice(SUNG, LENGTH))
    got = lyrics.cached_voice(folder)
    assert got is not None and got.labels == LABELS and got.sung[int(3.0 / F)] and not got.sung[int(0.2 / F)]
    (folder / "vocals.flac").unlink()
    assert lyrics.cached_voice(folder) is None


# The library: the store, the API, sharing (A3, A4, A6, B2, B3).


def write_page(page: Path, data: dict[str, Any], chart: dict[str, Any] = CHART, source: str = "abc") -> None:
    page.mkdir(parents=True, exist_ok=True)
    (page / "index.html").write_text(
        f'<script type="application/json" id="woodshed-data">{build.script_json({"song": chart, "view": {}})}</script>'
    )
    summary = {"title": "Song", "key": "G", "bpm": 120, "meter": "4/4", "duration": LENGTH, "doubts": 0, "stems": True}
    manifest = {"settings": {"source": source}, "summary": summary, "complete": True}
    (page / "woodshed.json").write_text(json.dumps(manifest))
    lyrics.write(page, data)


@pytest.fixture
def library(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[app.AppServer]:
    """A library with one page whose words are placed, its voice in the cache (WOODSHED_CACHE)."""
    monkeypatch.setenv("WOODSHED_CACHE", str(tmp_path / "cache"))

    def never(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("the speech model must not run for a line")

    monkeypatch.setattr(lyrics, "_run_model", never)
    lib = app.Library(tmp_path / "library", Options(use_stems=False, open_page=False))
    write_page(lib.root / PAGE, hand(SUNG, check="placed by the order of the text: listen to it"))
    cache = stems.folder_of("abc", stems.model_of({}))
    write_flac(cache / "vocals.flac", [(t[1], t[2]) for t in SUNG])
    write_npz(cache, voice(SUNG, LENGTH))
    srv = app.AppServer(lib)
    threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()  # a quick shutdown
    yield srv
    srv.shutdown()
    srv.server_close()


def placement(srv: app.AppServer) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((srv.library.root / PAGE / lyrics.LYRICS).read_text(encoding="utf-8"))
    return data


def fix(srv: app.AppServer, lines: dict[str, Any], key: str | None = None, **extra: Any) -> tuple[int, Any]:
    body = {"page": PAGE, "key": key or lyrics.words_key(placement(srv)), "lines": lines, **extra}
    return post(srv, "/api/words", body)


def read(srv: app.AppServer, key: str | None = None) -> dict[str, Any]:
    key = key or lyrics.words_key(placement(srv))
    got: dict[str, Any] = json.loads(request(srv, "GET", f"/api/corrections?page={PAGE}&key=a1b2c3&words={key}")[2])
    return got


def stored(srv: app.AppServer) -> dict[str, Any]:
    path = srv.library.root / app.CORRECTIONS_DIR / f"{PAGE}.json"
    out: dict[str, Any] = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    return out


def test_a_line_fixed_is_placed_again_kept_and_told_to_the_band(library: app.AppServer) -> None:
    before = library.live.fixes.get(PAGE, 0)
    status, answer = fix(library, {"1": {"text": "The radio hums what the night forgot!"}})
    assert status == 200, answer
    line = answer["lines"]["1"]["lines"][0]
    assert answer["lines"]["1"]["was"] == LINES[1] and line["text"] == "The radio hums what the night forgot!"
    assert line["check"] is None  # heard as written: no longer to check
    truth = starts_sung(*SUNG[1])
    assert all(abs(w["start"] - t) <= 2 * F + 1e-9 for w, t in zip(line["words"], truth, strict=True))
    assert answer["rev"] > 0 and library.live.fixes[PAGE] > before  # every device reads it again
    got = read(library)["words"]
    assert got == {"lines": answer["lines"], "removed": {}}
    assert placement(library)["lines"][1]["text"] == LINES[1]  # the placement itself is untouched


def test_fixes_merge_line_by_line_and_a_take_back_is_remembered(library: app.AppServer) -> None:
    fix(library, {"1": {"text": "the radio hums what the knight forgot"}})
    _, answer = fix(library, {"2": {"gone": "not-sung"}, "3": {"text": LINES[3], "voice": "other"}})
    assert set(answer["lines"]) == {"1", "2", "3"}
    assert answer["lines"]["2"] == {"was": LINES[2], "gone": "not-sung"}
    assert answer["lines"]["3"] == {"was": LINES[3], "voice": "other"}  # the same words, another voice
    was = answer["lines"]["1"]
    rev = answer["rev"]
    _, answer = fix(library, {"1": None})
    assert "1" not in answer["lines"] and answer["removed"] == {"1": was} and answer["rev"] == rev + 1
    _, answer = fix(library, {"2": {"text": LINES[2]}})  # its own words again: the placement's
    assert "2" not in answer["lines"] and answer["removed"]["2"] == {"was": LINES[2], "gone": "not-sung"}


def test_no_room_is_refused_and_nothing_is_written(library: app.AppServer) -> None:
    sung = [("morning comes in", 2.0, 9.9), ("abc", 10.0, 10.5), ("we are here", 10.6, 12.0)]
    write_page(library.library.root / PAGE, hand(sung))
    fix(library, {"0": {"text": "morning comes in", "voice": "other"}})
    before = stored(library)
    status, answer = fix(library, {"1": {"text": "a much longer line that cannot be sung there at all"}})
    assert status == 409 and "between 0:09 and 0:10" in answer["error"]
    assert answer["window"] == [pytest.approx(9.9), pytest.approx(10.6)]
    assert stored(library) == before  # the file and its revision as they were


@pytest.mark.parametrize("gap", ["no emission", "damaged emission", "no voice track"])
def test_without_the_voice_heard_before_the_words_are_spread(library: app.AppServer, gap: str) -> None:
    cache = stems.folder_of("abc", stems.model_of({}))
    if gap == "no emission":
        (cache / lyrics.CACHE).unlink()
    elif gap == "damaged emission":
        (cache / lyrics.CACHE).write_bytes(b"not a zip")
    else:
        (cache / "vocals.flac").unlink()
    status, answer = fix(library, {"1": {"text": "the radio hums what the knight forgot"}})
    assert status == 200, answer  # the model is never run for a line (it raises here)
    line = answer["lines"]["1"]["lines"][0]
    assert line["check"] == lyrics.SPREAD_CHECK
    assert line["words"][0]["start"] == SUNG[1][1] and line["words"][-1]["end"] == SUNG[1][2]


def test_a_stale_placement_is_refused(library: app.AppServer) -> None:
    status, answer = fix(library, {"1": {"text": "x y z"}}, key="0123abcd")
    assert status == 409 and answer["error"] == "the words were placed again: reload the page"
    assert stored(library) == {}


def test_the_token_is_needed_but_not_the_right_to_add_songs(
    library: app.AppServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    body = {"page": PAGE, "key": lyrics.words_key(placement(library)), "lines": {"1": {"text": "x y z"}}}
    assert post(library, "/api/words", body, token="wrong")[0] == 403
    monkeypatch.setattr(app.Handler, "_may_upload", lambda self: False)  # a phone of the band
    status, answer = fix(library, {"1": {"text": "the radio hums what the knight forgot"}})
    assert status == 200, answer  # milliseconds, not the speech model: any device of the band may fix a line


@pytest.mark.parametrize(
    "lines",
    [
        {"4": {"text": "a line"}},  # past the last line
        {"01": {"text": "a line"}},  # one spelling an index
        {"1": {"text": "a" * 201}},  # 200 characters at most
        {"1": {"text": "a\nb\nc\nd\ne"}},  # a line split in four at most
        {"1": {"text": "мир"}},  # letters the speech model cannot hear
        {"1": {"text": " ".join(["la"] * 41)}},  # 40 words at most
        {"1": {"text": "a line", "voice": "lead"}},
        {"1": {"gone": "joined"}},
        {"1": {"text": "a line", "start": 3.0}},  # the library computes every time
        {"1": "a line"},
        {},
        {str(k): None for k in range(501)},
    ],
)
def test_what_a_page_cannot_ask_is_refused(library: app.AppServer, lines: dict[str, Any]) -> None:
    status, _ = fix(library, lines)
    assert status == 400
    assert stored(library) == {}


def test_a_body_over_the_corrections_limit_is_refused(library: app.AppServer) -> None:
    status, _ = fix(library, {"1": {"text": "x"}}, pad="x" * app.CORRECTIONS_BYTES)
    assert status == 413


def test_a_chord_saved_after_a_line_keeps_the_words(library: app.AppServer) -> None:
    _, answer = fix(library, {"1": {"text": "the radio hums what the knight forgot"}})
    post(library, "/api/corrections", {"page": PAGE, "key": "a1b2c3", "fixes": {"3": [9, "m"]}})
    post(library, "/api/edits", {"page": PAGE, "key": "b1e2a3", "bars": {"4": {"chords": [[4, "G"]], "t": 1}}})
    post(library, "/api/band", {"page": PAGE, "transpose": 2, "key": "A"})
    assert read(library)["words"]["lines"] == answer["lines"]
    assert stored(library)["words"]  # in the file, beside the chords


def test_two_devices_fixing_lines_side_by_side_both_keep_theirs(
    library: app.AppServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    voice_of = app.Library._voice
    both = threading.Barrier(2)

    def slow(self: app.Library, folder: str) -> lyrics.Voice | None:
        got = voice_of(self, folder)
        with contextlib.suppress(threading.BrokenBarrierError):
            both.wait(5)  # decoded at once, outside the lock
        return got

    monkeypatch.setattr(app.Library, "_voice", slow)
    answers: list[Any] = []

    def go(i: int, text: str) -> None:
        answers.append(fix(library, {str(i): {"text": text}}))

    threads = [
        threading.Thread(target=go, args=(1, "the radio hums what the knight forgot")),
        threading.Thread(target=go, args=(2, "hold on hold on to the northern lights")),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(20)
    assert sorted(status for status, _ in answers) == [200, 200]
    assert sorted(a["rev"] for _, a in answers) == [1, 2]
    assert set(read(library)["words"]["lines"]) == {"1", "2"}


def test_the_voice_of_two_pages_at_most_is_kept(library: app.AppServer) -> None:
    lib = library.library
    assert lib._voice(PAGE) is not None and lib._voice(PAGE) is lib._voice(PAGE)  # decoded once
    for name in ("B.woodshed", "C.woodshed"):
        write_page(lib.root / name, hand(SUNG))
        lib._voice(name)
    assert len(lib.voices) == 2 and PAGE not in lib.voices


# A new placement carries the fixes; a rebuild keeps them (A8, A9).


def test_placing_the_words_again_carries_the_fixes(library: app.AppServer, monkeypatch: pytest.MonkeyPatch) -> None:
    fix(library, {"1": {"text": "the radio hums what the knight forgot"}, "2": {"gone": "not-sung"}})
    fix(library, {"3": {"text": "we are only halfway through the nights"}})
    old_key = lyrics.words_key(placement(library))
    v = voice([(t, 1.0 + 5 * k, 5.0 + 5 * k) for k, t in enumerate(["a new first line", *LINES])], 40.0)
    monkeypatch.setattr(lyrics, "listen", lambda *args, **kwargs: v)
    monkeypatch.setattr(lyrics, "page_song", lambda page: CHART)
    text = "\n".join(["a new first line", LINES[0], LINES[1], LINES[2], "we are only halfway through it all"])
    job = app.Job("j", PAGE, page=PAGE, kind="words")
    monkeypatch.setattr(library.library.queue, "task_done", lambda: None)  # run here, not by the worker
    library.library._place_words(job, library.library.root / PAGE, text, library.library.opts)
    assert job.status == "done", job.message
    new_key = lyrics.words_key(placement(library))
    assert new_key != old_key
    got = read(library, new_key)["words"]["lines"]
    assert set(got) == {"2", "3"} and got["3"] == {"was": LINES[2], "gone": "not-sung"}  # each follows its line
    assert got["2"]["lines"][0]["text"] == "the radio hums what the knight forgot"
    assert "1 line fixed on the sheet was left out: its text changed." in job.notes
    assert read(library, old_key)["words"]["lines"]  # the old placement's fixes are kept a while


def test_a_rebuild_of_the_page_keeps_the_key_and_the_fixes(
    library: app.AppServer, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(stems, "fingerprint", lambda path: "abc")  # rebuilt from the same recording
    _, answer = fix(library, {"1": {"text": "the radio hums what the knight forgot"}})
    old = library.library.root / PAGE
    key = lyrics.words_key(placement(library))
    new = tmp_path / "rebuilt"
    new.mkdir()
    (new / "exports").mkdir()
    build._keep_lyrics(old, new, CHART, old / "index.html")
    rebuilt = json.loads((new / lyrics.LYRICS).read_text(encoding="utf-8"))
    assert lyrics.words_key(rebuilt) == key
    assert read(library, key)["words"]["lines"] == answer["lines"]


def test_an_older_woodshed_file_without_words_reads_as_none(library: app.AppServer) -> None:
    post(library, "/api/corrections", {"page": PAGE, "key": "a1b2c3", "fixes": {"3": [9, "m"]}})
    assert read(library)["words"] == {"lines": {}, "removed": {}}
    path = library.library.root / app.CORRECTIONS_DIR / f"{PAGE}.json"
    body = json.loads(path.read_text(encoding="utf-8"))
    body["words"] = {lyrics.words_key(placement(library)): {"lines": {"1": {"was": 3}}, "removed": {}, "at": 1}}
    path.write_text(json.dumps(body))
    assert read(library)["words"] == {"lines": {}, "removed": {}}  # damaged by hand: skipped


def place_again(srv: app.AppServer, monkeypatch: pytest.MonkeyPatch, text_lines: list[str]) -> tuple[app.Job, str]:
    """The words placed again from the library, on a voice that sings `text_lines`."""
    v = voice([(t, 1.0 + 5 * k, 5.0 + 5 * k) for k, t in enumerate(text_lines)], 40.0)
    monkeypatch.setattr(lyrics, "listen", lambda *args, **kwargs: v)
    monkeypatch.setattr(lyrics, "page_song", lambda page: CHART)
    monkeypatch.setattr(srv.library.queue, "task_done", lambda: None)
    job = app.Job("j", PAGE, page=PAGE, kind="words")
    srv.library._place_words(job, srv.library.root / PAGE, "\n".join(text_lines), srv.library.opts)
    return job, lyrics.words_key(lyrics.place("\n".join(text_lines), v, CHART))


def test_fixes_made_on_the_new_placement_already_win(library: app.AppServer, monkeypatch: pytest.MonkeyPatch) -> None:
    fix(library, {"1": {"text": "the radio hums what the knight forgot"}})
    new = ["a new first line", *LINES]
    v = voice([(t, 1.0 + 5 * k, 5.0 + 5 * k) for k, t in enumerate(new)], 40.0)
    key = lyrics.words_key(lyrics.place("\n".join(new), v, CHART))
    path = library.library.root / app.CORRECTIONS_DIR / f"{PAGE}.json"
    body = json.loads(path.read_text(encoding="utf-8"))
    mine = {"was": LINES[1], "voice": "other"}  # made on that placement before (it was the page's once)
    body["words"][key] = {"lines": {"2": mine}, "removed": {}, "at": 1.0}
    path.write_text(json.dumps(body), encoding="utf-8")
    job, new_key = place_again(library, monkeypatch, new)
    assert job.status == "done" and new_key == key
    assert read(library, key)["words"]["lines"]["2"] == mine


def test_a_crash_while_carrying_leaves_the_words_and_the_fixes_as_they_were(
    library: app.AppServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, answer = fix(library, {"1": {"text": "the radio hums what the knight forgot"}})
    before = placement(library)

    def broken(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("a bug")

    monkeypatch.setattr(lyrics, "carry_edits", broken)
    job, _ = place_again(library, monkeypatch, ["a new first line", *LINES])
    assert job.status == "failed"
    assert placement(library) == before  # the words as they were, so the fixes still show
    assert read(library)["words"]["lines"] == answer["lines"]


def test_the_lyrics_command_carries_the_fixes_of_the_library(
    library: app.AppServer, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    fix(library, {"1": {"text": "the radio hums what the knight forgot"}})
    fix(library, {"3": {"text": "we are only halfway through the nights"}})
    new = ["a new first line", LINES[0], LINES[1], LINES[2], "we are only halfway through it all"]
    v = voice([(t, 1.0 + 5 * k, 5.0 + 5 * k) for k, t in enumerate(new)], 40.0)
    monkeypatch.setattr(lyrics, "listen", lambda *args, **kwargs: v)
    monkeypatch.setattr(lyrics, "page_song", lambda page: CHART)
    words = tmp_path / "words.txt"
    words.write_text("\n".join(new), encoding="utf-8")
    assert cli.main(["lyrics", str(library.library.root / PAGE), str(words)]) == 0
    assert "1 line fixed on the sheet was left out: its text changed." in capsys.readouterr().out
    got = read(library)["words"]["lines"]  # under the new placement's key
    assert set(got) == {"2"} and got["2"]["lines"][0]["text"] == "the radio hums what the knight forgot"


def test_an_undo_does_not_take_back_another_devices_fix(library: app.AppServer) -> None:
    _, mine = fix(library, {"1": {"text": "the radio hums what the knight forgot"}})
    ours = mine["lines"]["1"]
    _, theirs = fix(library, {"1": {"text": "the radio hums what the night forgets"}})  # another device
    before = stored(library)
    status, answer = fix(library, {"1": None}, expect={"1": ours})  # this device's Undo
    assert status == 409 and answer["error"] == "the line changed on another device" and answer["changed"] == ["1"]
    assert stored(library) == before
    status, answer = fix(library, {"1": None}, expect={"1": theirs["lines"]["1"]})
    assert status == 200 and "1" not in answer["lines"]
    status, _ = fix(library, {"2": {"gone": "not-sung"}}, expect={"2": None})  # nothing there yet: as expected
    assert status == 200


def test_a_section_from_a_newer_woodshed_is_kept_by_every_write(library: app.AppServer) -> None:
    path = library.library.root / app.CORRECTIONS_DIR / f"{PAGE}.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps({"rev": 3, "future": {"kept": [1, 2]}}), encoding="utf-8")
    post(library, "/api/corrections", {"page": PAGE, "key": "a1b2c3", "fixes": {"3": [9, "m"]}})
    fix(library, {"1": {"text": "the radio hums what the knight forgot"}})
    assert stored(library)["future"] == {"kept": [1, 2]}


# The library and the command line on one library (the review of the second version): one writer at a time.


def cli_commit_setup(library: app.AppServer, monkeypatch: pytest.MonkeyPatch) -> tuple[Any, dict[str, Any], Any]:
    """The command line's commit for a new placement of the page (a line added first), and that voice."""
    new = ["a new first line", *LINES]
    v = voice([(t, 1.0 + 5 * k, 5.0 + 5 * k) for k, t in enumerate(new)], 40.0)
    monkeypatch.setattr(lyrics, "page_song", lambda page: CHART)
    data = lyrics.place("\n".join(new), v, CHART)
    notes: list[str] = []
    return app.lyrics_commit(library.library.root / PAGE, notes), data, v


def test_the_command_line_waits_for_the_app_and_keeps_its_fix(
    library: app.AppServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    fix(library, {"1": {"text": "the radio hums what the knight forgot"}})
    commit, data, v = cli_commit_setup(library, monkeypatch)
    place = lyrics.place_pieces
    inside = threading.Event()

    def slow(*args: Any, **kwargs: Any) -> Any:
        inside.set()
        time.sleep(1.0)  # the app holds the corrections while it places a line from a phone
        return place(*args, **kwargs)

    monkeypatch.setattr(lyrics, "place_pieces", slow)
    phone = threading.Thread(target=lambda: fix(library, {"2": {"text": "hold on hold on to the northern lights"}}))
    phone.start()
    assert inside.wait(5)
    monkeypatch.setattr(lyrics, "place_pieces", place)
    started = time.monotonic()
    commit(data, v)  # the command line places the words again meanwhile
    waited = time.monotonic() - started
    phone.join(10)
    assert waited > 0.5  # it waited for the app's write
    got = read(library, lyrics.words_key(data))["words"]["lines"]
    assert set(got) == {"2", "3"}  # both fixes carried: the phone's is not lost
    assert got["3"]["lines"][0]["text"] == "hold on hold on to the northern lights"


def test_the_app_waits_for_the_command_line_and_keeps_its_write(
    library: app.AppServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    fix(library, {"1": {"text": "the radio hums what the knight forgot"}})
    commit, data, v = cli_commit_setup(library, monkeypatch)
    carry = lyrics.carry_edits
    inside = threading.Event()

    def slow(*args: Any, **kwargs: Any) -> Any:
        inside.set()
        time.sleep(1.0)  # the command line holds the corrections while it carries
        return carry(*args, **kwargs)

    monkeypatch.setattr(lyrics, "carry_edits", slow)
    cli_thread = threading.Thread(target=commit, args=(data, v))
    cli_thread.start()
    assert inside.wait(5)
    started = time.monotonic()
    status, _ = post(library, "/api/corrections", {"page": PAGE, "key": "a1b2c3", "fixes": {"3": [9, "m"]}})
    waited = time.monotonic() - started
    cli_thread.join(10)
    assert status == 200 and waited > 0.5
    body = stored(library)
    assert body["by_key"]["a1b2c3"]["fixes"] == {"3": [9, "m"]}  # the chord picked meanwhile
    assert lyrics.words_key(data) in body["words"]  # and the fixes carried by the command line


def test_a_write_that_cannot_get_the_corrections_says_so(
    library: app.AppServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(corrections, "LOCK_WAIT", 0.3)
    path = library.library.root / app.CORRECTIONS_DIR / f"{PAGE}.json"
    held, done = threading.Event(), threading.Event()

    def hold() -> None:
        with app.corrections_lock(path):
            held.set()
            done.wait(5)

    t = threading.Thread(target=hold)
    t.start()
    assert held.wait(5)
    try:
        status, answer = post(library, "/api/corrections", {"page": PAGE, "key": "a1b2c3", "fixes": {"3": [9, "m"]}})
    finally:
        done.set()
        t.join(5)
    assert status == 409 and answer["error"] == "another woodshed is writing the corrections of this song: try again"


def test_a_known_section_in_a_shape_this_version_cannot_read_is_kept(library: app.AppServer) -> None:
    path = library.library.root / app.CORRECTIONS_DIR / f"{PAGE}.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps({"rev": 1, "edits": ["a", "list"], "band": {"transpose": 99}}), encoding="utf-8")
    post(library, "/api/corrections", {"page": PAGE, "key": "a1b2c3", "fixes": {"3": [9, "m"]}})
    body = stored(library)
    assert body["edits"] == ["a", "list"] and body["band"] == {"transpose": 99}


def test_a_crash_while_the_command_line_carries_leaves_everything_as_it_was(
    library: app.AppServer, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _, answer = fix(library, {"1": {"text": "the radio hums what the knight forgot"}})
    before = placement(library)
    new = ["a new first line", *LINES]
    v = voice([(t, 1.0 + 5 * k, 5.0 + 5 * k) for k, t in enumerate(new)], 40.0)
    monkeypatch.setattr(lyrics, "listen", lambda *args, **kwargs: v)
    monkeypatch.setattr(lyrics, "page_song", lambda page: CHART)

    def broken(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("a bug")

    monkeypatch.setattr(app, "carry_fixes", broken)
    words = tmp_path / "words.txt"
    words.write_text("\n".join(new), encoding="utf-8")
    with pytest.raises(RuntimeError):  # a bug in the command line shows its traceback
        cli.main(["lyrics", str(library.library.root / PAGE), str(words)])
    assert placement(library) == before
    assert read(library)["words"]["lines"] == answer["lines"]
