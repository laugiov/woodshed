"""ChordPro for the stand and OnSong (spec 014, round 5): a sung line is never cut by a chord row, N.C. is never a
chord, repeated chord rows are folded, a key change is said where it happens."""

from __future__ import annotations

from typing import Any

import pytest

from tests import synth
from tests.test_exports import names, pop, words_for  # noqa: F401  (pop: a fixture)
from woodshed import analysis, exports, song


def line_of(data: dict[str, Any], spans: list[tuple[str, float, float]]) -> dict[str, Any]:
    """Words given as (text, start bar, end bar), in bars of the song (fractions allowed)."""
    starts = [b["start"] for b in data["bars"]]
    bar = starts[1] - starts[0]

    def at(x: float) -> float:
        return starts[0] + x * bar

    words = [{"text": t, "start": at(a), "end": at(b)} for t, a, b in spans]
    base: dict[str, Any] = {"tag": None, "block": 0, "backing": [], "sung": True, "check": None}
    return {**base, "text": " ".join(t for t, _, _ in spans), "words": words}


def sung(data: dict[str, Any], spans: list[tuple[str, float, float]]) -> list[str]:
    words = {**words_for(data), "lines": [line_of(data, spans)]}
    text = exports.chordpro(data, words)
    return text.split('{start_of_verse: label="Verse 1"}\n')[1].split("\n{end_of_verse}")[0].splitlines()


def test_a_chord_between_two_words_goes_inline_not_on_a_row(pop: dict[str, Any]) -> None:  # noqa: F811
    n = names(pop)
    rows = sung(pop, [("Morning", 0.0, 0.4), ("comes", 2.0, 2.4)])  # G (bar 2) in the gap
    assert rows[0] == f"[{n[0][0]}]Morning [{n[1][0]}] [{n[2][0]}]comes"


def test_a_break_of_two_bars_or_more_stays_a_bar_row(pop: dict[str, Any]) -> None:  # noqa: F811
    n = names(pop)
    rows = sung(pop, [("Morning", 0.0, 0.4), ("comes", 3.0, 3.4)])  # G and Am in a gap of 2.6 bars
    assert rows[:3] == [f"[{n[0][0]}]Morning", f"| [{n[1][0]}] | [{n[2][0]}] |", f"[{n[3][0]}]comes"]


def test_a_chord_on_a_held_word_comes_after_it(pop: dict[str, Any]) -> None:  # noqa: F811
    n = names(pop)
    rows = sung(pop, [("Morning", 0.0, 1.45), ("comes", 2.0, 2.4)])  # held over the G of bar 2
    assert rows[0] == f"[{n[0][0]}]Morning [{n[1][0]}] [{n[2][0]}]comes"


def test_no_chord_is_ever_glued_to_another_on_a_word(pop: dict[str, Any]) -> None:  # noqa: F811
    text = exports.chordpro(pop, words_for(pop))
    assert "][" not in text


def test_no_chord_written_is_ever_n_c(pop: dict[str, Any]) -> None:  # noqa: F811
    bars = [dict(b) for b in pop["bars"]]
    bars[1] = {**bars[1], "chords": [{**bars[1]["chords"][0], "pc": -1, "quality": "N", "doubt": None}]}
    data = {**pop, "bars": bars}
    rows = sung(data, [("Morning", 0.0, 0.4), ("comes", 3.0, 3.4)])
    assert "[N.C.]" not in "\n".join(rows) and "[*N.C.]" in rows[1]


@pytest.mark.parametrize(
    ("rows", "folded"),
    [
        (["| [A] |"] * 4, ["| [A] | x4"]),
        (["| [A] |", "| [B] |"] * 2 + ["| [A] |"], ["|: [A] |", "| [B] :| x2", "| [A] |"]),
        (["| [A] |", "| [A] |", "| [B] |", "| [B] |"], ["| [A] | x2", "| [B] | x2"]),
        (["| [A] |", "| [B] |", "| [C] |"], ["| [A] |", "| [B] |", "| [C] |"]),
    ],
)
def test_repeated_chord_rows_are_folded(rows: list[str], folded: list[str]) -> None:
    assert exports.fold_rows(rows) == folded


@pytest.fixture(scope="module")
def lift(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    folder = tmp_path_factory.mktemp("lift")
    return song.to_json(analysis.analyze(synth.write("lift", folder).wav, use_stems=False))


def test_a_key_change_in_a_grid_part_is_said_and_the_rest_continues(lift: dict[str, Any]) -> None:
    sections = [{"name": "Part B", "role": "verse", "letter": "B", "start": 12, "end": len(lift["bars"])}]
    data = {**lift, "sections": [{**lift["sections"][0], "end": 12}, *sections]}
    text = exports.chordpro(data)
    assert '{start_of_grid: label="Part B"}' in text
    head, tail = text.split("{comment: Key change: Db major}\n{key: Db}\n")
    assert head.rstrip().endswith("{end_of_grid}") and tail.startswith('{start_of_grid: label="Part B, continued"}')
    assert text.count('label="Part B"') == 1


def test_a_key_change_in_sung_lines_is_said_before_the_line_that_holds_it(lift: dict[str, Any]) -> None:
    data = {
        **lift,
        "sections": [{"name": "Verse 1", "role": "verse", "letter": "A", "start": 0, "end": len(lift["bars"])}],
    }
    words = {
        **words_for(data),
        "lines": [
            line_of(data, [("before", 14.0, 14.5)]),
            line_of(data, [("over", 15.2, 15.6), ("change", 16.2, 16.6)]),
        ],
    }
    rows = exports.chordpro(data, words).splitlines()
    said = rows.index("{comment: Key change: Db major}")
    assert rows[said + 1] == "{key: Db}" and any("over" in r for r in rows[said + 2 : said + 4])  # with its line
    assert "key change to" not in "\n".join(rows)  # the 0.4.0 part-level comment is gone
