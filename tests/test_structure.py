"""Song structure from per-beat labels: bars, lines, section letters, repeats, doubts, harmony."""

from __future__ import annotations

import numpy as np
import pytest

from woodshed import structure as st
from woodshed.theory import Key


def grid(labels: list[str], period: float = 0.5) -> np.ndarray:
    return np.arange(len(labels), dtype=float) * period


def build(labels: list[str], phase: int = 0, per_bar: int = 4, flags: list[bool] | None = None) -> st.Structure:
    n = len(labels)
    return st.build(grid(labels), labels, np.array(flags or [False] * n), None, [], phase, per_bar)


def bar_names(s: st.Structure, i: int) -> list[str]:
    return [c.name for c in s.bars[i].chords]


LOOP = ["C"] * 4 + ["G"] * 4 + ["Am"] * 4 + ["F"] * 4


def test_identical_lines_collapse_into_a_repeat() -> None:
    s = build(LOOP * 3)
    assert len(s.bars) == 12
    assert [g.label for g in s.groups] == ["A"]
    assert len(s.groups[0].occurrences) == 3


def test_a_line_differing_by_one_bar_keeps_its_letter_with_a_prime() -> None:
    variant = ["C"] * 4 + ["G"] * 4 + ["Am"] * 4 + ["Dm"] * 4
    s = build(LOOP + variant + LOOP)
    assert [g.label for g in s.groups] == ["A", "A′", "A"]
    assert all(len(g.occurrences) == 1 for g in s.groups)  # never merged: they differ


def test_a_different_line_gets_a_new_letter() -> None:
    other = ["Am"] * 4 + ["G"] * 4 + ["F"] * 4 + ["E"] * 4
    s = build(LOOP + other + LOOP)
    assert [g.label for g in s.groups] == ["A", "B", "A"]


def test_no_repetition_means_no_repeat_marks() -> None:
    s = build(["C"] * 4 + ["D"] * 4 + ["E"] * 4 + ["F"] * 4 + ["G"] * 4 + ["A"] * 4 + ["B"] * 4 + ["Bb"] * 4)
    assert all(len(g.occurrences) == 1 for g in s.groups)


def test_two_chords_per_bar() -> None:
    s = build(["C", "C", "G", "G", "Am", "Am", "F", "F"])
    assert bar_names(s, 0) == ["C", "G"] and [c.beats for c in s.bars[0].chords] == [2, 2]


def test_leading_and_trailing_silence_is_trimmed_and_reported() -> None:
    s = build(["N"] * 6 + LOOP + ["N"] * 3)
    assert s.music_start == pytest.approx(3.0)
    assert bar_names(s, 0) == ["N", "C"]  # the pickup beats are no-chord, not an invented chord
    assert s.bars[0].chords[0].beats == 2
    assert s.music_end == pytest.approx(11.0)  # last chord beat at 10.5 s, plus one beat


def test_bar_phase_sets_where_bars_start() -> None:
    s = build(["C", *LOOP], phase=1)
    assert bar_names(s, 1) == ["C"]
    assert s.bars[1].start == pytest.approx(0.5)


def test_three_four_bars() -> None:
    s = build(["D"] * 3 + ["A"] * 3 + ["Bm"] * 3 + ["G"] * 3, per_bar=3)
    assert len(s.bars) == 4 and bar_names(s, 2) == ["Bm"]


def test_silence_only_gives_an_empty_structure() -> None:
    s = build(["N"] * 16)
    assert s.bars == [] and s.groups == []


def test_doubtful_chords_carry_ranked_alternatives() -> None:
    labels = LOOP
    flags = [False] * 12 + [True] * 4
    names = ["C", "Cm", "F", "Fm", "Am", "G"]
    scores = np.zeros((len(names), len(labels)))
    scores[names.index("F"), 12:] = 0.80
    scores[names.index("Fm"), 12:] = 0.78
    scores[names.index("Am"), 12:] = 0.60
    s = st.build(grid(labels), labels, np.array(flags), scores, names, 0, 4)
    doubt = s.bars[3].chords[0].doubt
    assert doubt is not None
    assert [a.name for a in doubt.alternatives] == ["F", "Fm", "Am"]
    shares = [a.share for a in doubt.alternatives]
    assert shares == sorted(shares, reverse=True) and 98 <= sum(shares) <= 102
    assert s.bars[0].chords[0].doubt is None


def test_harmony_summary_names_the_progression() -> None:
    s = build(LOOP * 2)
    summary = st.harmony_summary(s, Key(0, "maj"))
    assert [h.label for h in summary.sections] == ["A"]
    assert summary.sections[0].romans == ["I", "V", "vi", "IV"]
    assert summary.name is not None and "most common one in pop" in summary.name


def test_two_alternating_sections_are_one_loop() -> None:
    a = ["Ab"] * 8 + ["Fm"] * 8
    b = ["Db"] * 8 + ["Bbm"] * 4 + ["Eb"] * 4
    s = build((a + b) * 3)
    summary = st.harmony_summary(s, Key(8, "maj"))
    assert [h.label for h in summary.sections] == ["A+B"]
    assert summary.sections[0].romans == ["I", "vi", "IV", "ii", "V"]
    assert summary.name is not None and "ii before the V" in summary.name


def test_verse_and_refrain_are_summarised_separately() -> None:
    verse = ["C", "C", "G", "G", "Am", "Am", "F", "F", "C", "C", "G", "G", "F", "F", "C", "C"]
    refrain = ["Am", "Am", "G", "G", "F", "F", "C", "C", "C", "C", "G", "G", "F", "F", "C", "C"]
    s = build(verse * 2 + refrain + verse * 2 + refrain * 2)
    summary = st.harmony_summary(s, Key(0, "maj"))
    assert [h.label for h in summary.sections] == ["A", "B"]
    assert summary.sections[0].romans[:4] == ["I", "V", "vi", "IV"]
    assert summary.sections[1].romans[:4] == ["vi", "V", "IV", "I"]
