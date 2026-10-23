"""The keys panel tells the truth (spec 015): no chord said as such, the guitar's rhythm named as the
guitar's, no voicings promised when no keys are heard, and the readings of the record checked
against the chart."""

from __future__ import annotations

import re
from typing import Any

import pytest
from playwright.sync_api import Locator, expect

NBSP = "\u00a0"


def french() -> pytest.MarkDecorator:
    return pytest.mark.browser_context_args(locale="fr-FR")


def keys_at(o: Any, bar: int) -> Locator:
    """The keys panel, stopped on `bar` (0-based)."""
    o.js("Woodshed.app.setInstrument('piano')")
    o.js("(u) => Woodshed.app.seekBar(u)", bar)
    desk: Locator = o.page.get_by_test_id("desk")
    return desk


def hint(desk: Locator) -> str:
    return str(desk.locator(".piano-wrap > .hint").text_content())


def rhythm_head(desk: Locator) -> Locator:
    return desk.locator(".label.subhead").filter(has_text=re.compile("Rhythm|Rythme"))


# R1: a bar with no chord.


def test_a_bar_with_no_chord_says_so_and_names_the_next(open_page: Any) -> None:
    o = open_page("pop", variant="keys-readings")
    desk = keys_at(o, 4)
    assert hint(desk) == "Now: no chord. Orange outline: the next chord, Gsus4."
    expect(desk.get_by_test_id("hear-keys")).to_have_count(0)
    expect(desk.get_by_role("button", name="Note by note")).to_have_count(0)
    expect(desk.locator(".pc-chip.bassnote")).to_have_count(0)
    assert o.js("document.querySelectorAll('[data-testid=keyboard] rect[fill=\"var(--accent)\"]').length") == 0


def test_a_bar_with_a_chord_keeps_its_root_position_hint(open_page: Any) -> None:
    o = open_page("pop")
    desk = keys_at(o, 0)
    assert hint(desk) == "Now: C in root position. Orange outline: the next chord, G."


@french()
def test_no_chord_in_french(open_page: Any) -> None:
    o = open_page("pop", variant="keys-readings")
    desk = keys_at(o, 4)
    assert hint(desk) == f"Maintenant{NBSP}: pas d'accord. Contour orange{NBSP}: l'accord suivant, Gsus4."


# R2: the rhythm in the keys panel read from the guitar is said to be the guitar's.

GUITAR_NOTE = re.compile(
    r"^From the isolated guitar track: chords on .+\. Bigger dot: hit in more bars\."
    r" The keys' own rhythm is not read\.$"
)


def test_the_keys_panel_names_the_guitars_strumming(open_page: Any) -> None:
    o = open_page("pop", six=True)
    desk = keys_at(o, 0)
    expect(rhythm_head(desk)).to_have_text("Rhythm: the guitar's strumming")
    expect(desk.locator("#compGrid")).to_be_visible()  # the grid is kept
    expect(desk.locator(".src-note").last).to_have_text(GUITAR_NOTE)


def test_with_no_keys_heard_the_keys_panel_still_names_the_guitars_strumming(open_page: Any) -> None:
    o = open_page("pop", six=False)
    desk = keys_at(o, 0)
    expect(desk.get_by_test_id("voicing-not-heard")).to_have_text("No keys heard in this song.")
    expect(rhythm_head(desk)).to_have_text("Rhythm: the guitar's strumming")
    expect(desk.locator(".src-note").last).to_have_text(GUITAR_NOTE)


def test_the_guitar_panel_keeps_its_rhythm_heading(open_page: Any) -> None:
    o = open_page("pop", six=True)
    o.js("Woodshed.app.setInstrument('guitar')")
    desk = o.page.get_by_test_id("desk")
    expect(rhythm_head(desk)).to_have_text("Rhythm: when the chords hit")
    expect(desk).not_to_contain_text("The keys' own rhythm is not read.")


