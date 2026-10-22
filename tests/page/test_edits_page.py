"""Chords typed on a bar (core/edits.js): reading the chart notation and laying it on the beats."""

from __future__ import annotations

import json
from typing import Any

import pytest

PARSE = "(text, per, prev) => Woodshed.edits.parseBar(text, per, prev || null)"


@pytest.mark.parametrize(
    ("text", "per", "expected"),
    [
        ("G", 4, [[4, "G"]]),
        ("G Am", 4, [[2, "G"], [2, "Am"]]),
        ("G Am C", 4, [[2, "G"], [1, "Am"], [1, "C"]]),  # the first chord holds the remainder
        ("G Am", 3, [[2, "G"], [1, "Am"]]),
        ("C D E F", 6, [[2, "C"], [2, "D"], [1, "E"], [1, "F"]]),
        ("D/F# . G .", 4, [[2, "D/F#"], [2, "G"]]),
        ("G / / /", 4, [[4, "G"]]),
        ("G . . Am", 4, [[3, "G"], [1, "Am"]]),
        ("G G Am Am", 4, [[2, "G"], [2, "Am"]]),  # the same chord twice is held
        ("N.C. . G .", 4, [[2, "N.C."], [2, "G"]]),
        ("bb Ebmaj7", 4, [[2, "A#"], [2, "D#maj7"]]),  # stored by sharp names, spelled by the key on screen
        ("  Dsus4  ", 4, [[4, "Dsus4"]]),
    ],
)
def test_a_bar_is_read_as_a_chord_sheet_writes_it(open_page: Any, text: str, per: int, expected: list[Any]) -> None:
    o = open_page("pop")
    assert o.js(f"({PARSE})({json.dumps(text)}, {per})") == {"chords": expected}


@pytest.mark.parametrize(
    ("text", "per", "code", "at"),
    [
        ("", 4, "empty", None),
        ("G Am C D E", 4, "too-many", None),
        ("G . Am", 4, "beats", None),  # with holds, one token a beat
        ("G Xyz", 4, "unknown", 1),
        ("Cmaj . . .", 4, "maj-alone", 0),
        ("G | C", 4, "bar-line", None),
    ],
)
def test_a_bar_that_cannot_be_read_says_why_and_where(open_page: Any, text: str, per: int, code: str, at: Any) -> None:
    o = open_page("pop")
    got = o.js(f"({PARSE})({json.dumps(text)}, {per})")
    assert got["error"] == code and got.get("at") == at


def test_percent_repeats_the_bar_before_and_a_leading_hold_carries_it_on(open_page: Any) -> None:
    o = open_page("pop")
    prev = [[2, "C"], [2, "G"]]
    assert o.js(f"({PARSE})('%', 4, {json.dumps(prev)})") == {"chords": prev}
    assert o.js(f"({PARSE})('. . Am .', 4, {json.dumps(prev)})") == {"chords": [[2, "G"], [2, "Am"]]}
    assert o.js(f"({PARSE})('%', 4, null)")["error"] == "nothing-before"


APPLY = """(edits) => {
  const c = (pc, quality, beats, doubt) => ({pc, quality, beats, doubt: doubt ? {id: doubt, kind: "chord"} : null});
  const bars = [
    {chords: [c(0, "", 4)]},
    {chords: [c(7, "", 2, 3), c(9, "m", 2)]},
    {chords: [c(5, "", 4, 4)]},
  ];
  const out = Woodshed.edits.apply(bars, edits, 1, 4);
  const bass = (x) => (x.bass === undefined ? null : x.bass);
  const row = (x) => [x.beats, x.pc, x.quality, bass(x), x.doubt ? x.doubt.id : null, !!x.typed];
  return out.map((b) => ({edited: !!b.edited, chords: b.chords.map(row)}));
}"""


def test_typed_bars_are_laid_on_their_beats_and_resolve_the_doubts_they_touch(open_page: Any) -> None:
    o = open_page("pop")
    # Bar 1 starts on beat 1 + 4 = 5: D/F# for two beats, then the analysis's Am stays.
    got = o.js(f"({APPLY})({json.dumps({'bars': {'5': {'chords': [[2, 'D/F#']]}}})})")
    assert got[0] == {"edited": False, "chords": [[4, 0, "", None, None, False]]}
    assert got[1] == {"edited": True, "chords": [[2, 2, "", 6, None, True], [2, 9, "m", None, None, False]]}
    assert got[2]["chords"][0][4] == 4  # an untouched doubt stays to check
    # A typed span over a bar line (after the bar lines moved): both bars are edited, the doubt it touches resolved.
    got = o.js(f"({APPLY})({json.dumps({'bars': {'7': {'chords': [[4, 'E']]}}})})")
    assert got[1]["edited"] and got[2]["edited"]
    assert got[1]["chords"] == [[2, 7, "", None, 3, False], [2, 4, "", None, None, True]]
    assert got[2]["chords"] == [[2, 4, "", None, None, True], [2, 5, "", None, None, False]]  # doubt 4 resolved


def test_a_label_that_no_longer_parses_is_left_out(open_page: Any) -> None:
    o = open_page("pop")
    got = o.js(f"({APPLY})({json.dumps({'bars': {'5': {'chords': [[4, 'Hxyz']]}}})})")
    assert got[1]["edited"] is False
