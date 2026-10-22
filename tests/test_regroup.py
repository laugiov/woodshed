"""Lines of the chart: four bars inside each part, a part always starting a line."""

from __future__ import annotations

import itertools
import random

from woodshed import structure
from woodshed.model import Bar, Chord, Group, Section


def _old_group(bars: list[Bar], sections: list[Section]) -> list[Group]:
    """structure._group as it was before parts could start anywhere: the reference the analysis must keep."""
    lettering = structure._Lettering()
    groups: list[Group] = []
    previous = None
    starts = {s.start for s in sections}
    for start in range(0, len(bars), structure.LINE_BARS):
        line = list(range(start, min(start + structure.LINE_BARS, len(bars))))
        sig = tuple(bars[i].signature() for i in line)
        if groups and sig == previous and start not in starts:
            groups[-1].occurrences.append(line)
        else:
            label, family = lettering.letter_for(sig)
            groups.append(Group(label, family, [line]))
        previous = sig
    return groups


def _bars(labels: list[int]) -> list[Bar]:
    return [Bar(float(i), float(i + 1), [Chord(pc, "m" if pc % 3 else "", 4)]) for i, pc in enumerate(labels)]


def _parts(n: int, starts: list[int]) -> list[Section]:
    edges = [*starts, n]
    return [Section(f"P{k}", "part", "A", a, b) for k, (a, b) in enumerate(itertools.pairwise(edges))]


def _fields(bars: list[Bar]) -> list[tuple[int, int, int]]:
    return [(b.group, b.occurrence, b.column) for b in bars]


def test_parts_on_the_four_bar_grid_give_the_lines_they_always_gave() -> None:
    rng = random.Random(7)
    for _ in range(200):
        n = rng.randrange(1, 40)
        labels = [rng.choice([0, 0, 7, 9, 5]) for _ in range(n)]
        starts = sorted({0, *(4 * rng.randrange(0, (n + 3) // 4) for _ in range(rng.randrange(0, 4)))})
        starts = [s for s in starts if s < n]
        old_bars, new_bars = _bars(labels), _bars(labels)
        expected = _old_group(old_bars, _parts(n, starts))
        assert structure._group(new_bars, _parts(n, starts)) == expected


def test_a_part_starting_off_the_grid_starts_a_line() -> None:
    bars = _bars([0, 7, 9, 5, 0, 7, 9, 5, 0, 7])
    groups = structure._group(bars, _parts(10, [0, 6]))
    assert [g.occurrences for g in groups] == [[[0, 1, 2, 3]], [[4, 5]], [[6, 7, 8, 9]]]
    assert _fields(bars)[6] == (2, 0, 0)  # the part's first bar is a line's first bar


def test_without_parts_lines_are_every_four_bars() -> None:
    bars = _bars([0, 0, 0, 0, 0, 0, 0, 0, 7])
    assert [g.occurrences for g in structure._group(bars, [])] == [[[0, 1, 2, 3], [4, 5, 6, 7]], [[8]]]