def test_the_strumming_read_from_the_keys_keeps_its_rhythm_heading(open_page: Any) -> None:
    o = open_page("pop", six=True, guitar=False)  # the strumming read from the keys themselves
    desk = keys_at(o, 0)
    expect(rhythm_head(desk)).to_have_text("Rhythm: when the chords hit")
    expect(desk).not_to_contain_text("The keys' own rhythm is not read.")


def test_four_stems_keep_their_rhythm_heading(open_page: Any) -> None:
    o = open_page("pop")  # four stems: keys and guitar are one track
    desk = keys_at(o, 0)
    expect(rhythm_head(desk)).to_have_text("Rhythm: when the chords hit")
    expect(desk).to_contain_text("From the isolated keys and guitar track")


@french()
def test_the_guitars_strumming_in_french(open_page: Any) -> None:
    o = open_page("pop", six=True)
    desk = keys_at(o, 0)
    assert rhythm_head(desk).text_content() == f"Rythme{NBSP}: celui de la guitare"
    note = str(desk.locator(".src-note").last.text_content())
    assert note.startswith(f"D'après la piste séparée de la guitare{NBSP}: accords sur ")
    assert note.endswith(f"{NBSP}: frappé dans plus de mesures. Le rythme propre des claviers n'est pas lu.")


# R3: keys not heard, step 2 promises no voicings.


def step_two(o: Any) -> tuple[str, str]:
    card = o.page.get_by_test_id("step-2")
    return str(card.locator(".t").text_content()), str(card.locator(".d").text_content())


def test_with_no_keys_heard_step_two_is_learning_the_chords(open_page: Any) -> None:
    o = open_page("pop", six=False)
    o.js("Woodshed.app.setInstrument('piano')")
    assert step_two(o) == ("Learn the chords", "The chords of the chart, with the panel on the right.")
    o.js("Woodshed.app.setInstrument('guitar')")  # the guitar is heard: its card as it was
    assert step_two(o) == ("Learn the shapes", "Your part alone. Click a shape to hear it.")


def test_with_keys_heard_step_two_is_still_the_voicings(open_page: Any) -> None:
    o = open_page("pop", six=True)
    o.js("Woodshed.app.setInstrument('piano')")
    assert step_two(o) == ("Learn the voicings", "The chords alone, as played on the record.")


@french()
def test_learning_the_chords_in_french(open_page: Any) -> None:
    o = open_page("pop", six=False)
    o.js("Woodshed.app.setInstrument('piano')")
    assert step_two(o) == ("Apprendre les accords", "Les accords de la grille, avec le panneau à droite.")


# R4: "On the record, this bar", checked against the chart.


def check_line(note: str, chord: str) -> str:
    return f"The record has {note} here, the chart says {chord}: check this bar by ear."


VERDICT = "([cur, chords, pcs]) => Woodshed.instruments.voicingVerdict(cur, chords, pcs)"


