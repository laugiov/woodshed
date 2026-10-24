"""The chord still sounding, at the start of every sung line (spec 027): in the Lyrics view a line whose first word
carries no chord of its own shows the chord playing there, small and muted ("C", "N.C."), so a line with no chord
never reads as "nothing found here". On the guitar and keys words stage, on the lines after the one sung; never on
the singer's stage. A screen reader hears each line's opening chord. The stage tests are marked `tablet` (also run in
WebKit)."""

from __future__ import annotations

import json
from typing import Any

import pytest
from playwright.sync_api import expect

from tests.page.test_singer_stage import at, on_stage, sized

NBSP = "\u00a0"

# Per sung line of the sheet (or of the stage), the visible text of its reminders (None: no reminder).
REMINDERS = """(sel) => [...document.querySelectorAll(sel)].map((line) => {
  const found = [...line.querySelectorAll('[data-testid="chord-reminder"]')];
  return found.length ? found.map((r) => r.querySelector('[aria-hidden="true"]').textContent) : null;
})"""
SHEET = '#sheet [data-testid="lyric-line"]'
STAGE = '#stLyrics [data-testid="stage-line"]'
# Per sung line of the sheet, what a screen reader hears of its opening chord (None: nothing).
SAID = """() => [...document.querySelectorAll('#sheet [data-testid="lyric-line"]')].map((line) => {
  const said = line.querySelectorAll('[data-testid="line-chord"]');
  return said.length ? [...said].map((x) => x.textContent) : null;
})"""


def reminders(o: Any, where: str = SHEET) -> list[list[str] | None]:
    found: list[list[str] | None] = o.js(REMINDERS, where)
    return found


def redraw(o: Any) -> None:
    o.js("Woodshed.app.store.set({corrections: Woodshed.app.store.get().corrections + 1})")


def bar_start(o: Any, u: int) -> float:
    start: float = o.js(f"Woodshed.current.bars[{u}].start")
    return start


# A1 (R1), A2 (R4)
def test_a_line_with_no_chord_of_its_own_shows_the_chord_still_sounding(open_page: Any) -> None:
    o = open_page("pop", variant="lyrics-vamp")
    expect(o.page.get_by_test_id("lyric-line")).to_have_count(6)
    # Line 1 opens on C, line 3 on the C to check, line 5 on N.C.: their own chords. Lines 2, 4 and 6 keep the
    # chord before them: it is shown, once each.
    assert reminders(o) == [None, ["C"], None, ["C"], None, ["N.C."]]


# A2 (R4) in French: N.C. is the band's word in both languages.
@pytest.mark.browser_context_args(locale="fr-FR")
def test_no_chord_is_n_c_in_french_too(open_page: Any) -> None:
    o = open_page("pop", variant="lyrics-vamp")
    assert reminders(o)[5] == ["N.C."]


# A3 (R2)
def test_the_reminder_is_named_as_the_line_chords_transposed_and_in_capo_shapes(open_page: Any) -> None:
    o = open_page("pop", variant="lyrics-vamp")
    o.js("Woodshed.app.transposeTo(2)")
    assert reminders(o)[1] == ["D"]
    o.js("Woodshed.app.transposeTo(0)")
    o.js("Woodshed.app.store.set({ capo: 3, pos: 'open', view: 'shapes' })")
    assert o.js("Woodshed.app.showShapes(Woodshed.app.store.get())")
    line_one = o.page.get_by_test_id("lyric-line").first.locator(".lw.has .lc").first
    expect(line_one).to_have_text("A")  # C, capo 3: the A shape
    assert reminders(o)[1] == ["A"]


# A4 (R2): the key region of the bar the line opens in, not the region of the bar where the chord began.
def test_a_chord_held_across_a_key_change_is_spelled_in_the_new_key(open_page: Any) -> None:
    o = open_page("lift", variant="lyrics-vamp-lift")
    lines = o.page.get_by_test_id("lyric-line")
    expect(lines).to_have_count(5)
    assert o.js("Array.from(document.querySelectorAll('#sheet [data-testid=lyric-line]'), (l) => +l.dataset.from)") == [
        14, 15, 16, 17, 18,
    ]  # fmt: skip
    expect(lines.nth(1).locator(".lw.has .lc").first).to_have_text("F♯")  # bar 16: its own change, in C
    # Bar 17 is sung 0.1 s early, on bar 16's chord (in C), and opens in D flat: G flat. Bar 18: G flat too.
    assert reminders(o) == [None, None, ["G♭"], ["G♭"], None]


