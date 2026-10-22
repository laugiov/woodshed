"""Typed chords in every corner of the page: guitar shapes, keys, triads and the exports."""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from typing import Any

from tests.test_chords import movable_shape
from woodshed import chords

STRINGS = [40, 45, 50, 55, 59, 64]


def test_movable_shapes_are_the_ones_python_checks_for_every_quality_and_key(open_page: Any) -> None:
    o = open_page("pop")
    for quality in chords.QUALITIES:
        got = o.js(
            f"[...Array(12).keys()].map((pc) => Woodshed.instruments.movableShape(pc, {json.dumps(quality)}).frets)"
        )
        assert got == [movable_shape(pc, quality) for pc in range(12)], quality


def test_typed_chords_find_their_open_shapes_and_a_slash_bass_is_kept(open_page: Any) -> None:
    o = open_page("pop")
    shape = "(pc, q, bass) => Woodshed.instruments.openOrBarre(Woodshed.current.view.shapes, pc, q, bass)"
    assert o.js(f"({shape})(2, '', 6).frets") == chords.OPEN["D/F#"]  # D/F# has its own open shape
    assert o.js(f"({shape})(2, 'sus4', null).frets") == chords.OPEN["Dsus4"]
    e_over_gs = o.js(f"({shape})(4, '', 8)")  # no own shape: E's, with the bass named apart
    assert e_over_gs["bass"] == 8 and e_over_gs["frets"] == [0, 2, 2, 1, 0, 0]
    # The analysis's chords keep exactly their shapes (no bass, the four qualities).
    assert o.js(f"({shape})(9, 'm7', null)").get("bass") is None


def test_keys_and_triads_play_the_typed_chord(open_page: Any) -> None:
    o = open_page("pop")
    cmaj7 = o.js("Woodshed.instruments.keysMidi(0, 'maj7', false)")
    assert {n % 12 for n in cmaj7} == {0, 4, 7, 11}
    g9 = o.js("Woodshed.instruments.keysMidi(7, '9', false)")
    assert {n % 12 for n in g9} == {7, 11, 5, 9} and len(g9) == 4  # five-note chord: the fifth left out
    d_fs = o.js("Woodshed.instruments.keysMidi(2, '', true, 6)")
    assert d_fs[0] % 12 == 6 and d_fs[0] < min(d_fs[1:])  # the slash bass in the left hand, below
    assert o.js("Woodshed.instruments.triadOf(0, 'maj7')") == [0, 4, 11]
    assert o.js("Woodshed.instruments.triadOf(2, 'sus4')") == [2, 7, 9]
    assert o.js("Woodshed.instruments.triadOf(9, 'm')") == [9, 0, 4]  # the analysis's: unchanged


TYPED = (
    "(() => { Woodshed.current.bars[1].chords = ["
    "{pc: 2, quality: '', bass: 6, beats: 2, doubt: null}, {pc: 7, quality: 'maj7', beats: 2, doubt: null}]; })()"
)


def note_ons(midi: bytes, track_no: int) -> list[tuple[int, int]]:
    """(tick, note) of every note-on of one track."""
    pos = 14
    for _ in range(track_no):
        pos += 8 + int.from_bytes(midi[pos + 4 : pos + 8], "big")
    end = pos + 8 + int.from_bytes(midi[pos + 4 : pos + 8], "big")
    pos += 8
    tick, out, status = 0, [], 0
    while pos < end:
        delta = 0
        while True:
            byte = midi[pos]
            pos += 1
            delta = (delta << 7) | (byte & 0x7F)
            if byte < 0x80:
                break
        tick += delta
        if midi[pos] == 0xFF:
            length = midi[pos + 2]
            pos += 3 + length
            continue
        if midi[pos] & 0x80:
            status = midi[pos]
            pos += 1
        a, b = midi[pos], midi[pos + 1] if status & 0xF0 not in (0xC0, 0xD0) else 0
        pos += 1 if status & 0xF0 in (0xC0, 0xD0) else 2
        if status & 0xF0 == 0x90 and b > 0:
            out.append((tick, a))
    return out


def test_the_exports_carry_typed_qualities_and_slash_basses(open_page: Any) -> None:
    o = open_page("pop")
    o.js(TYPED)
    per = o.js("Woodshed.current.per")
    lab = o.js("Woodshed.exports.lab(Woodshed.current)")
    assert " D:maj/3\n" in lab and " G:maj7\n" in lab  # Harte: the bass as its degree
    xml = o.js("Woodshed.exports.musicxml(Woodshed.current)")
    ET.fromstring(re.sub(r"<!DOCTYPE[^>]*>", "", xml).encode())  # well formed
    second = xml.split('<measure number="2">')[1].split("</measure>")[0]
    assert "<kind>major</kind><bass><bass-step>F</bass-step><bass-alter>1</bass-alter></bass>" in second
    assert '<kind text="maj7">major-seventh</kind>' in second
    midi = bytes(o.js("Array.from(Woodshed.exports.midi(Woodshed.current))"))
    at = per * 480  # bar 2
    d_over_fs = sorted(n for t, n in note_ons(midi, 1) if t == at)
    assert d_over_fs[0] % 12 == 6 and {n % 12 for n in d_over_fs[1:]} == {2, 6, 9}  # F# below the D chord
    gmaj7 = {n % 12 for t, n in note_ons(midi, 1) if t == at + 2 * 480}
    assert gmaj7 == {7, 11, 2, 6}
    pro = o.js("Woodshed.exports.chordpro(Woodshed.current, null)")
    assert "D/F#" in pro and "Gmaj7" in pro
