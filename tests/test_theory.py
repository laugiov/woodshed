"""Music theory: spelling, transposition, roman numerals, named progressions, capo."""

from __future__ import annotations

import pytest

from woodshed import theory as th

MAJOR_DIATONIC = [(0, ""), (2, "m"), (4, "m"), (5, ""), (7, ""), (9, "m")]


def diatonic(key_pc: int) -> list[str]:
    return [th.chord_name((key_pc + iv) % 12, q, th.Key(key_pc, "maj")) for iv, q in MAJOR_DIATONIC]


@pytest.mark.parametrize(
    ("key_pc", "expected"),
    [
        (0, ["C", "Dm", "Em", "F", "G", "Am"]),
        (7, ["G", "Am", "Bm", "C", "D", "Em"]),
        (2, ["D", "Em", "F#m", "G", "A", "Bm"]),
        (9, ["A", "Bm", "C#m", "D", "E", "F#m"]),
        (4, ["E", "F#m", "G#m", "A", "B", "C#m"]),
        (11, ["B", "C#m", "D#m", "E", "F#", "G#m"]),
        (6, ["F#", "G#m", "A#m", "B", "C#", "D#m"]),
        (5, ["F", "Gm", "Am", "Bb", "C", "Dm"]),
        (10, ["Bb", "Cm", "Dm", "Eb", "F", "Gm"]),
        (3, ["Eb", "Fm", "Gm", "Ab", "Bb", "Cm"]),
        (8, ["Ab", "Bbm", "Cm", "Db", "Eb", "Fm"]),
        (1, ["Db", "Ebm", "Fm", "Gb", "Ab", "Bbm"]),
    ],
)
def test_every_major_key_is_spelled_like_a_songbook(key_pc: int, expected: list[str]) -> None:
    assert diatonic(key_pc) == expected


@pytest.mark.parametrize("tonic", range(12))
def test_minor_keys_follow_their_relative_major(tonic: int) -> None:
    minor, relative = th.Key(tonic, "min"), th.Key((tonic + 3) % 12, "maj")
    for pc in range(12):
        assert th.spell(pc, minor) == th.spell(pc, relative)


@pytest.mark.parametrize(
    ("pc", "key", "expected"),
    [(10, th.Key(0, "maj"), "Bb"), (8, th.Key(0, "maj"), "Ab"), (3, th.Key(0, "maj"), "Eb"),  # bVII bVI bIII in C
     (6, th.Key(0, "maj"), "F#"), (1, th.Key(0, "maj"), "Db"),  # #IV and bII in C
     (5, th.Key(7, "maj"), "F"), (10, th.Key(7, "maj"), "Bb"),  # bVII and bIII in G
     (2, th.Key(4, "maj"), "D"), (7, th.Key(4, "maj"), "G"),  # bVII and bIII in E: lowered sharps become naturals
     (4, th.Key(8, "maj"), "E"), (11, th.Key(1, "maj"), "B")],  # no Fb or Cb in a chart
)  # fmt: skip
def test_borrowed_chord_roots_are_spelled_by_degree(pc: int, key: th.Key, expected: str) -> None:
    assert th.chord_name(pc, "", key) == expected


def test_single_notes_keep_the_key_accidentals() -> None:
    # A chromatic bass note under F in A-flat major is an E, not an F-flat.
    assert th.spell(4, th.Key(8, "maj")) == "E"
    assert th.spell(7, th.Key(8, "maj")) == "G"


def test_forcing_sharps_or_flats() -> None:
    key = th.Key(8, "maj")
    assert th.spell(8, key, prefer="sharps") == "G#"
    assert th.spell(1, th.Key(4, "maj"), prefer="flats") == "Db"


@pytest.mark.parametrize("n", range(-11, 12))
def test_transposition_round_trips(n: int) -> None:
    for pc in range(12):
        assert th.transpose(th.transpose(pc, n), -n) == pc


