"""The page draws the chart's lines again when the band edits its parts: the same lines as Python."""

from __future__ import annotations

import itertools
import json
import random
from typing import Any

from woodshed import structure
from woodshed.model import Bar, Chord, Group, Section


def _python(bars_json: list[dict[str, Any]], starts: list[int]) -> tuple[list[Group], list[tuple[int, int, int]]]:
    bars = [
        Bar(b["start"], b["end"], [Chord(c["pc"], c["quality"], c["beats"]) for c in b["chords"]]) for b in bars_json
    ]
    edges = [*starts, len(bars)]
    parts = [Section("P", "part", "A", a, b) for a, b in itertools.pairwise(edges)]
    groups = structure._group(bars, parts)
    return groups, [(b.group, b.occurrence, b.column) for b in bars]


def _as_dicts(groups: list[Group]) -> list[dict[str, Any]]:
    return [{"label": g.label, "family": g.family, "occurrences": g.occurrences} for g in groups]


def _regroup(o: Any, bars: str, starts: list[int]) -> tuple[list[dict[str, Any]], list[tuple[int, int, int]]]:
    parts = json.dumps([{"start": s} for s in starts])
    out = o.js(
        f"(() => {{ const r = Woodshed.structure.regroup({bars}, {parts});"
        " return [r.groups, r.fields.map((f) => [f.group, f.occurrence, f.column])]; })()"
    )
    return out[0], [tuple(f) for f in out[1]]


def _page(o: Any, starts: list[int]) -> tuple[list[dict[str, Any]], list[tuple[int, int, int]]]:
    return _regroup(o, "Woodshed.current.bars", starts)


def test_the_analysis_lines_come_out_the_same(open_page: Any) -> None:
    for name in ("pop", "waltz"):
        o = open_page(name)
        song = o.js("Woodshed.current.song")
        groups, fields = _page(o, [s["start"] for s in song["sections"]])
        assert groups == song["groups"], name
        assert fields == [(b["group"], b["occurrence"], b["column"]) for b in song["bars"]], name


def test_parts_anywhere_give_the_lines_python_gives(open_page: Any) -> None:
    o = open_page("pop")
    bars = o.js("Woodshed.current.song.bars")
    rng = random.Random(3)
    for _ in range(25):
        starts = sorted({0, *(rng.randrange(1, len(bars)) for _ in range(rng.randrange(0, 4)))})
        groups, fields = _python(bars, starts)
        page_groups, page_fields = _page(o, starts)
        assert page_groups == _as_dicts(groups), starts
        assert page_fields == fields, starts


def test_long_charts_with_repeats_and_variants_agree(open_page: Any) -> None:
    o = open_page("pop")
    rng = random.Random(11)
    primes = 0
    for _ in range(40):
        motif = [rng.choice([0, 5, 7, 9]) for _ in range(4)]
        labels = []
        for _ in range(10):  # a line again, a variant of it (one bar changed), or a new line
            line = motif[:] if rng.random() < 0.5 else [rng.choice([0, 2, 5, 7, 9]) for _ in range(4)]
            if rng.random() < 0.3:
                line[rng.randrange(4)] = rng.choice([2, 4, 11])
            labels += line
        labels = labels[: rng.randrange(20, 41)]
        bars = [
            {"start": i, "end": i + 1, "chords": [{"pc": pc, "quality": "m" if pc in (2, 4, 9) else "", "beats": 4}]}
            for i, pc in enumerate(labels)
        ]
        starts = sorted({0, *(rng.randrange(1, len(bars)) for _ in range(rng.randrange(0, 5)))})
        groups, fields = _python(bars, starts)
        page_groups, page_fields = _regroup(o, json.dumps(bars), starts)
        assert page_groups == _as_dicts(groups)
        assert page_fields == fields
        primes += sum("′" in g.label for g in groups)
    assert primes > 0  # variants (A′) are exercised
