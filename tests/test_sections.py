"""Song sections: named the way a band talks (intro, verse, chorus), from chords, loudness and voice."""

from __future__ import annotations

import itertools

import numpy as np
import pytest

from tests.test_structure import grid
from woodshed import audio, parts, theory
from woodshed import sections as sc
from woodshed import structure as st


def line(text: str, energy_db: float = 0.0, sung: float | None = None) -> sc.Line:
    """ "C G | Am F | C G | F C": two beats per chord name in a 4/4 bar."""
    bars = []
    for bar in text.split("|"):
        names = bar.split()
        counts: sc.BarChords = {}
        for name in names:
            parsed = theory.parse_label(name)
            if parsed is not None:
                counts[parsed] = counts.get(parsed, 0) + 4 // len(names)
        bars.append(counts)
    return sc.Line(bars, energy_db, sung)


def names(lines: list[sc.Line]) -> list[tuple[str, int, int]]:
    return [(name, a, b) for a, b, name, _, _ in sc.find(lines)]


VERSE = "C G | Am F | C G | F C"
CHORUS = "Am G | F C | C G | C"
BREAK = "F C | G F C | Fm | G C"


def test_a_verse_and_chorus_song_is_named_like_the_band_would() -> None:
    # A piano ballad as woodshed charts it, line by line: no part is louder than another.
    chart = [VERSE, "C G | Am F | C G | C", "C G | Am F | C G | F", CHORUS, VERSE, VERSE, "Am G | F C | C G | F C",
             "Am G | F C | C G | F", BREAK, "C G | Am F | C G | F", VERSE, "Am G | F C | C G | F C",
             "C G | Am F | C G | F N"]  # fmt: skip
    lines = [line(t) for t in chart]
    assert names(lines) == [
        ("Verse 1", 0, 3),
        ("Chorus 1", 3, 4),
        ("Verse 2", 4, 6),
        ("Chorus 2", 6, 8),
        ("Bridge", 8, 9),
        ("Verse 3", 9, 11),
        ("Chorus 3", 11, 12),
        ("Outro", 12, 13),
    ]


def test_with_the_voice_the_intro_and_the_solo_are_found_and_the_form_stays() -> None:
    # The same ballad, with the share of sung beats measured on its vocal track: the piano intro
    # and the guitar solo are not sung. A chorus shares half its bars with the second verse line:
    # it must not take the verse's letter.
    chart = [VERSE, "C G | Am F | C G | C", "C G | Am F | C G | F", CHORUS, VERSE, VERSE, "Am G | F C | C G | F C",
             "Am G | F C | C G | F", BREAK, "C G | Am F | C G | F", VERSE, "Am G | F C | C G | F C",
             "C G | Am F | C G | F N"]  # fmt: skip
    sung = [0.03, 0.71, 0.76, 0.68, 0.71, 0.69, 0.67, 0.65, 0.0, 0.0, 0.12, 0.73, 0.73]
    lines = [line(t, sung=v) for t, v in zip(chart, sung, strict=True)]
    assert [n for n, _, _ in names(lines)] == [
        "Intro", "Verse 1", "Chorus 1", "Verse 2", "Chorus 2", "Instrumental", "Verse 3", "Chorus 3", "Outro",
    ]  # fmt: skip


def test_the_loudest_repeated_part_is_the_chorus_and_what_leads_to_it_the_pre_chorus() -> None:
    quiet, build, loud = -18.0, -9.0, -5.0
    lines = [
        line("Ab | Ab | Ab | Ab", -26),
        line("Db | Ab | Gb Ab | Ab", quiet),
        line("Db | Ab | Gb Ab | Ab", quiet),
        line("Bbm | Ab | Gbm | Gbm", build),
        line("Db | Ab | Gb | Gb", loud),
        line("Db | Ab | Gb | Gb", loud),
        line("Db | Ab | Gb Db | Db", quiet),
        line("Db | Fm | Gb Fm | Fm", quiet),
        line("Bbm | Ab | Gbm | Gbm", build),
        line("Db | Ab | Gb | Gb", loud),
        line("Db | Ab | Gb | Gb", loud),
    ]
    assert [n for n, _, _ in names(lines)] == [
        "Intro",
        "Verse 1",
        "Pre-chorus 1",
        "Chorus 1",
        "Verse 2",
        "Pre-chorus 2",
        "Chorus 2",
    ]