# A5 (R9)
def test_a_correction_and_its_undo_redraw_the_reminder(open_page: Any) -> None:
    o = open_page("pop", variant="lyrics-vamp")
    o.js("Woodshed.app.correct(2, 0, { pc: 7, quality: '' })")  # bar 3 is G: bar 4's C is a change again
    assert reminders(o)[3] is None
    expect(o.page.get_by_test_id("lyric-line").nth(3).locator(".lw.has .lc").first).to_have_text("C")
    o.js("Woodshed.app.uncorrect(910)")
    assert reminders(o)[3] == ["C"]


STYLE = """(sel) => {
  const r = document.querySelector(sel);
  const chord = document.querySelector('#sheet [data-testid="lyric-line"] .lw.has .lc');
  const probe = document.createElement('span');
  probe.style.color = 'var(--muted)';
  document.body.append(probe);
  const muted = getComputedStyle(probe).color;
  probe.remove();
  const cs = getComputedStyle(r);
  return { ratio: parseFloat(cs.fontSize) / parseFloat(getComputedStyle(chord).fontSize), color: cs.color, muted,
           weight: cs.fontWeight, shown: r.getBoundingClientRect().height > 0 && cs.display !== 'none' };
}"""
FIRST_REMINDER = '#sheet [data-testid="chord-reminder"] [aria-hidden="true"]'


# A6 (R3)
@pytest.mark.parametrize("theme", ["dark", "light"])
def test_the_reminder_is_small_and_muted(open_page: Any, theme: str) -> None:
    o = open_page("pop", variant="lyrics-vamp")
    o.js(f"document.documentElement.dataset.theme = '{theme}'")
    style = o.js(STYLE, FIRST_REMINDER)
    assert style["ratio"] == pytest.approx(0.72, abs=0.01)
    assert style["color"] == style["muted"]
    assert style["weight"] == "500"


# A10 (R8)
def test_the_reminder_is_printed_in_the_paper_grey(open_page: Any) -> None:
    o = open_page("pop", variant="lyrics-vamp")
    o.page.emulate_media(media="print")
    style = o.js(STYLE, FIRST_REMINDER)
    assert style["shown"]
    assert style["color"] == "rgb(68, 68, 68)"
    assert style["ratio"] == pytest.approx(0.82, abs=0.01)
    legend = o.js(
        "parseFloat(getComputedStyle(document.querySelector('[data-testid=chord-reminder-legend]')).fontSize)"
    )
    assert legend == pytest.approx(10.5, abs=0.1)


GAP = """(line) => {
  const r = line.querySelector('[data-testid="chord-reminder"] [aria-hidden="true"]').getBoundingClientRect();
  const next = line.querySelectorAll('.lw')[1].querySelector('.lc').getBoundingClientRect();
  return next.left - r.right;
}"""
WIDENED = """(line) => {
  const w = line.querySelector('.lw');
  return w.getBoundingClientRect().width - w.querySelector('.wt').getBoundingClientRect().width;
}"""


# A7 (R5): never glued to the next chord, and the sung text keeps its spacing.
@pytest.mark.tablet
@pytest.mark.parametrize(("width", "height"), [(390, 844), (1440, 900)])
def test_the_reminder_never_touches_the_next_chord(open_page: Any, width: int, height: int) -> None:
    o = open_page("pop", variant="lyrics-vamp-glue")
    sized(o, width, height)
    lines = o.page.get_by_test_id("lyric-line")
    assert reminders(o)[1] == ["Cm7"] and reminders(o)[3] == ["Cm7"]
    assert lines.nth(1).evaluate(GAP) >= 4  # "a" with G on "road": the reminder takes its width
    assert lines.nth(3).evaluate(WIDENED) <= 1  # "I", nothing on "time": the reminder lies over the words
    # The guitar's words stage, stopped on line 1: line 2 comes next, with its reminder.
    on_stage(o, "Guitar")
    sized(o, width, height)
    at(o, bar_start(o, 0) + 0.3, playing=False)
    stage = o.page.locator(STAGE)
    assert reminders(o, STAGE)[1] == ["Cm7"]
    assert stage.nth(1).evaluate(GAP) >= 4


