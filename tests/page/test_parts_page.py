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
    page.get_by_test_id("untype-parts").click()
    assert 2 not in o.js("Woodshed.current.song.groups.flatMap((g) => g.occurrences.map((l) => l[0]))")
    assert [2, "Tag", True] not in o.js(PARTS)