def test_an_unsung_first_line_is_the_intro_even_with_the_verse_chords() -> None:
    lines = [line(VERSE, sung=0.0), line(VERSE, sung=0.9), line(CHORUS, sung=0.9), line(VERSE, sung=0.8),
             line(CHORUS, sung=0.9), line(CHORUS, sung=0.9)]  # fmt: skip
    assert [n for n, _, _ in names(lines)][:2] == ["Intro", "Verse 1"]


def test_a_quiet_first_line_is_the_intro() -> None:
    lines = [line(VERSE, -20), line(VERSE, -6), line(VERSE, -6), line(CHORUS, -3), line(VERSE, -6), line(CHORUS, -3),
             line(CHORUS, -3)]  # fmt: skip
    assert [n for n, _, _ in names(lines)] == ["Intro", "Verse 1", "Chorus 1", "Verse 2", "Chorus 2"]


def test_without_repeats_the_parts_are_only_lettered() -> None:
    lines = [line("C | C | C | C"), line("D | D | D | D"), line("E | E | E | E")]
    assert [n for n, _, _ in names(lines)] == ["Part A", "Part B", "Part C"]


def test_two_lines_taking_turns_are_one_section() -> None:
    a, b = "Db | Gb Ab | Db Ebm | Gb Ab", "Fm Gb | Ab | Fm Gb | Ab"
    lines = [line(a), line(b), line(a), line(b), line(CHORUS, 6), line(CHORUS, 6), line(a), line(b), line(CHORUS, 6),
             line(CHORUS, 6)]  # fmt: skip
    assert names(lines)[:2] == [("Verse 1", 0, 4), ("Chorus 1", 4, 6)]


def test_a_lone_line_joins_the_neighbour_it_sounds_like() -> None:
    lines = [line(VERSE), line(VERSE), line("C G | Am F | Dm G | C"), line(CHORUS, 5), line(VERSE), line(VERSE),
             line(CHORUS, 5)]  # fmt: skip
    assert names(lines)[0] == ("Verse 1", 0, 3)


def test_a_part_heard_once_with_no_voice_is_instrumental() -> None:
    sung = 0.9
    lines = [line(VERSE, sung=sung), line(CHORUS, 4, sung), line(VERSE, sung=sung), line(CHORUS, 4, sung),
             line("E | E | A | A", sung=0.05), line(CHORUS, 4, sung), line(VERSE, sung=sung)]  # fmt: skip
    assert [n for n, _, _ in names(lines)][4] == "Instrumental"


def test_names_are_numbered_only_when_a_part_comes_back() -> None:
    roles = ["intro", "verse", "chorus", "verse", "chorus", "bridge", "chorus", "outro"]
    assert sc.name_sections(roles, [0, 1, 2, 1, 2, 3, 2, 4]) == [
        "Intro", "Verse 1", "Chorus 1", "Verse 2", "Chorus 2", "Bridge", "Chorus 3", "Outro",
    ]  # fmt: skip


def test_no_line_no_section() -> None:
    assert sc.find([]) == []


@pytest.mark.parametrize("n_lines", [1, 2, 7])
def test_sections_cover_every_line_in_order(n_lines: int) -> None:
    rng = np.random.default_rng(n_lines)
    pool = [VERSE, CHORUS, BREAK, "D | D | G | A"]
    lines = [line(pool[int(rng.integers(len(pool)))], float(rng.uniform(-20, 0))) for _ in range(n_lines)]
    found = sc.find(lines)
    assert found[0][0] == 0 and found[-1][1] == n_lines
    assert all(a[1] == b[0] for a, b in itertools.pairwise(found))


@pytest.mark.parametrize("per_bar", [4, 3])
def test_a_section_never_hides_inside_a_repeat_sign(per_bar: int) -> None:
    # One chord all through, quiet then loud: identical lines, yet the loud part starts its own
    # line on the page (it would collapse into a repeat of the quiet one without sections).
    beats = per_bar * 4 * 4  # four lines
    labels = ["C"] * (2 * beats)
    energy = np.array([-14.0] * beats + [-3.0] * beats)
    s = st.build(grid(labels), labels, np.zeros(len(labels), bool), None, [], 0, per_bar, energy_db=energy)
    assert [(sec.start, sec.end) for sec in s.sections] == [(0, 16), (16, 32)]
    for sec in s.sections:
        assert s.groups[s.bars[sec.start].group].occurrences[0][0] == sec.start  # starts its own group
    assert len(s.groups) == 2  # each part shown once with its repeat sign, not one group for both