def test_the_first_word_keeps_its_width(open_page: Any) -> None:
    o = open_page("pop", variant="lyrics-vamp")
    assert o.page.get_by_test_id("lyric-line").nth(1).evaluate(WIDENED) <= 1


# A8 (R6): every line's first word says its chord; a reminder says it goes on.
def test_a_screen_reader_hears_the_chord_each_line_opens_on(open_page: Any) -> None:
    o = open_page("pop", variant="lyrics-vamp")
    # Line 3's chord to check is a control that already reads it: nothing more is said there.
    assert o.js(SAID) == [["C"], ["still C"], None, ["still C"], ["no chord"], ["still no chord"]]
    reminder = o.page.get_by_test_id("chord-reminder").first
    seen = reminder.locator('[aria-hidden="true"]')
    expect(seen).to_have_attribute("title", "Still C: the chord goes on from before")
    nc = o.page.get_by_test_id("chord-reminder").last.locator('[aria-hidden="true"]')
    expect(nc).to_have_attribute("title", "Still no chord: nothing played from before")


@pytest.mark.browser_context_args(locale="fr-FR")
def test_a_screen_reader_hears_it_in_french(open_page: Any) -> None:
    o = open_page("pop", variant="lyrics-vamp")
    assert o.js(SAID) == [["C"], ["toujours C"], None, ["toujours C"], ["pas d'accord"], ["toujours sans accord"]]
    seen = o.page.get_by_test_id("chord-reminder").first.locator('[aria-hidden="true"]')
    expect(seen).to_have_attribute("title", f"Toujours C{NBSP}: l'accord continue d'avant")
    nc = o.page.get_by_test_id("chord-reminder").last.locator('[aria-hidden="true"]')
    expect(nc).to_have_attribute("title", f"Toujours sans accord{NBSP}: rien de joué depuis avant")


# The legend (no hover on a touch screen): one muted line above the first sung line.
def test_a_legend_says_what_the_grey_chord_is(open_page: Any) -> None:
    o = open_page("pop", variant="lyrics-vamp")
    legend = o.page.get_by_test_id("chord-reminder-legend")
    expect(legend).to_have_text("Grey chord: still sounding from before.")
    expect(legend).to_have_attribute("aria-hidden", "true")  # a screen reader hears "still C" on the line itself
    assert (
        o.js("document.querySelector('[data-testid=chord-reminder-legend]').nextElementSibling.dataset.testid")
        == "lyric-line"
    )


@pytest.mark.browser_context_args(locale="fr-FR")
def test_the_legend_in_french(open_page: Any) -> None:
    o = open_page("pop", variant="lyrics-vamp")
    expect(o.page.get_by_test_id("chord-reminder-legend")).to_have_text(f"Accord gris{NBSP}: il continue depuis avant.")


# A9 (R7): the guitar and keys words stage, on the lines after the one sung (the big Now chord names that one);
# never the singer's stage.
@pytest.mark.tablet
@pytest.mark.parametrize("inst", ["guitar", "piano", "voice"])
def test_the_stage_shows_reminders_on_the_lines_to_come(open_page: Any, inst: str) -> None:
    o = open_page("pop", variant="lyrics-vamp")
    o.js(f"Woodshed.app.setInstrument('{inst}')")
    o.js("Woodshed.app.store.set({ sheet: 'lyrics' })")
    on_stage(o, {"guitar": "Guitar", "piano": "Keys", "voice": "Voice"}[inst])
    at(o, bar_start(o, 1) + 0.3, playing=False)  # stopped inside line 2
    lines = o.page.locator(STAGE)
    expect(lines).to_have_count(3)
    expect(lines.first).to_contain_text("the road")
    if inst == "voice":
        expect(o.page.locator("#stLyrics").get_by_test_id("chord-reminder")).to_have_count(0)
    else:
        assert reminders(o, STAGE) == [None, None, ["C"]]  # line 2 sung, line 3 its check's C, line 4 still C


