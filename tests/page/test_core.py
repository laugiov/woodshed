"""The page core (no DOM): song lookups and instrument geometry, against the Python results."""

from __future__ import annotations

from typing import Any

import pytest

from woodshed import theory


def test_the_page_loads_offline_from_disk(open_page: Any) -> None:
    o = open_page("pop")
    assert o.page.title().endswith("· woodshed")


def test_beat_times_follow_the_tracked_beats(open_page: Any) -> None:
    o = open_page("pop")
    data = o.js("Woodshed.current.song")
    times = o.js("Array.from({length: Woodshed.current.totalBeats}, (_, b) => Woodshed.current.beatTime(b))")
    first = data["first_beat"]
    tracked = data["beats"]
    for b, t in enumerate(times):
        if 0 <= first + b < len(tracked):
            assert t == pytest.approx(tracked[first + b])
    # beatAt is the inverse: just after beat b, beat b is playing
    back = o.js(
        "(() => { const s = Woodshed.current;"
        " return Array.from({length: s.totalBeats}, (_, b) => s.beatAt(s.beatTime(b) + 0.01)); })()"
    )
    assert back == list(range(len(back)))


@pytest.mark.parametrize("transpose", [0, 2, 5, 6, 10, -1])
def test_chord_names_are_the_python_spellings(open_page: Any, transpose: int) -> None:
    o = open_page("pop")
    song = o.js("Woodshed.current.song")
    key = theory.Key((song["key"]["pc"] + transpose) % 12, song["key"]["mode"])
    for bar in song["bars"]:
        for c in bar["chords"]:
            if c["pc"] < 0:
                continue
            expected = theory.chord_name((c["pc"] + transpose) % 12, c["quality"], key)
            assert o.js("([c, t]) => Woodshed.current.chordName(c, t)", [c, transpose]) == expected


def test_roman_numerals_and_key_names(open_page: Any) -> None:
    o = open_page("pop")
    assert o.js("Woodshed.current.roman({pc: 9, quality: 'm'})") == "vi"
    assert o.js("Woodshed.current.keyName(0)") == "C" and o.js("Woodshed.current.keyName(7)") == "G"


def test_guitar_shapes_come_from_the_shared_table(open_page: Any) -> None:
    o = open_page("pop")
    shapes = o.js("Woodshed.current.view.shapes")
    assert shapes["open"] == theory.SHAPES["open"]
    assert o.js("Woodshed.instruments.openOrBarre(Woodshed.current.view.shapes, 0, '')")["frets"] == [-1, 3, 2, 0, 1, 0]
    f = o.js("Woodshed.instruments.barreShape(5, '')")  # F: E-shape barre on the first fret
    assert f["frets"] == [1, 3, 3, 2, 1, 1] and f["barre"] == 1
    bm = o.js("Woodshed.instruments.barreShape(11, 'm')")  # Bm: A-shape on the second fret
    assert bm["frets"] == [-1, 2, 4, 4, 3, 2]


def test_funk_triads_contain_the_chord_tones(open_page: Any) -> None:
    o = open_page("pop")
    voicings = o.js(
        "Woodshed.instruments.funkVoicings([{pc: 0, quality: ''}, {pc: 9, quality: 'm'}, {pc: 5, quality: ''}])"
    )
    for name, pcs in (("0", {0, 4, 7}), ("9m", {9, 0, 4}), ("5", {5, 9, 0})):
        frets = voicings[name]["frets"]
        sounded = {(55 + frets[3]) % 12, (59 + frets[4]) % 12, (64 + frets[5]) % 12}
        assert sounded == pcs


def test_counts_follow_the_meter(open_page: Any) -> None:
    o = open_page("pop")
    assert o.js("Woodshed.instruments.counts(3)") == ["1", "e", "&", "a", "2", "e", "&", "a", "3", "e", "&", "a"]
