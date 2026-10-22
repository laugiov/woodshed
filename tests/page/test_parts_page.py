"""The band names and cuts its parts: renamed, joined, started on any bar; lines and exports follow."""

from __future__ import annotations

from typing import Any

from playwright.sync_api import expect

PARTS = "Woodshed.app.sections().map((p) => [p.start, p.name, !!p.custom])"


def editing(o: Any) -> Any:
    o.page.get_by_test_id("edit-chart").click()
    return o.page


def test_a_part_renamed_in_edit_mode_is_shown_as_typed(open_page: Any) -> None:
    o = open_page("pop")
    o.js("Woodshed.app.namePart(4, 'Chorus')")  # pop is one part: a second one first
    page = editing(o)
    field = page.get_by_test_id("part-name").nth(1)
    field.fill("Riff")
    field.press("Enter")
    assert o.js(PARTS)[1][1:] == ["Riff", True]
    page.get_by_test_id("edit-done").click()
    expect(page.get_by_test_id("form-chip").nth(1)).to_have_text("Riff")
    assert '{start_of_verse: label="Riff"}' in o.js(
        "Woodshed.exports.chordpro(Woodshed.current, null)"
    ) or 'label="Riff"' in o.js("Woodshed.exports.chordpro(Woodshed.current, null)")
    page.get_by_test_id("lang-fr").click()  # a typed name reads the same in every language
    expect(page.get_by_test_id("form-chip").nth(1)).to_have_text("Riff")


def test_two_parts_joined_make_one_with_its_lines(open_page: Any) -> None:
    o = open_page("pop")
    o.js("Woodshed.app.namePart(4, 'Chorus')")
    before = o.js(PARTS)
    page = editing(o)
    page.get_by_test_id("part-join").first.click()  # the second part joins the first
    after = o.js(PARTS)
    assert len(after) == len(before) - 1 and after[0][0] == 0
    assert before[1][0] not in [p[0] for p in after]
    expect(page.get_by_test_id("section")).to_have_count(len(after))


def test_a_part_started_mid_line_starts_a_line(open_page: Any) -> None:
    o = open_page("pop")
    page = editing(o)
    page.locator('.bar[data-bar="2"]').first.click()
    page.get_by_test_id("part-start").click()
    page.get_by_test_id("part-start-name").fill("Tag")
    page.get_by_test_id("part-start-name").press("Enter")
    expect(page.get_by_test_id("toast")).to_contain_text("A part starts at bar 3")
    assert [2, "Tag", True] in o.js(PARTS)
    firsts = o.js("Woodshed.current.song.groups.flatMap((g) => g.occurrences.map((l) => l[0]))")
    assert 2 in firsts  # the line breaks where the part starts
    # The parts back to the analysis: the lines as they were.
    page.once("dialog", lambda d: d.accept())
    page.get_by_test_id("untype-parts").click()
    assert 2 not in o.js("Woodshed.current.song.groups.flatMap((g) => g.occurrences.map((l) => l[0]))")
    assert [2, "Tag", True] not in o.js(PARTS)


def test_the_parts_overlay_on_its_edges(open_page: Any) -> None:
    o = open_page("pop")
    apply = "(base, parts) => Woodshed.edits.applyParts(base, parts, 0, 4, 12).map((p) => [p.start, p.name, p.role])"
    base = [
        {"name": "Verse 1", "role": "verse", "letter": "A", "start": 0, "end": 8},
        {"name": "Chorus 1", "role": "chorus", "letter": "B", "start": 8, "end": 12},
    ]
    assert o.js(f"({apply})({base}, {{'0': {{join: true}}}})") == [
        [0, "Verse 1", "verse"],
        [8, "Chorus 1", "chorus"],
    ]  # nothing before the first
    assert o.js(f"({apply})({base}, {{'16': {{name: 'Tag'}}, '17': {{name: 'Solo over the chorus'}}}})") == [
        [0, "Verse 1", "verse"],
        [4, "Solo over the chorus", "instrumental"],  # beats 16 and 17 round to bar 4: the later one wins
        [8, "Chorus 1", "chorus"],
    ]
    assert o.js(f"({apply})([], {{'16': {{name: 'B'}}}})")[0][1] == "Part A"  # no parts before: the first has a name


def test_enter_on_an_untouched_bar_types_nothing(open_page: Any) -> None:
    o = open_page("pop")
    page = editing(o)
    page.locator('.bar[data-bar="1"]').first.click()
    page.get_by_test_id("bar-field").press("Enter")  # walks on to the next bar
    expect(page.get_by_test_id("bar-editor")).to_contain_text("Bar 3")
    assert o.js("Woodshed.app.typedBar(1)") is None and o.js("Woodshed.current.bars[1].edited") is False


def test_on_a_part_s_first_bar_the_editor_renames_it(open_page: Any) -> None:
    o = open_page("pop")
    page = editing(o)
    page.locator('.bar[data-bar="0"]').first.click()
    expect(page.get_by_test_id("part-start")).to_have_text("Rename the part")
    page.get_by_test_id("part-start").click()
    page.get_by_test_id("part-start-name").fill("Intro riff")
    page.get_by_test_id("part-start-name").press("Enter")
    assert o.js(PARTS)[0] == [0, "Intro riff", True]
    expect(page.get_by_test_id("toast")).to_contain_text("The part at bar 1 is renamed")


def test_the_parts_go_back_to_the_analysis_with_a_confirm_and_an_undo(open_page: Any) -> None:
    o = open_page("pop")
    before = o.js(PARTS)
    o.js("Woodshed.app.namePart(4, 'Chorus')")
    page = editing(o)
    page.once("dialog", lambda d: d.accept())
    page.get_by_test_id("untype-parts").click()
    assert o.js(PARTS) == before
    page.get_by_test_id("toast-action").click()  # Undo
    assert [4, "Chorus", True] in o.js(PARTS)


def test_renaming_a_part_to_its_own_name_types_nothing(open_page: Any) -> None:
    o = open_page("pop")
    page = editing(o)
    page.locator('.bar[data-bar="0"]').first.click()
    page.get_by_test_id("part-start").click()
    page.get_by_test_id("part-start-name").press("Enter")  # the name as shown, untouched
    assert o.js("Object.keys(Woodshed.app.typedParts.values()).length") == 0
    assert o.js("Woodshed.edits.roleOf('Introduction')") == "intro"
