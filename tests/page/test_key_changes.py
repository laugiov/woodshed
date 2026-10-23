"""Key changes on the page (spec 012): the mark before the bar, the numerals and names in the new key, the
header, transposed, in French, and said to a screen reader."""

from __future__ import annotations

from typing import Any

import pytest
from playwright.sync_api import expect


def bar(o: Any, u: int) -> Any:
    return o.page.locator(f"#sheet .bar[data-bar='{u}']")


def test_the_lift_is_marked_and_read_in_its_new_key(open_page: Any) -> None:
    o = open_page("lift", stems=False)
    page = o.page
    mark = page.get_by_test_id("key-change")
    expect(mark).to_have_count(1)
    expect(bar(o, 16).get_by_test_id("key-change")).to_have_text("→ D♭ major")
    expect(bar(o, 16)).to_have_class("bar key-change-bar")
    assert mark.get_attribute("aria-hidden") == "true"
    expect(bar(o, 16)).to_have_attribute("aria-label", "Bar 17: D♭, key change: D♭ major")
    for u, numeral in ((0, "I"), (1, "V"), (16, "I"), (17, "V"), (18, "vi"), (19, "IV")):
        expect(bar(o, u).locator(".rn")).to_have_text(numeral)  # no bII after the lift
    expect(bar(o, 19)).to_contain_text("G♭")  # spelled in D♭, not F♯
    expect(page.get_by_test_id("key-facts")).to_have_text("Key C major → D♭ major")


def test_transposed_the_change_follows(open_page: Any) -> None:
    o = open_page("lift", stems=False)
    o.js("Woodshed.app.transposeTo(2)")
    expect(bar(o, 16).get_by_test_id("key-change")).to_have_text("→ E♭ major")
    expect(o.page.get_by_test_id("key-facts")).to_have_text("Key D major → E♭ major")
    expect(bar(o, 16).locator(".rn")).to_have_text("I")  # numerals do not move with the key


def test_a_song_in_one_key_has_no_mark(open_page: Any) -> None:
    o = open_page("pop", stems=False)
    expect(o.page.get_by_test_id("key-change")).to_have_count(0)
    expect(o.page.get_by_test_id("key-facts")).to_have_text("Key C major")


@pytest.mark.browser_context_args(locale="fr-FR")
def test_in_french(open_page: Any) -> None:
    o = open_page("lift", stems=False)
    expect(bar(o, 16).get_by_test_id("key-change")).to_have_text("→ D♭ majeur")
    expect(o.page.get_by_test_id("key-facts")).to_have_text("Tonalité C majeur → D♭ majeur")


@pytest.mark.parametrize("transpose", [0, 2])
def test_the_exports_say_the_change_where_it_happens_as_python_does(open_page: Any, transpose: int) -> None:
    from tests.page.test_page import download
    from woodshed import exports

    o = open_page("lift", stems=False)
    o.js("(t) => Woodshed.app.transposeTo(t)", transpose)
    data = o.js("Woodshed.current.song")
    cho = download(o, "export-chordpro")
    assert cho == exports.chordpro(data, transpose=transpose)
    new = "Db" if transpose == 0 else "Eb"
    assert cho.count("{key: ") == 2 and ("{key: " + new + "}") in cho
    before = cho.split("{key: " + new + "}")[0]
    assert new not in before  # no chord of the new key before the change is said
    xml = download(o, "export-musicxml")
    if transpose == 0:
        assert xml == exports.musicxml(data)
        m17 = xml.split('<measure number="17">')[1].split("</measure>")[0]
        assert m17.startswith("<attributes><key><fifths>-5</fifths><mode>major</mode></key></attributes>")
        m16 = xml.split('<measure number="16">')[1].split("</measure>")[0]
        assert m16.endswith('<barline location="right"><bar-style>light-light</bar-style></barline>')
        assert "<root-step>G</root-step><root-alter>-1</root-alter>" in xml  # Gb, not F#


def test_in_the_words_the_change_is_said_above_its_line(open_page: Any) -> None:
    o = open_page("lift", variant="lyrics-lift")
    mark = o.page.get_by_test_id("key-change-words")
    expect(mark).to_have_count(1)
    expect(mark).to_have_text("→ D♭ major")
    nxt = o.js("document.querySelector('[data-testid=key-change-words]').nextElementSibling.dataset.from")
    assert nxt == "14"  # the line holding bar 17


def test_the_library_says_the_key_a_song_ends_in(page: Any, pages_root: str, tmp_path: Any, monkeypatch: Any) -> None:
    import json
    import shutil
    import threading

    from tests.page.conftest import built
    from woodshed import app
    from woodshed.run import Options

    monkeypatch.setenv("WOODSHED_CACHE", str(tmp_path / "cache"))
    srv = app.AppServer(app.Library(tmp_path / "library", Options(use_stems=False, open_page=False)))
    folder = srv.library.root / "Lift.woodshed"
    shutil.copytree(built("pop", True, pages_root), folder)
    ends = ["Db", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B", "C"]
    summary = {"title": "Lift", "stems": True, "key": "C", "key_end": ends, "bpm": 120, "meter": "4/4", "duration": 58}
    (folder / "woodshed.json").write_text(
        json.dumps({"settings": {}, "summary": summary, "complete": True, "doubts": 0})
    )
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        page.goto(srv.url)
        expect(page.get_by_test_id("key-end")).to_have_text("ends in D♭")
    finally:
        srv.shutdown()
        srv.server_close()


def test_a_chord_typed_after_the_lift_is_spelled_in_the_new_key(open_page: Any) -> None:
    o = open_page("lift", stems=False)
    o.js("Woodshed.app.typeBars([19], [[4, 'F#']])")  # typed with a sharp: the key of D-flat spells it G-flat
    expect(bar(o, 19)).to_contain_text("G♭")
    expect(bar(o, 19).locator(".rn")).to_have_text("IV")