@pytest.mark.parametrize(
    ("pc", "q", "key", "expected"),
    [(0, "", th.Key(0, "maj"), "I"), (7, "", th.Key(0, "maj"), "V"), (9, "m", th.Key(0, "maj"), "vi"),
     (10, "", th.Key(0, "maj"), "bVII"), (5, "m", th.Key(0, "min"), "iv"), (8, "", th.Key(0, "min"), "bVI"),
     (2, "7", th.Key(0, "maj"), "II7"), (2, "m7", th.Key(0, "maj"), "ii7")],
)  # fmt: skip
def test_roman_numerals(pc: int, q: str, key: th.Key, expected: str) -> None:
    assert th.roman(pc, q, key) == expected


@pytest.mark.parametrize(
    ("romans", "fragment"),
    [
        (["I", "V", "vi", "IV"], "most common one in pop"),
        (["vi", "IV", "I", "V"], "started on the vi"),
        (["I", "vi", "IV", "V"], "1950s progression"),
        (["ii", "V", "I"], "ii-V-I"),
        (["I", "V", "vi", "IV", "I", "V", "IV", "I"], "most common one in pop"),
    ],
)
def test_named_progressions(romans: list[str], fragment: str) -> None:
    name = th.named_progression(romans)
    assert name is not None and fragment in name


def test_unknown_progression_has_no_name() -> None:
    assert th.named_progression(["I", "bII", "#IV"]) is None


def chords(*spec: tuple[int, str, int]) -> list[th.TimedChord]:
    return [th.TimedChord(pc, q, beats) for pc, q, beats in spec]


def test_capo_suggested_when_it_turns_barre_chords_into_open_shapes() -> None:
    # Ab - Fm - Db - Bbm - Eb: all barre chords; capo 1 gives G - Em - C - Am - D.
    song = chords((8, "", 8), (5, "m", 8), (1, "", 8), (10, "m", 4), (3, "", 4))
    assert th.suggest_capo(song) == 1


def test_no_capo_for_a_song_that_is_already_easy() -> None:
    # C - G - Am - F: F counts as an easy small barre, so no capo.
    song = chords((0, "", 8), (7, "", 8), (9, "m", 8), (5, "", 8))
    assert th.suggest_capo(song) == 0


def test_capo_suggestion_is_deterministic_and_bounded() -> None:
    song = chords((1, "", 4), (6, "", 4), (8, "", 4))
    results = {th.suggest_capo(song) for _ in range(5)}
    assert len(results) == 1 and 0 <= results.pop() <= 7


def test_parse_label() -> None:
    assert th.parse_label("A#m7") == (10, "m7")
    assert th.parse_label("Bbm") == (10, "m")
    assert th.parse_label("N") is None


@pytest.mark.parametrize("key", [th.Key(0, "maj"), th.Key(9, "min")])
def test_a_loop_has_the_same_name_in_the_major_and_the_relative_minor(key: th.Key) -> None:
    loop = [(9, "m"), (5, ""), (0, ""), (7, "")]  # Am F C G
    name = th.progression_name(loop, key)
    assert name is not None and "I-V-vi-IV" in name


@pytest.mark.parametrize(("label", "parsed"), [("Cb", (11, "")), ("E#m", (5, "m")), ("Fb7", (4, "7")), ("B#", (0, ""))])
def test_enharmonic_labels_parse(label: str, parsed: tuple[int, str]) -> None:
    assert th.parse_label(label) == parsed


def test_a_non_chord_label_is_rejected() -> None:
    with pytest.raises(ValueError, match="not a chord"):
        th.parse_label("H7")


def test_a_major_seventh_keeps_an_upper_case_numeral() -> None:
    assert th.roman(0, "maj7", th.Key(0)) == "Imaj7"
    assert th.roman(9, "m7", th.Key(0)) == "vi7"
    assert th.roman(7, "7", th.Key(0)) == "V7"


@pytest.mark.parametrize("mode", ["maj", "min"])
def test_no_root_in_any_key_needs_a_double_accidental(mode: str) -> None:
    for tonic in range(12):
        key = th.Key(tonic, mode)  # type: ignore[arg-type]
        for pc in range(12):
            name = th.spell_root(pc, key)
            assert th.parse_label(name) == (pc, ""), (key, pc, name)
            assert not name.endswith(("bb", "##")) and len(name) <= 2


def test_the_flat_second_of_a_flat_key_is_spelled_plainly() -> None:
    assert th.spell_root(9, th.Key(8)) == "A"  # bII of Ab: A, not Bbb