# A11 (R1): a first word sung just before a downbeat where the chord changes: the chord sounding under it.
def test_an_anticipated_first_word_shows_the_chord_before_the_change(open_page: Any) -> None:
    o = open_page("pop", variant="lyrics-vamp-early")
    line = o.page.get_by_test_id("lyric-line").nth(3)
    assert reminders(o)[3] == ["C"]
    expect(line.locator(".lw").nth(1).locator(".lc")).to_contain_text("G")  # the change, pushed to "time"


# A12 (guard): every line opens on a change: no reminder, no legend; the exports write changes only.
def test_lines_opening_on_their_own_chord_have_no_reminder(open_page: Any) -> None:
    o = open_page("pop", variant="lyrics")
    expect(o.page.get_by_test_id("lyric-line")).to_have_count(2)
    expect(o.page.get_by_test_id("chord-reminder")).to_have_count(0)
    expect(o.page.get_by_test_id("chord-reminder-legend")).to_have_count(0)


def test_the_chordpro_writes_no_reminder(open_page: Any) -> None:
    from tests.page.test_page import download
    from woodshed import exports

    o = open_page("pop", variant="lyrics-vamp")
    data = o.js("Woodshed.current.song")
    words = json.loads((o.folder / "lyrics.json").read_text())
    text = download(o, "export-chordpro")
    assert text == exports.chordpro(data, words)
    assert "[C]the" not in text and "[C]in" not in text


# The capo shapes view: the grid's label names the sounding chord, so the words say the shape as a shape.
def test_in_the_shapes_view_a_screen_reader_hears_the_shape(open_page: Any) -> None:
    o = open_page("pop", variant="lyrics-vamp")
    o.js("Woodshed.app.store.set({ capo: 3, pos: 'open', view: 'shapes' })")
    assert o.js(SAID)[:2] == [["the A shape"], ["still the A shape"]]
    o.js("Woodshed.app.store.set({ view: 'chords' })")
    assert o.js(SAID)[:2] == [["C"], ["still C"]]  # the sounding names again


@pytest.mark.browser_context_args(locale="fr-FR")
def test_in_the_shapes_view_the_shape_is_said_in_french(open_page: Any) -> None:
    o = open_page("pop", variant="lyrics-vamp")
    o.js("Woodshed.app.store.set({ capo: 3, pos: 'open', view: 'shapes' })")
    assert o.js(SAID)[:2] == [["la position de A"], ["toujours la position de A"]]


# A long reminder over short words: it takes its width when it would reach any chord after it, not only the next.
@pytest.mark.parametrize(("width", "height"), [(390, 844), (1440, 900)])
def test_a_long_reminder_never_reaches_a_chord_further_on(open_page: Any, width: int, height: int) -> None:
    o = open_page("pop", variant="lyrics-vamp-long")
    sized(o, width, height)
    redraw(o)
    line = o.page.get_by_test_id("lyric-line").nth(1)
    assert reminders(o)[1] == ["A♭maj7/C"]
    gap = line.evaluate(
        """(line) => {
          const r = line.querySelector('[data-testid="chord-reminder"] [aria-hidden="true"]').getBoundingClientRect();
          return line.querySelectorAll('.lw')[2].querySelector('.lc').getBoundingClientRect().left - r.right;
        }"""
    )
    assert gap >= 4


# Stopped before a line (an intro), the stage's "Next:" line is the one to come: it shows its grey chord too.
@pytest.mark.tablet
def test_the_next_line_on_stage_shows_its_grey_chord(open_page: Any) -> None:
    o = open_page("pop", variant="lyrics-vamp-intro")
    on_stage(o, "Guitar")
    at(o, bar_start(o, 0) + 0.3, playing=False)  # in the intro, before the first line
    expect(o.page.get_by_test_id("stage-next-label")).to_be_visible()
    assert reminders(o, STAGE)[0] == ["C"]
    at(o, bar_start(o, 1) + 0.3, playing=False)  # inside it: the big Now chord names it
    assert reminders(o, STAGE)[0] is None