def verdict(o: Any, chords: list[tuple[int, str]], pcs: list[int]) -> object:
    made = [{"pc": pc, "quality": q, "beats": 4 // len(chords)} for pc, q in chords]
    return o.js(VERDICT, [made[0], made, pcs])


def test_the_reading_verdict_of_a_bar(open_page: Any) -> None:
    o = open_page("pop")
    assert verdict(o, [(9, "m")], []) == "none"
    assert verdict(o, [(-1, "")], []) == "none"
    assert verdict(o, [(7, "")], [7]) == "root"
    assert verdict(o, [(7, ""), (2, "")], [7]) is None  # two chords: the playhead's root is not the bar's
    assert verdict(o, [(9, "m")], [1, 4]) == {"other": 1}  # Am, a major third heard
    assert verdict(o, [(11, "m7")], [3, 9]) == {"other": 3}  # Bm7, D sharp heard
    assert verdict(o, [(5, "")], [8, 0]) == {"other": 8}  # F, a minor third heard
    assert verdict(o, [(5, "maj7")], [8, 4]) == {"other": 8}
    assert verdict(o, [(9, "m")], [0, 4]) is None  # the chart's own third
    assert verdict(o, [(5, "")], [8, 9, 0]) is None  # both thirds
    assert verdict(o, [(7, "sus4")], [10, 2]) is None  # no third to contradict
    assert verdict(o, [(7, "5")], [10, 2]) is None
    assert verdict(o, [(-1, "")], [1, 4]) is None  # no chord
    assert verdict(o, [(9, "m"), (5, "")], [1, 4]) is None  # two chords in the bar
    assert verdict(o, [(9, "m")], [0, 4, 9]) is None  # a plain reading


def test_no_upper_note_heard_says_so_without_chips(open_page: Any) -> None:
    o = open_page("pop", variant="keys-readings")
    desk = keys_at(o, 0)
    expect(desk.get_by_test_id("voicing-none")).to_have_text("No upper notes heard on the record in this bar.")
    expect(desk.locator(".pc-chip")).to_have_count(0)
    expect(desk.get_by_test_id("hear-voicing")).to_have_count(0)


def test_only_the_root_heard_is_a_quiet_statement(open_page: Any) -> None:
    o = open_page("pop", variant="keys-readings")
    desk = keys_at(o, 1)
    expect(desk.get_by_test_id("voicing-root")).to_have_text("Only the root heard here.")
    expect(desk.get_by_test_id("voicing-root")).to_have_class(re.compile(r"\bhint\b"))
    expect(desk.locator(".pc-chip")).to_have_count(0)  # no "G over G"
    expect(desk.get_by_test_id("hear-voicing")).to_be_visible()


def test_the_other_third_heard_is_said_under_the_chips(open_page: Any) -> None:
    o = open_page("pop", variant="keys-readings")
    desk = keys_at(o, 2)
    # The major third of A is C sharp, not D flat: a third is spelled as a third of the chart's root.
    expect(desk.get_by_test_id("voicing-check")).to_have_text(check_line("C♯", "Am"))
    expect(desk.locator(".chips-row .pc-chip")).to_have_count(3)  # the chips as heard, over the root
    expect(desk.locator(".chips-row .pc-chip").first).to_have_text("C♯")  # the chip agrees with the line
    expect(desk.get_by_test_id("hear-voicing")).to_be_visible()
    desk = keys_at(o, 3)
    expect(desk.get_by_test_id("voicing-check")).to_have_text(check_line("A♭", "F"))
    expect(desk.locator(".chips-row .pc-chip").first).to_have_text("A♭")


def test_the_other_third_follows_the_transposition(open_page: Any) -> None:
    o = open_page("pop", variant="keys-readings")
    o.js("Woodshed.app.transposeTo(2)")  # compared before transposition, said in the new key
    desk = keys_at(o, 2)
    expect(desk.get_by_test_id("voicing-check")).to_have_text(check_line("D♯", "Bm"))
    expect(desk.locator(".chips-row .pc-chip").first).to_have_text("D♯")


def test_the_other_third_is_spelled_from_the_chords_own_root(open_page: Any) -> None:
    o = open_page("lift", variant="keys-lift")
    desk = keys_at(o, 17)
    expect(desk.get_by_test_id("voicing-check")).to_have_text(check_line("G♭", "E♭"))
    expect(desk.locator(".chips-row .pc-chip").first).to_have_text("G♭")


def test_a_third_is_two_letters_above_the_root(open_page: Any) -> None:
    o = open_page("pop")
    third = "([root, semis]) => Woodshed.instruments.thirdName(root, semis)"
    cases = {("A", 4): "C#", ("B", 4): "D#", ("F", 3): "Ab", ("Eb", 3): "Gb", ("C#", 3): "E", ("Bb", 4): "D"}
    for (root, semis), name in cases.items():
        assert o.js(third, [root, semis]) == name, (root, semis)
    assert o.js(third, ["D#", 4]) is None  # F double sharp: the caller falls back to the plain name
    assert o.js(third, ["Gb", 3]) is None  # B double flat


@pytest.mark.parametrize("bar", [4, 5, 6, 7], ids=["no-chord", "sus4", "two-chords", "both-thirds"])
def test_readings_with_nothing_to_check_are_shown_as_heard(open_page: Any, bar: int) -> None:
    o = open_page("pop", variant="keys-readings")
    desk = keys_at(o, bar)
    expect(desk.get_by_test_id("hear-voicing")).to_be_visible()
    expect(desk.locator(".chips-row .pc-chip").first).to_be_visible()
    for verdict_id in ("voicing-check", "voicing-root", "voicing-none"):
        expect(desk.get_by_test_id(verdict_id)).to_have_count(0)


def test_a_plain_reading_is_unchanged(open_page: Any) -> None:
    o = open_page("pop")
    desk = keys_at(o, 2)
    expect(desk.locator(".chips-row .pc-chip")).to_have_count(4)  # C E A over A
    expect(desk.locator(".chips-row")).to_contain_text("over")
    for verdict_id in ("voicing-check", "voicing-root", "voicing-none"):
        expect(desk.get_by_test_id(verdict_id)).to_have_count(0)


@french()
def test_the_readings_in_french(open_page: Any) -> None:
    o = open_page("pop", variant="keys-readings")
    said = {
        0: ("voicing-none", "Aucune note du haut entendue sur le disque dans cette mesure."),
        1: ("voicing-root", "Seule la fondamentale s'entend ici."),
        2: ("voicing-check", f"Le disque a C♯ ici, la grille dit Am{NBSP}: vérifie cette mesure à l'oreille."),
    }
    for bar, (testid, text) in said.items():
        desk = keys_at(o, bar)
        expect(desk.get_by_test_id(testid)).to_be_visible()
        assert desk.get_by_test_id(testid).text_content() == text


# The keys read thin: said once for the song, under "On the record", from a quarter of the bars.


def thin_line(n: int, m: int) -> str:
    return (
        f"The keys read thin on this song: one note in {n} of {m} bars."
        " Where only one is heard, play the chart's chord."
    )


def test_keys_read_thin_on_a_quarter_of_the_bars_is_said_for_the_song(open_page: Any) -> None:
    o = open_page("pop", variant="keys-thin")
    m = int(str(o.js("Woodshed.current.bars.length")))
    n = (m + 3) // 4
    for bar in (0, m - 1):  # the same note on a one-note bar and on a full one
        desk = keys_at(o, bar)
        expect(desk.get_by_test_id("keys-thin")).to_have_count(1)
        expect(desk.get_by_test_id("keys-thin")).to_have_text(thin_line(n, m))
        expect(desk.get_by_test_id("keys-thin").locator("xpath=..")).to_have_class(re.compile(r"\bsrc-note\b"))


@pytest.mark.parametrize("variant", ["keys-thin-below", "keys-readings"])
def test_keys_read_thin_below_a_quarter_of_the_bars_says_nothing(open_page: Any, variant: str) -> None:
    o = open_page("pop", variant=variant)
    desk = keys_at(o, 1)
    expect(desk.locator(".chips-row, [data-testid=voicing-root]").first).to_be_visible()
    expect(desk.get_by_test_id("keys-thin")).to_have_count(0)


@french()
def test_keys_read_thin_in_french(open_page: Any) -> None:
    o = open_page("pop", variant="keys-thin")
    m = int(str(o.js("Woodshed.current.bars.length")))
    desk = keys_at(o, 0)
    assert desk.get_by_test_id("keys-thin").text_content() == (
        f"Les claviers s'entendent peu sur ce morceau{NBSP}: une seule note dans {(m + 3) // 4} mesures sur {m}."
        " Là où une seule s'entend, joue l'accord de la grille."
    )


# R6: French punctuation keeps to its word.


def test_no_french_text_breaks_before_its_punctuation(open_page: Any) -> None:
    """A colon, semicolon, question or exclamation mark takes a non-breaking space before it, never a
    plain one a line could break on (a URL, a time like 0:37 or a "{x}:" has none)."""
    o = open_page("pop")
    plain = o.js("Object.entries(Woodshed.FR).filter(([, fr]) => / [:;?!]/.test(fr)).map(([, fr]) => fr)")
    assert plain == []
    assert o.js(f"Object.values(Woodshed.FR).filter((fr) => /{NBSP}[:;?!]/.test(fr)).length") > 100