def test_an_intro_riff_played_again_as_the_outro_is_not_a_verse() -> None:
    riff, pre, chorus, bridge = "E | E | A | E", "C#m | A | B | B", "A E | B | A E | B", "C#m | B | A | A"
    lines = [line(riff, -14, 0.0), line(VERSE, -9, 0.8), line(VERSE, -9, 0.8), line(pre, -7, 0.8),
             line(chorus, -3, 0.9), line(chorus, -3, 0.9), line(VERSE, -9, 0.8), line(VERSE, -9, 0.8),
             line(pre, -7, 0.8), line(chorus, -3, 0.9), line(chorus, -3, 0.9), line(bridge, -6, 0.8),
             line(chorus, -3, 0.9), line(chorus, -3, 0.9), line(riff, -14, 0.0)]  # fmt: skip
    assert [n for n, _, _ in names(lines)] == [
        "Intro", "Verse 1", "Pre-chorus 1", "Chorus 1", "Verse 2", "Pre-chorus 2", "Chorus 2", "Bridge", "Chorus 3",
        "Outro",
    ]  # fmt: skip


def test_a_song_on_one_chord_loop_is_cut_by_its_loudness() -> None:
    loop = "Em | C | G | D"
    lines = [line(loop, e) for e in (-12, -12, -3, -3, -12, -12, -3, -3)]
    assert names(lines) == [("Verse 1", 0, 2), ("Chorus 1", 2, 4), ("Verse 2", 4, 6), ("Chorus 2", 6, 8)]


def test_a_twelve_bar_blues_is_one_section_a_round() -> None:
    rounds = ["A | A | A | A", "D | D | A | A", "E | D | A | E"] * 4
    found = names([line(t) for t in rounds])
    assert [(a, b) for _, a, b in found] == [(0, 3), (3, 6), (6, 9), (9, 12)]
    assert len({n.split()[0] for n, _, _ in found}) == 1  # the same part each round


def test_a_last_chorus_of_one_line_is_still_a_chorus() -> None:
    lines = [line(VERSE, -8), line(VERSE, -8), line(CHORUS, -3), line(VERSE, -8), line(VERSE, -8), line(CHORUS, -3)]
    assert [n for n, _, _ in names(lines)] == ["Verse 1", "Chorus 1", "Verse 2", "Chorus 2"]


def test_the_voice_is_found_beat_by_beat() -> None:
    sr = audio.SR
    beat = 0.5
    t = np.arange(int(4 * sr)) / sr
    voice = np.where(t >= 2.0, 0.3 * np.sin(2 * np.pi * 440 * t), 1e-4 * np.sin(2 * np.pi * 440 * t))
    share = parts.vocal_activity(voice.astype(np.float32), np.arange(0, 4, beat))
    assert float(np.max(share[:4])) < 0.1 and float(np.min(share[4:])) > 0.9
    assert parts.vocal_activity(np.zeros(sr, np.float32), np.arange(0, 1, beat)).sum() == 0


def test_a_one_line_verse_pre_chorus_and_chorus_are_not_a_blues_round() -> None:
    pre, chorus = "F | G | F | G", "Am G | F C | C G | C"
    lines = [line(t, e, 0.8) for _ in range(3) for t, e in ((VERSE, -10), (pre, -7), (chorus, -3))]
    assert [n.split()[0] for n, _, _ in names(lines)][1:4] == ["Pre-chorus", "Chorus", "Verse"]


def test_a_soft_recording_with_a_quiet_vocal_track_is_not_called_unsung() -> None:
    chart = [VERSE, VERSE, CHORUS, CHORUS, VERSE, VERSE, CHORUS, CHORUS, BREAK, CHORUS, CHORUS]
    energies = [-10, -10, -4, -4, -10, -10, -4, -4, -7, -4, -4]
    quiet = [line(t, e, 0.0) for t, e in zip(chart, energies, strict=True)]  # the voice under the floor
    unknown = [line(t, e) for t, e in zip(chart, energies, strict=True)]
    assert names(quiet) == names(unknown)
    assert [n for n, _, _ in names(quiet)][:2] == ["Verse 1", "Chorus 1"]


def test_a_louder_last_verse_is_still_a_verse() -> None:
    lines = [line(VERSE, -10), line(VERSE, -10), line(CHORUS, -3), line(VERSE, -10), line(VERSE, -10),
             line(CHORUS, -3), line(VERSE, -4), line(VERSE, -4), line(CHORUS, -3), line(CHORUS, -3)]  # fmt: skip
    assert [n for n, _, _ in names(lines)] == ["Verse 1", "Chorus 1", "Verse 2", "Chorus 2", "Verse 3", "Chorus 3"]
