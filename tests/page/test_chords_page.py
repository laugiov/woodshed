"""Typed chords in the page: the same grammar as woodshed/chords.py, names and numerals with the bass."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from woodshed import chords, theory

CASES: list[list[Any]] = json.loads((Path(__file__).parents[1] / "chord_cases.json").read_text(encoding="utf-8"))


def test_the_page_reads_every_case_as_python_does(open_page: Any) -> None:
    o = open_page("pop")
    got = o.js(f"{json.dumps([c[0] for c in CASES])}.map((t) => Woodshed.chords.parse(t))")
    for (text, expected), page in zip(CASES, got, strict=True):
        if expected == "none":
            assert page == {"pc": -1, "quality": "", "bass": None}, text
        elif "refused" in expected:
            refusal = chords.parse(text)
            assert isinstance(refusal, chords.Refusal)
            assert page == {"refused": expected["refused"], "hint": refusal.hint}, text
        else:
            assert page == expected, text


def test_typed_chords_are_named_and_numbered_as_the_library_does(open_page: Any) -> None:
    o = open_page("pop")
    data = o.js("Woodshed.current.song")
    key = theory.Key(data["key"]["pc"], "maj" if data["key"]["mode"] == "maj" else "min")
    typed = ["D/F#", "Cmaj7", "Bm7b5", "G7sus4", "Fadd9", "Ebdim7", "C/G", "Aaug", "E5", "Am/G"]
    for text in typed:
        chord = chords.parse(text)
        assert isinstance(chord, chords.Chord)
        for transpose in range(12):  # every key, sharp and flat
            name = o.js(f"Woodshed.current.chordName(Woodshed.chords.parse({json.dumps(text)}), {transpose})")
            assert name == chords.name(chord, key, transpose), (text, transpose)
        numeral = o.js(f"Woodshed.current.roman(Woodshed.chords.parse({json.dumps(text)}))")
        assert numeral == chords.roman(chord, key), text
    # The same chord only with the same bass.
    assert o.js("Woodshed.current.same(Woodshed.chords.parse('D'), Woodshed.chords.parse('D/F#'))") is False
    assert o.js("Woodshed.current.same(Woodshed.chords.parse('D/F#'), Woodshed.chords.parse('D/Gb'))") is True


def test_a_slash_bass_gets_a_real_sharp_or_flat(open_page: Any) -> None:
    o = open_page("pop")
    assert o.js("Woodshed.chordNode('D/F#').textContent") == "D/F♯"
    assert o.js("Woodshed.chordNode('Bb/Ab').querySelectorAll('.acc').length") == 2
    assert o.js("Woodshed.prettyText('Gb/Db')") == "G♭/D♭"
