"""Chords a musician types on the chart: the table, the parser, names and roman numerals."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from woodshed import chords, theory

CASES: list[list[Any]] = json.loads((Path(__file__).parent / "chord_cases.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize(("text", "expected"), CASES, ids=[c[0] or "(empty)" for c in CASES])
def test_the_shared_case_table(text: str, expected: Any) -> None:
    got = chords.parse(text)
    if expected == "none":
        assert got == chords.NO_CHORD
    elif "refused" in expected:
        assert isinstance(got, chords.Refusal) and got.code == expected["refused"]
    else:
        assert got == chords.Chord(expected["pc"], expected["quality"], expected["bass"])


def test_every_quality_has_its_intervals_roman_and_exports() -> None:
    for quality, q in chords.QUALITIES.items():
        assert q["intervals"][0] == 0 and q["intervals"] == sorted(set(q["intervals"])), quality
        assert q["musicxml"]["kind"] and q["harte"], quality
        assert chords.parse("C" + quality) == chords.Chord(0, quality, None), quality  # each suffix reads back


def test_the_analysis_qualities_keep_their_names_and_numerals() -> None:
    # The engine writes these four: the table must say exactly what theory says today.
    for key in (theory.Key(0), theory.Key(9, "min"), theory.Key(5), theory.Key(6)):
        for pc in range(12):
            for quality in ("", "m", "7", "m7"):
                chord = chords.Chord(pc, quality, None)
                assert chords.name(chord, key) == theory.chord_name(pc, quality, key)
                assert chords.roman(chord, key) == theory.roman(pc, quality, key)


def test_a_slash_bass_is_spelled_by_the_key_and_moves_with_a_transposition() -> None:
    d_over_fs = chords.Chord(2, "", 6)
    assert chords.name(d_over_fs, theory.Key(2)) == "D/F#"
    assert chords.name(d_over_fs, theory.Key(5)) == "D/Gb"  # in F, by the key's spelling
    assert chords.name(d_over_fs, theory.Key(2), transpose=2) == "E/G#"
    assert chords.roman(d_over_fs, theory.Key(2)) == "I/3"
    assert chords.roman(chords.Chord(7, "", 5), theory.Key(0)) == "V/b7"


@pytest.mark.parametrize(
    ("quality", "numeral"),
    [
        ("maj7", "Imaj7"),
        ("dim", "i°"),
        ("m7b5", "iø7"),
        ("aug", "I+"),
        ("sus4", "Isus4"),
        ("add9", "Iadd9"),
        ("m6", "i6"),
    ],
)
def test_roman_numerals_of_the_typed_qualities(quality: str, numeral: str) -> None:
    assert chords.roman(chords.Chord(0, quality, None), theory.Key(0)) == numeral


def test_no_chord_and_refusals_say_why() -> None:
    assert chords.name(chords.NO_CHORD, theory.Key(0)) == "N.C."
    refused = chords.parse("Cmaj")
    assert isinstance(refused, chords.Refusal) and "Cmaj7" in refused.hint
    two = chords.parse("Bb2")
    assert isinstance(two, chords.Refusal) and two.hint == "Bbsus2 or Bbadd9"  # the root as typed


def test_the_page_reads_the_same_table() -> None:
    # The page cannot fetch a JSON file from disk (file://): it gets the table as a script.
    root = Path(__file__).resolve().parents[1]
    table = (root / "src" / "woodshed" / "chords.json").read_text(encoding="utf-8")
    page = (root / "src" / "woodshed" / "page" / "assets" / "js" / "core" / "chord-table.js").read_text(
        encoding="utf-8"
    )
    shipped = page.split("window.Woodshed.CHORD_TABLE = ", 1)[1].rstrip().rstrip(";")
    assert json.loads(shipped) == json.loads(table), "run python3 scripts/chord_table.py"


STRINGS = [40, 45, 50, 55, 59, 64]  # E2 A2 D3 G3 B3 E4
FIFTH_OPTIONAL = {"9", "m9", "maj9", "add9", "madd9"}


def movable_shape(pc: int, quality: str) -> list[int]:
    """The page's choice (core/instruments.js): the movable form lowest on the neck, a stretch of four
    frets or more counted as three frets higher."""
    forms = chords.MOVABLE[quality]
    found = []
    for string, form in forms.items():
        root_fret = (pc - (4 if string == "E" else 9)) % 12
        for r in (root_fret, root_fret + 12):  # up an octave when a finger would sit below the nut
            if all(o is None or r + o >= 0 for o in form):
                frets = [-1 if o is None else r + o for o in form]
                fretted = [f for f in frets if f > 0]
                low = min(fretted) if fretted else 0
                stretch = 3 if fretted and max(fretted) - low >= 4 else 0
                found.append((low + stretch, frets))
                break
    return min(found, key=lambda x: x[0])[1]


def sounded(frets: list[int]) -> set[int]:
    return {(STRINGS[i] + f) % 12 for i, f in enumerate(frets) if f >= 0}


def playable(frets: list[int], chord: chords.Chord) -> bool:
    fretted = [f for f in frets if f > 0]
    tones = {(chord.pc + i) % 12 for i in chords.intervals(chord.quality)}
    needed = tones - ({(chord.pc + 7) % 12} if chord.quality in FIFTH_OPTIONAL else set())
    if chord.bass is not None:
        tones.add(chord.bass)
        needed.add(chord.bass)
    span_ok = not fretted or max(fretted) - min(fretted) <= 4
    return span_ok and (not fretted or min(fretted) <= 9) and needed <= sounded(frets) <= tones


@pytest.mark.parametrize("quality", list(chords.QUALITIES))
def test_every_typed_quality_has_a_playable_guitar_shape_in_every_key(quality: str) -> None:
    for pc in range(12):
        frets = movable_shape(pc, quality)
        assert playable(frets, chords.Chord(pc, quality)), (theory.SHARP_NAMES[pc] + quality, frets)


def test_the_open_shapes_of_typed_chords_sound_their_chord() -> None:
    for name, frets in chords.OPEN.items():
        chord = chords.parse(name)
        assert isinstance(chord, chords.Chord) and playable(frets, chord), (name, frets)
