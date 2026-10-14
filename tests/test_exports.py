"""Exports read back: ChordPro, MIREX .lab, MIDI and MusicXML say what the chart says."""

from __future__ import annotations

import re
import struct
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import pytest

from tests import synth
from tests.test_analysis import fake_stems
from woodshed import analysis, exports, song, theory


@pytest.fixture(scope="module")
def pop(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    folder = tmp_path_factory.mktemp("exports")
    wav = synth.write("pop", folder).wav
    result = analysis.analyze(wav, use_stems=True, stems_result=fake_stems("pop", folder), title="Pop & Co")
    return song.to_json(result)


@pytest.fixture(scope="module")
def waltz(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    folder = tmp_path_factory.mktemp("exports-waltz")
    wav = synth.write("waltz", folder).wav
    return song.to_json(analysis.analyze(wav, use_stems=False, beats_per_bar=3))


def names(data: dict[str, Any]) -> list[list[str]]:
    key = theory.Key(data["key"]["pc"], data["key"]["mode"])
    return [[exports._name(c, key) for c in bar["chords"]] for bar in data["bars"]]


def test_chordpro_has_the_song_facts_and_one_grid_per_section(pop: dict[str, Any]) -> None:
    text = exports.chordpro(pop)
    assert "{title: Pop & Co}" in text and "{key: C}" in text and "{time: 4/4}" in text
    assert text.count('{start_of_grid label="') == len(pop["groups"]) == text.count("{end_of_grid}")
    grid = [re.sub(r"^\|:? | :?\|( x\d+)?$", "", line) for line in text.splitlines() if line.startswith("|")]
    bars = [bar.split() for line in grid for bar in line.split(" | ")]
    assert all(len(cells) == 4 for cells in bars)  # one cell per beat
    first_line = pop["groups"][0]["occurrences"][0]
    assert [cells[0] for cells in bars[:4]] == [names(pop)[u][0] for u in first_line]


def test_chordpro_marks_repeats(pop: dict[str, Any]) -> None:
    repeated = [g for g in pop["groups"] if len(g["occurrences"]) > 1]
    assert repeated and exports.chordpro(pop).count("|: ") == len(repeated)


def test_lab_covers_the_file_and_matches_the_chart(pop: dict[str, Any]) -> None:
    rows = [line.split() for line in exports.lab(pop).splitlines()]
    starts, ends = [float(r[0]) for r in rows], [float(r[1]) for r in rows]
    assert starts[0] == 0 and ends[-1] == pytest.approx(pop["duration"])
    assert all(e == pytest.approx(s) for e, s in zip(ends, starts[1:], strict=False))  # contiguous
    labels = [r[2] for r in rows]
    assert labels[1:5] == ["C:maj", "G:maj", "A:min", "F:maj"]
    bar = pop["bars"][1]  # the G bar spans exactly its bar
    g_row = rows[2]
    assert float(g_row[0]) == pytest.approx(bar["start"], abs=0.002) and float(g_row[1]) == pytest.approx(
        bar["end"], abs=0.002
    )


def read_midi(data: bytes) -> tuple[tuple[int, int, int], list[list[tuple[int, bytes]]]]:
    """A small reader: header (format, tracks, PPQ) and each track's (absolute tick, event)."""
    assert data[:4] == b"MThd"
    fmt, ntracks, ppq = struct.unpack(">HHH", data[8:14])
    pos = 14
    tracks = []
    for _ in range(ntracks):
        assert data[pos : pos + 4] == b"MTrk"
        (length,) = struct.unpack(">I", data[pos + 4 : pos + 8])
        body = data[pos + 8 : pos + 8 + length]
        pos += 8 + length
        events, i, tick = [], 0, 0
        while i < len(body):
            delta = 0
            while True:
                byte = body[i]
                i += 1
                delta = (delta << 7) | (byte & 0x7F)
                if byte < 0x80:
                    break
            tick += delta
            status = body[i]
            if status == 0xFF:
                size = body[i + 2]
                events.append((tick, body[i : i + 3 + size]))
                i += 3 + size
            else:
                size = 2 if status & 0xF0 == 0xC0 else 3
                events.append((tick, body[i : i + size]))
                i += size
        tracks.append(events)
    assert pos == len(data)
    return (fmt, ntracks, ppq), tracks


def test_midi_has_tempo_chords_bass_and_drums_on_the_grid(pop: dict[str, Any]) -> None:
    (fmt, ntracks, ppq), tracks = read_midi(exports.midi(pop))
    assert (fmt, ntracks, ppq) == (1, 4, exports.PPQ)
    tempo = next(e for _, e in tracks[0] if e[:2] == b"\xff\x51")
    assert 60_000_000 / int.from_bytes(tempo[3:6], "big") == pytest.approx(pop["bpm"], rel=0.01)
    for track in tracks[1:]:
        ons = [(t, e[1]) for t, e in track if e[0] & 0xF0 == 0x90]
        offs = [(t, e[1]) for t, e in track if e[0] & 0xF0 == 0x80]
        assert ons and len(ons) == len(offs)
    chord_track = tracks[1]
    first_on = [e[1] % 12 for t, e in chord_track if e[0] & 0xF0 == 0x90 and t == 0]
    c = pop["bars"][0]["chords"][0]
    assert c["quality"] == "" and set(first_on) == {(c["pc"] + i) % 12 for i in (0, 4, 7)}  # the C triad
    drums = [e for _, e in tracks[3] if e[0] & 0xF0 == 0x90]
    assert drums and all(e[0] & 0x0F == 9 for e in drums)  # General MIDI drum channel


def test_midi_without_stems_plays_the_roots(waltz: dict[str, Any]) -> None:
    (_, ntracks, _), tracks = read_midi(exports.midi(waltz))
    assert ntracks == 3  # no drum track without a groove
    meter = next(e for _, e in tracks[0] if e[:2] == b"\xff\x58")
    assert meter[3] == 3  # 3/4


def test_musicxml_is_well_formed_and_every_bar_adds_up(pop: dict[str, Any], waltz: dict[str, Any]) -> None:
    for data in (pop, waltz):
        root = ET.fromstring(exports.musicxml(data).split("\n", 2)[2])
        measures = root.findall("./part/measure")
        assert len(measures) == len(data["bars"])
        per = data["beats_per_bar"]
        for m in measures:
            assert sum(int(n.findtext("duration") or 0) for n in m.findall("note")) == per * exports.STEM_SLOTS
        assert root.findtext(".//key/fifths") == ("0" if data is pop else "2")  # C major, D major
        assert root.findtext(".//time/beats") == str(per)


def test_musicxml_chord_symbols_follow_the_chart(pop: dict[str, Any]) -> None:
    root = ET.fromstring(exports.musicxml(pop).split("\n", 2)[2])
    first = root.findall("./part/measure")[:4]
    symbols = [(m.findtext("harmony/root/root-step"), m.findtext("harmony/kind")) for m in first]
    assert symbols == [("C", "major"), ("G", "major"), ("A", "minor"), ("F", "major")]
    bass = [n for n in first[0].findall("note") if n.find("pitch") is not None]
    assert bass and bass[0].findtext("pitch/step") == "C"  # the bass line from the bass stem


def test_write_all_names_the_files_after_the_song(pop: dict[str, Any], tmp_path: Path) -> None:
    files = exports.write_all({**pop, "file": 'a/b:c*?"<>|.mp3'}, tmp_path)
    assert sorted(p.suffix for p in files) == [".cho", ".json", ".lab", ".mid", ".musicxml"]
    assert all(p.parent == tmp_path and p.exists() for p in files)


def test_hostile_titles_stay_inside_their_directive_and_xml(pop: dict[str, Any]) -> None:
    data = {**pop, "title": "Live }{title: x}\n\x01 at <Club> & co", "file": "a\nb}.wav"}
    text = exports.chordpro(data)
    assert text.splitlines()[0] == "{title: Live )(title: x)  at <Club> & co}"
    assert text.count("{title:") == 1 and "\x01" not in text
    root = ET.fromstring(exports.musicxml(data).split("\n", 2)[2])  # well-formed despite the control character
    assert root.findtext("work/work-title") == "Live }{title: x}\n at <Club> & co"


def test_tempo_rounds_half_up_like_the_page(pop: dict[str, Any]) -> None:
    assert "{tempo: 119}" in exports.chordpro({**pop, "bpm": 118.5})
    assert exports.half_up(116.5) == 117 and exports.half_up(116.49) == 116


@pytest.mark.parametrize("name", ["ballad", "funk", "pickup"])
def test_lab_never_runs_past_the_end_of_the_file(tmp_path: Path, name: str) -> None:
    wav = synth.write(name, tmp_path).wav
    data = song.to_json(analysis.analyze(wav, use_stems=False))
    rows = [line.split() for line in exports.lab(data).splitlines()]
    assert float(rows[-1][1]) == pytest.approx(data["duration"]) and all(
        float(r[1]) <= data["duration"] + 1e-9 for r in rows
    )
    assert all(float(r[0]) < float(r[1]) for r in rows)


def test_export_file_names_are_plain_ascii(pop: dict[str, Any], tmp_path: Path) -> None:
    files = exports.write_all({**pop, "file": "Song #1 100% été?.wav"}, tmp_path)
    assert sorted(p.name for p in files) == [f"Song_1_100_t.{ext}" for ext in ("cho", "json", "lab", "mid", "musicxml")]


def test_musicxml_ties_have_notations_for_score_editors(pop: dict[str, Any]) -> None:
    # Notes of 5 sixteenths (a quarter tied to a sixteenth), then 11.
    line = [[36, 1.0]] + [None] * 4 + [[38, 1.0]] + [None] * 10
    data = {**pop, "parts": {**pop["parts"], "bass": [line for _ in pop["bars"]]}}
    root = ET.fromstring(exports.musicxml(data).split("\n", 2)[2])
    notes = root.findall("./part/measure/note")
    tied = [n for n in notes if n.find("tie") is not None]
    assert tied and all(n.find("notations/tied") is not None for n in tied)
