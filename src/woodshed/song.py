"""The song model handed to the practice page, and its JSON form (versioned, with a JSON Schema)."""

from __future__ import annotations

import json
from functools import cache
from importlib import resources
from typing import Any

from woodshed import model
from woodshed.model import Song

SCHEMA_VERSION = 2  # 2: sections, doubt kinds


def _r(x: float, digits: int = 3) -> float:
    return round(float(x), digits)


def _chord(c: model.Chord) -> dict[str, Any]:
    out: dict[str, Any] = {"pc": c.pc, "quality": c.quality, "beats": c.beats, "doubt": None}
    if c.doubt:
        out["doubt"] = {
            "id": c.doubt.id,
            "why": c.doubt.why,
            "kind": c.doubt.kind,
            "alternatives": [{"pc": a.pc, "quality": a.quality, "share": a.share} for a in c.doubt.alternatives],
        }
    return out


def to_json(song: Song) -> dict[str, Any]:
    """Plain JSON data for the page (no numpy types)."""
    s = song.structure
    data: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "title": song.title,
        "file": song.file,
        "duration": _r(song.duration, 2),
        "bpm": _r(song.bpm, 1),
        "beats_per_bar": song.beats_per_bar,
        "key": {"pc": song.key.tonic, "mode": song.key.mode, "known": song.key_known},
        "capo": song.capo,
        "beats": [_r(t) for t in song.beats],
        "first_beat": s.first_beat,
        "music_start": None if s.music_start is None else _r(s.music_start),
        "music_end": None if s.music_end is None else _r(s.music_end),
        "bars": [
            {
                "start": _r(b.start),
                "end": _r(b.end),
                "group": b.group,
                "occurrence": b.occurrence,
                "column": b.column,
                "chords": [_chord(c) for c in b.chords],
            }
            for b in s.bars
        ],
        "groups": [{"label": g.label, "family": g.family, "occurrences": g.occurrences} for g in s.groups],
        "sections": [
            {"name": x.name, "role": x.role, "letter": x.letter, "start": x.start, "end": x.end} for x in s.sections
        ],
        "harmony": [
            {"label": h.label, "chords": [list(c) for c in h.chords], "romans": h.romans, "name": h.name}
            for h in song.harmony.sections
        ],
        "energy": [[_r(t), _r(db, 1)] for t, db in song.energy],
        "parts": None,
        "analysis": {
            "beats": song.analysis.beats,
            "tempo_halved": song.analysis.tempo_halved,
            "stems": song.analysis.stems,
            "sevenths": song.analysis.sevenths,
            "clarity": _r(song.analysis.clarity, 2),
            "chords_reliable": song.analysis.chords_reliable,
            "stems_gain": None if song.analysis.stems_gain is None else _r(song.analysis.stems_gain, 6),
            "bpm_hint": song.analysis.bpm_hint,
        },
        "meta": {"version": song.meta.version, "seconds": _r(song.meta.seconds, 1)},
    }
    if song.parts:
        p = song.parts
        data["parts"] = {
            "groove": None
            if p.groove is None
            else {
                "kick": p.groove.kick,
                "snare": p.groove.snare,
                "hat": p.groove.hat,
                "agreement": p.groove.agreement,
                "bars": p.groove.bars,
            },
            "bass": [[None if n is None else [n.midi, n.confidence] for n in bar] for bar in p.bass],
            "comp": p.comp,
            "voicings": p.voicings,
            "vocal": None
            if p.vocal is None
            else {"low": p.vocal.low, "high": p.vocal.high, "voiced_share": p.vocal.voiced_share},
            "grid_shift": _r(p.grid_shift),
        }
    return data


@cache
def schema() -> dict[str, Any]:
    text = resources.files("woodshed").joinpath("song.schema.json").read_text(encoding="utf-8")
    result: dict[str, Any] = json.loads(text)
    return result


def cross_check(data: dict[str, Any]) -> list[str]:
    """Rules the JSON Schema cannot express: indexes between bars and groups, lengths, order.

    Returns the problems found (empty when the data is consistent).
    """
    problems: list[str] = []
    per_bar, bars, groups = data["beats_per_bar"], data["bars"], data["groups"]
    slots = per_bar * 4
    if len(data["energy"]) != len(data["beats"]):
        problems.append("energy and beats differ in length")
    if any(b >= a for a, b in zip(data["beats"][1:], data["beats"], strict=False)):
        problems.append("beats are not strictly in time order")
    placed: set[int] = set()
    for g, group in enumerate(groups):
        for o, line in enumerate(group["occurrences"]):
            for c, i in enumerate(line):
                if not 0 <= i < len(bars):
                    problems.append(f"group {g} refers to bar {i}, which does not exist")
                    continue
                placed.add(i)
                if (bars[i]["group"], bars[i]["occurrence"], bars[i]["column"]) != (g, o, c):
                    problems.append(f"bar {i} does not point back to group {g}, occurrence {o}, column {c}")
        if not group["label"].startswith(group["family"]):
            problems.append(f"group {g}: label {group['label']} is not of family {group['family']}")
    if placed != set(range(len(bars))):
        problems.append("some bars belong to no group")
    edge = 0
    group_starts = {group["occurrences"][0][0] for group in groups if group["occurrences"]}
    for k, sec in enumerate(data["sections"]):
        if sec["start"] != edge or sec["end"] <= sec["start"]:
            problems.append(f"section {k} does not start right after the previous section")
        if sec["start"] not in group_starts:
            problems.append(f"section {k} does not start a line of its own on the page")
        edge = sec["end"]
    if bars and edge != len(bars):
        problems.append("the sections do not cover every bar")
    ids = []
    for i, bar in enumerate(bars):
        if bar["end"] <= bar["start"] or (i and bar["start"] < bars[i - 1]["start"]):
            problems.append(f"bar {i}: times out of order")
        # The last bar may run past the end of the file (a song ending mid-bar), by less than a bar.
        if bar["start"] < 0 or bar["start"] >= data["duration"]:
            problems.append(f"bar {i}: starts outside the file")
        if sum(c["beats"] for c in bar["chords"]) != per_bar:
            problems.append(f"bar {i}: chord beats do not add up to {per_bar}")
        ids += [c["doubt"]["id"] for c in bar["chords"] if c["doubt"]]
    if len(ids) != len(set(ids)):
        problems.append("doubt ids are not unique")
    parts = data["parts"]
    if parts:
        lengths = {"comp": len(parts["comp"])}
        if parts["groove"]:
            lengths |= {k: len(parts["groove"][k]) for k in ("kick", "snare", "hat")}
        lengths |= {f"bass bar {i}": len(b) for i, b in enumerate(parts["bass"])}
        problems += [f"parts: {k} has {n} slots, not {slots}" for k, n in lengths.items() if n != slots]
        for name in ("bass", "voicings"):
            if len(parts[name]) != len(bars):
                problems.append(f"parts: {name} has {len(parts[name])} bars, not {len(bars)}")
    return problems
