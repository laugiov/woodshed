"""Browser tests of the practice page, with Playwright, on pages built from the synthetic songs.

Every test opens the page from disk (file://). Any network request, console error or console
warning fails the test. Browsers are chosen with pytest-playwright's --browser option.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import ConsoleMessage, Page, Request

from tests import synth
from tests.test_analysis import fake_stems
from woodshed import analysis, build

REQUIRED = os.environ.get("WOODSHED_REQUIRE_PAGE") == "1"


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    here = Path(__file__).parent
    for item in items:
        if Path(str(item.fspath)).is_relative_to(here):
            item.add_marker(pytest.mark.page)


@pytest.fixture(scope="session", autouse=True)
def _browsers_installed(request: pytest.FixtureRequest) -> None:
    try:
        request.getfixturevalue("browser")
    except Exception as exc:  # Playwright raises its own Error when a browser is missing
        if REQUIRED:
            raise
        pytest.skip(f"browser not available ({str(exc).splitlines()[0]}): run `playwright install`")


@cache
def built(name: str, stems: bool, root: str, title: str | None = None) -> Path:
    folder = Path(root)
    wav = synth.write(name, folder / "src").wav
    per = synth.SONGS[name].beats_per_bar
    separated = fake_stems(name, folder / "src") if stems else None
    result = analysis.analyze(wav, use_stems=stems, stems_result=separated, beats_per_bar=per, title=title)
    return build.build(result, wav, folder / "pages" / f"{name}-{int(stems)}", separated)


@cache
def built_six(name: str, keys: bool, root: str, guitar: bool = True) -> Path:
    """The page of `name` separated with six stems: its chords on the guitar and on the keys, each heard or not."""
    from tests.test_guitar_keys import six_stems

    folder = Path(root) / f"six-{int(guitar)}{int(keys)}"
    wav = synth.write(name, folder / "src").wav
    separated = six_stems(folder / "src", keys=keys, guitar=guitar)
    result = analysis.analyze(
        wav, use_stems=True, stems_result=separated, beats_per_bar=synth.SONGS[name].beats_per_bar
    )
    return build.build(result, wav, folder / "pages" / f"{name}-six", separated)


@cache
def with_close_calls(name: str, stems: bool, root: str) -> Path:
    """The page of `name` with every doubt turned into a close call (the synthetic songs only have
    timing doubts: their chords are clear)."""
    source = built(name, stems, root)
    folder = source.with_name(source.name.replace(".woodshed", "-close.woodshed"))
    shutil.copytree(source, folder)
    page = folder / "index.html"
    text = page.read_text(encoding="utf-8")
    assert '"kind":"timing"' in text
    page.write_text(text.replace('"kind":"timing"', '"kind":"chord"'), encoding="utf-8")
    return folder


def rewritten(name: str, root: str, tag: str, change: Callable[[dict[str, Any]], None]) -> Path:
    """A copy of the page of `name` whose song data `change` rewrote."""
    source = built(name, True, root)
    folder = source.with_name(source.name.replace(".woodshed", f"-{tag}.woodshed"))
    if folder.exists():
        return folder
    shutil.copytree(source, folder)
    page = folder / "index.html"
    text = page.read_text(encoding="utf-8")
    match = re.search(r'(<script type="application/json" id="woodshed-data">)(.*?)(</script>)', text, re.S)
    assert match is not None
    data = json.loads(match.group(2))
    change(data["song"])
    back = data["song"].pop("_view_regions_back", None)
    if back is not None:  # a third key region, back to the first key: the view's tables follow
        data["view"]["regions"].append({**data["view"]["regions"][0], "bar": back})
    named = data["song"].pop("_lyrics_sections", None)
    late = data["song"].pop("_lyrics_late", False)
    midline = data["song"].pop("_lyrics_midline", False)
    opened = data["song"].pop("_lyrics_opened", False)
    at = data["song"].pop("_lyrics_at", 0)
    given = data["song"].pop("_lyrics_data", None)
    if given is not None:  # words written by the variant itself
        (folder / "lyrics.js").write_text("window.WOODSHED_LYRICS = " + build.script_json(given) + ";\n")
        (folder / "lyrics.json").write_text(json.dumps(given))
    if data["song"].pop("_lyrics", False):
        lyrics = lyrics_for(data["song"], at)
        if late:  # a line whose only word comes late in bar 2, after both of its chord changes
            start, end = data["song"]["bars"][1]["start"], data["song"]["bars"][1]["end"]
            first = {**lyrics["lines"][0], "words": lyrics["lines"][0]["words"][:1]}
            word = {"text": "late", "start": start + 0.75 * (end - start), "end": start + 0.9 * (end - start)}
            lyrics["lines"] = [first, {**lyrics["lines"][0], "text": "late", "words": [word]}]
        if midline:  # one line: a word on bar 1, then one late in bar 2, after two chord changes
            start, end = data["song"]["bars"][1]["start"], data["song"]["bars"][1]["end"]
            early = lyrics["lines"][0]["words"][0]
            word = {"text": "late", "start": start + 0.75 * (end - start), "end": start + 0.9 * (end - start)}
            lyrics["lines"] = [{**lyrics["lines"][0], "text": early["text"] + " late", "words": [early, word]}]
        if opened:  # a word on bar 1; the next line early in bar 3, which plays bar 2's chord on
            bars = data["song"]["bars"]
            start, end = bars[2]["start"], bars[2]["end"]
            first = {**lyrics["lines"][0], "text": "Morning", "words": lyrics["lines"][0]["words"][:1]}
            word = {"text": "comes", "start": start + 0.2 * (end - start), "end": start + 0.3 * (end - start)}
            lyrics["lines"] = [first, {**lyrics["lines"][0], "text": "comes", "words": [word]}]
        if named is not None:
            lyrics["sections"] = named
        (folder / "lyrics.js").write_text("window.WOODSHED_LYRICS = " + build.script_json(lyrics) + ";\n")
        (folder / "lyrics.json").write_text(json.dumps(lyrics))
    page.write_text(text[: match.start(2)] + build.script_json(data) + text[match.end(2) :], encoding="utf-8")
    return folder


def _two_sections(song: dict[str, Any]) -> None:
    """pop as a verse and a chorus: each line its own group, two sections of one line each."""
    bars = song["bars"]
    lines = [list(range(i, min(i + 4, len(bars)))) for i in range(0, len(bars), 4)]
    song["groups"] = [{"label": "A", "family": "A", "occurrences": [line]} for line in lines]
    for g, line in enumerate(lines):
        for c, i in enumerate(line):
            bars[i].update(group=g, occurrence=0, column=c)
    song["sections"] = [
        {"name": "Verse 1", "role": "verse", "letter": "A", "start": 0, "end": 4},
        {"name": "Chorus 1", "role": "chorus", "letter": "B", "start": 4, "end": len(bars)},
    ]


def _no_sections(song: dict[str, Any]) -> None:
    song["sections"] = []


def lyrics_for(song: dict[str, Any], at: int = 0) -> dict[str, Any]:
    """Two sung lines on pop (bars 1-4, 5-6, or from bar `at`): a word at each bar start and one in between;
    bars 7-8 are not sung (an ending)."""
    starts = [b["start"] for b in song["bars"]]

    def words(bars: range, texts: list[str]) -> list[dict[str, Any]]:
        out = []
        for k, u in enumerate(bars):
            half = (starts[u + 1] - starts[u]) / 2 if u + 1 < len(starts) else 1.0
            out.append({"text": texts[2 * k], "start": starts[u], "end": starts[u] + half * 0.8})
            out.append({"text": texts[2 * k + 1], "start": starts[u] + half, "end": starts[u] + half * 1.8})
        return out

    line: dict[str, Any] = {"tag": None, "block": 0, "backing": [], "sung": True, "check": None}
    return {
        "version": 1, "language": "en", "text": "", "chords": [],
        "lines": [
            {**line, "text": "Morning comes in on the harbour road,",
             "words": words(range(at, at + 4), ["Morning", "comes", "in", "on", "the", "harbour", "road,", "yes"])},
            {**line, "text": "the radio hums", "backing": ["hums"], "check": "placed by the order of the text",
             "words": words(range(at + 4, at + 6), ["the", "radio", "hums", "what"])},
            {**line, "text": "not in this recording", "sung": False, "check": "not heard",
             "words": [{"text": "not", "start": None, "end": None}]},
        ],
    }  # fmt: skip


def lyrics_per_bar(song: dict[str, Any], at: int, texts: list[tuple[str, str]]) -> dict[str, Any]:
    """One sung line per bar from bar `at` (0-based), one per pair of `texts`: the first word on the downbeat, the
    second at half the bar."""
    line: dict[str, Any] = {"tag": None, "block": 0, "backing": [], "sung": True, "check": None}
    lines = []
    for k, (a, b) in enumerate(texts):
        start, end = song["bars"][at + k]["start"], song["bars"][at + k]["end"]
        size = end - start
        words = [
            {"text": a, "start": start, "end": start + 0.4 * size},
            {"text": b, "start": start + 0.5 * size, "end": start + 0.8 * size},
        ]
        lines.append({**line, "text": a + " " + b, "words": words})
    return {"version": 1, "language": "en", "text": "", "chords": [], "lines": lines}


VAMP_WORDS = [
    ("Morning", "comes"), ("the", "road"), ("radio", "hums"), ("in", "time"), ("no", "sound"), ("still", "here"),
]  # fmt: skip


def _vamp(
    song: dict[str, Any], quality: str = "", glue: bool = False, early: bool = False, intro: bool = False
) -> None:
    """pop as a vamp (spec 027): bars 1-4 all C, bars 5-6 no chord, a close call (G) on bar 3's C, one sung line per
    bar over bars 1-6. `glue`: the vamp in `quality`, line 2 opening on one letter with a change (G) on its second
    word, line 4 on one letter. `early`: bar 4 played as G, line 4's first word 0.1 s before its downbeat and its
    second 0.15 s after it (the change pushed to it). `intro`: bar 1 an intro, the lines from bar 2 (the first one
    opening on the intro's chord, held)."""
    bars = song["bars"]
    c = {**bars[0]["chords"][0], "pc": 0, "quality": quality, "beats": song["beats_per_bar"], "doubt": None}
    alternatives = [{"pc": 7, "quality": "", "share": 55}, {"pc": 0, "quality": quality, "share": 45}]
    doubt = {"id": 910, "why": "Close call between the top candidates.", "kind": "chord", "alternatives": alternatives}
    for u in range(4):
        bars[u]["chords"] = [dict(c)]
    bars[2]["chords"] = [{**c, "doubt": doubt}]
    for u in (4, 5):
        bars[u]["chords"] = [{**c, "pc": -1, "quality": ""}]
    texts = list(VAMP_WORDS)
    if glue:
        half = song["beats_per_bar"] // 2
        bars[1]["chords"] = [{**c, "beats": half}, {**c, "pc": 7, "quality": "", "beats": half}]
        texts[1], texts[3] = ("a", "road"), ("I", "time")
    if early:
        bars[3]["chords"] = [{**c, "pc": 7, "quality": ""}]
    words = lyrics_per_bar(song, 1, texts[:5]) if intro else lyrics_per_bar(song, 0, texts)
    if early:
        t = bars[3]["start"]
        first, second = words["lines"][3]["words"]
        first.update(start=t - 0.1, end=t + 0.1)
        second.update(start=t + 0.15, end=t + 0.6)
    song["_lyrics_data"] = words


def _vamp_long(song: dict[str, Any]) -> None:
    """lyrics-vamp on a long chord (A flat major seventh over C): line 2 sung "I a road", the first two words short
    and close, a change (G) on "road" at half the bar."""
    _vamp(song)
    bars = song["bars"]
    for u in range(4):
        for c in bars[u]["chords"]:
            c.update(pc=8, quality="maj7", bass=0)
    for alt in bars[2]["chords"][0]["doubt"]["alternatives"][1:]:
        alt.update(pc=8, quality="maj7")
    half = song["beats_per_bar"] // 2
    held = bars[1]["chords"][0]
    bars[1]["chords"] = [{**held, "beats": half}, {**held, "pc": 7, "quality": "", "bass": None, "beats": half}]
    start, end = bars[1]["start"], bars[1]["end"]
    size = end - start
    line = song["_lyrics_data"]["lines"][1]
    line["text"] = "I a road"
    line["words"] = [
        {"text": "I", "start": start, "end": start + 0.2 * size},
        {"text": "a", "start": start + 0.25 * size, "end": start + 0.45 * size},
        {"text": "road", "start": start + 0.5 * size, "end": start + 0.8 * size},
    ]


def _vamp_lift(song: dict[str, Any]) -> None:
    """lift (C, then D flat from bar 17) with bars 16-18 all on pitch class 6 (F sharp in C, G flat in D flat), one
    sung line per bar over bars 15-19; the line of bar 17 sung 0.1 s before its downbeat (on bar 16's chord, in C)."""
    bars = song["bars"]
    for u in (15, 16, 17):
        bars[u]["chords"] = [{**bars[u]["chords"][0], "pc": 6, "quality": "", "beats": song["beats_per_bar"]}]
    texts = [("one", "two"), ("three", "four"), ("five", "six"), ("seven", "eight"), ("nine", "ten")]
    words = lyrics_per_bar(song, 14, texts)
    t = bars[16]["start"]
    words["lines"][2]["words"][0].update(start=t - 0.1)
    song["_lyrics_data"] = words


def _with_lyrics(song: dict[str, Any]) -> None:
    song["_lyrics"] = True  # marker: the folder gets lyrics.js below


def _lyrics_before_the_lift(song: dict[str, Any]) -> None:
    """lift with its sung lines over bars 5-10: the key changes later, among the chord rows (spec 014)."""
    song["_lyrics"] = True
    song["_lyrics_at"] = 4


def _lyrics_over_the_lift(song: dict[str, Any]) -> None:
    """lift with its first sung line over bars 15-18: the key changes inside it (spec 012)."""
    song["_lyrics"] = True
    song["_lyrics_at"] = 14


def _lyrics_named(song: dict[str, Any]) -> None:
    """Two lines of the chart the analysis could only letter (Part A, Part B), named by the words."""
    _two_sections(song)
    song["sections"][0].update(name="Part A", role="part")
    song["sections"][1].update(name="Part B", role="part")
    song["_lyrics"] = True
    song["_lyrics_sections"] = [  # the parts as the words name them (lyrics.sections_by_words)
        {"name": "Verse 1", "role": "verse", "letter": "A", "start": 0, "end": 4},
        {"name": "Chorus 1", "role": "chorus", "letter": "B", "start": 4, "end": len(song["bars"])},
    ]


def _lyrics_same_chord_to_check(song: dict[str, Any]) -> None:
    """Words on pop, and bar 2 played as bar 1 (the same chord) with a close call on it: the chord
    to check is no chord change, so only a mark can show it on the words."""
    _with_lyrics(song)
    first = song["bars"][0]["chords"][0]
    other = (first["pc"] + 7) % 12
    alternatives = [
        {"pc": other, "quality": "", "share": 55},
        {"pc": first["pc"], "quality": first["quality"], "share": 45},
    ]
    doubt = {"id": 900, "why": "Close call between the top candidates.", "alternatives": alternatives, "kind": "chord"}
    song["bars"][1]["chords"] = [{**first, "doubt": doubt}]


def _groove_loose(song: dict[str, Any]) -> None:
    """A drum read where no kick or snare is played in more than half the bars."""
    groove = song["parts"]["groove"]
    for drum in ("kick", "snare"):
        groove[drum] = [round(min(p, 0.45), 3) for p in groove[drum]]


def _lyrics_stacked(song: dict[str, Any]) -> None:
    """Words on pop with bar 2 split in two chords that both lead into a late word, and a chord to
    check: the ChordPro writes chords apart and names the part to check."""
    _with_lyrics(song)
    second = song["bars"][1]["chords"][0]
    third = song["bars"][2]["chords"][0]
    doubt = {"id": 901, "why": "Close call between the top candidates.", "kind": "chord", "alternatives": []}
    song["bars"][1]["chords"] = [{**second, "beats": 2}, {**third, "beats": 2, "doubt": doubt}]
    song["_lyrics_late"] = True


def _lyrics_midline(song: dict[str, Any]) -> None:
    """As lyrics-stacked, with both words on one line: the chords that change while the first word is
    held cannot all go on the second."""
    _lyrics_stacked(song)
    del song["_lyrics_late"]
    song["_lyrics_midline"] = True


def _lyrics_opened(song: dict[str, Any]) -> None:
    """Words on pop with bar 3 playing bar 2's chord on: the second line, opened by a chord row, has no change
    of its own on its first word (the chord sounding there is written on it)."""
    _with_lyrics(song)
    song["bars"][2]["chords"] = [dict(c) for c in song["bars"][1]["chords"]]
    song["_lyrics_opened"] = True


def _groove_edge(song: dict[str, Any]) -> None:
    """A kick on the & of 1 in 55 % of the bars: drawn by the notation (over half the bars), below the
    strong hits a relative rule would keep."""
    groove = song["parts"]["groove"]
    groove["kick"] = [1.0 if i in (0, 8) else 0.55 if i == 2 else 0.0 for i in range(len(groove["kick"]))]


def _groove_diffuse(song: dict[str, Any]) -> None:
    """Beyond the Sky's read: a kick a little on every slot, nothing steady (no clear groove)."""
    groove = song["parts"]["groove"]
    groove["kick"] = [0.51, 0.42, 0.25, 0.39, 0.33, 0.21, 0.28, 0.18, 0.25, 0.23, 0.21, 0.21, 0.37, 0.18, 0.26, 0.26]
    groove["snare"] = [0.05, 0.05, 0.07, 0.02, 0.02, 0.0, 0.05, 0.02, 0.0, 0.02, 0.0, 0.0, 0.05, 0.0, 0.04, 0.02]
    groove["hat"] = [0.28, 0.23, 0.14, 0.14, 0.32, 0.18, 0.19, 0.18, 0.32, 0.14, 0.16, 0.16, 0.39, 0.19, 0.25, 0.26]


def _bass_doubts(song: dict[str, Any]) -> None:
    """Bar 1 heard with little confidence, bar 2 with no bass at all."""
    bass = song["parts"]["bass"]
    bass[0] = [None if e is None else [e[0], 0.4] for e in bass[0]]
    bass[1] = [None for _ in bass[1]]


def _keys_readings(song: dict[str, Any]) -> None:
    """pop's keys as the record can read them (spec 015): bar 1 no upper note, bar 2 its root alone, bar 3 Am
    with a major third, bar 4 F with a minor third, bar 5 no chord, bar 6 Gsus4 (no third to contradict), bar 7
    two chords, bar 8 F with both thirds."""
    bars = song["bars"]
    heard = song["parts"]["voicings"]
    heard[0], heard[1], heard[2], heard[3] = [], [7], [1, 4], [8, 0]
    bars[4]["chords"] = [{"pc": -1, "quality": "", "beats": 4, "doubt": None}]
    bars[5]["chords"] = [{**bars[5]["chords"][0], "quality": "sus4"}]
    heard[5] = [10, 2]
    bars[6]["chords"] = [{**bars[6]["chords"][0], "beats": 2}, {**bars[7]["chords"][0], "beats": 2}]
    heard[6] = [1, 4]
    heard[7] = [8, 9, 0]


def _keys_after_the_lift(song: dict[str, Any]) -> None:
    """lift with bar 18 (in D flat) played as E flat over a G flat: the other third, spelled in its region."""
    song["bars"][17]["chords"] = [{**song["bars"][17]["chords"][0], "pc": 3, "quality": ""}]
    song["parts"]["voicings"][17] = [6, 10]


def _keys_thin(song: dict[str, Any], below: bool = False) -> None:
    """The keys read as one note in a quarter of pop's bars (one bar fewer with `below`), the others a triad."""
    heard = song["parts"]["voicings"]
    thin = (len(song["bars"]) + 3) // 4 - (1 if below else 0)
    for u in range(len(song["bars"])):
        heard[u] = [7] if u < thin else [0, 4, 7]


def _lyrics_no_sections(song: dict[str, Any]) -> None:
    _no_sections(song)
    _with_lyrics(song)


def _two_checks(song: dict[str, Any]) -> None:
    """pop with bar 2 split in two chords, each a close call: two chords to check in one bar."""
    first, other = song["bars"][1]["chords"][0], song["bars"][2]["chords"][0]

    def doubt(n: int, chord: dict[str, Any]) -> dict[str, Any]:
        alternatives = [
            {"pc": (chord["pc"] + 7) % 12, "quality": "", "share": 55},
            {"pc": chord["pc"], "quality": chord["quality"], "share": 45},
        ]
        return {"id": n, "why": "Close call between the top candidates.", "kind": "chord", "alternatives": alternatives}

    song["bars"][1]["chords"] = [
        {**first, "beats": 2, "doubt": doubt(902, first)},
        {**other, "beats": 2, "doubt": doubt(903, other)},
    ]


def _voice(song: dict[str, Any], low: int, high: int, *ranges: tuple[int | None, int | None, int]) -> None:
    """lift (C, D♭ from bar 17) sung from `low` to `high`, with the range of each key region (spec 024): bar 1, then
    bar 17 (and bar 25 for a third region, back in C)."""
    bars = [0, 16, 24]
    if len(ranges) > 2:
        song["key_regions"].append({**song["key_regions"][0], "bar": 24})
        song["_view_regions_back"] = 24
    song["parts"]["vocal"] = {
        "low": low,
        "high": high,
        "voiced_share": 0.6,
        **(
            {"regions": [{"bar": bars[k], "low": a, "high": b, "notes": n} for k, (a, b, n) in enumerate(ranges)]}
            if ranges
            else {}
        ),
    }


VARIANTS: dict[str, Callable[[dict[str, Any]], None]] = {
    # The voice range per key region (spec 024): the ending inside the song's range, above it, below it, a
    # semitone above (the margin), too short to measure, a third of the song (its top is the whole song's), not
    # measured yet (a page built before), and two changes (C, D♭, C).
    "voice-lift-inside": lambda song: _voice(song, 53, 61, (53, 61, 68), (53, 58, 13)),
    "voice-lift-higher": lambda song: _voice(song, 53, 61, (53, 61, 68), (55, 66, 13)),
    "voice-lift-lower": lambda song: _voice(song, 53, 61, (53, 61, 68), (50, 58, 13)),
    "voice-lift-semitone": lambda song: _voice(song, 53, 61, (53, 61, 68), (54, 62, 13)),
    "voice-lift-short": lambda song: _voice(song, 53, 61, (53, 61, 68), (None, None, 5)),
    "voice-lift-long": lambda song: _voice(song, 53, 64, (53, 61, 40), (55, 64, 30)),
    "voice-lift-unmeasured": lambda song: _voice(song, 53, 61),
    "voice-lift-twice": lambda song: _voice(song, 53, 61, (53, 61, 60), (55, 66, 13), (53, 60, 12)),

    "two-checks": _two_checks,
    "sections": _two_sections, "nosections": _no_sections, "lyrics": _with_lyrics,
    "lyrics-nosections": _lyrics_no_sections, "lyrics-named": _lyrics_named,
    "lyrics-same-check": _lyrics_same_chord_to_check,
    "groove-loose": _groove_loose,
    "bass-doubts": _bass_doubts,
    "groove-edge": _groove_edge,
    "groove-diffuse": _groove_diffuse,
    "lyrics-stacked": _lyrics_stacked,
    "lyrics-midline": _lyrics_midline,
    "lyrics-opened": _lyrics_opened,
    "lyrics-vamp": _vamp,
    "lyrics-vamp-glue": lambda song: _vamp(song, quality="m7", glue=True),
    "lyrics-vamp-early": lambda song: _vamp(song, early=True),
    "lyrics-vamp-lift": _vamp_lift,
    "lyrics-vamp-long": _vamp_long,
    "lyrics-vamp-intro": lambda song: _vamp(song, intro=True),
    "lyrics-lift": _lyrics_over_the_lift,
    "lyrics-lift-early": _lyrics_before_the_lift,
    "keys-readings": _keys_readings,
    "keys-lift": _keys_after_the_lift,
    "keys-thin": _keys_thin,
    "keys-thin-below": lambda song: _keys_thin(song, below=True),
}  # fmt: skip


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args: dict[str, Any]) -> dict[str, Any]:
    """The pages in English whatever the computer's language (the French has its own tests, whose
    browser_context_args marker wins)."""
    return {**browser_context_args, "locale": "en-US"}


@pytest.fixture(scope="session")
def pages_root(tmp_path_factory: pytest.TempPathFactory) -> str:
    return str(tmp_path_factory.mktemp("pages"))


@dataclass
class Opened:
    page: Page
    folder: Path
    network: list[str] = field(default_factory=list)
    console: list[str] = field(default_factory=list)

    def js(self, expression: str, arg: object = None) -> object:
        return self.page.evaluate(expression, arg)


@pytest.fixture
def open_page(page: Page, pages_root: str) -> Iterator[object]:
    opened: list[Opened] = []

    def open_(
        name: str = "pop",
        stems: bool = True,
        title: str | None = None,
        close_calls: bool = False,
        variant: str = "",
        six: bool | None = None,  # six stems, with the keys heard (True) or not (False)
        guitar: bool = True,  # on a six-stem page: the guitar heard or not
    ) -> Opened:
        if six is not None:
            folder = built_six(name, six, pages_root, guitar)
        elif variant:
            folder = rewritten(name, pages_root, variant, VARIANTS[variant])
        elif close_calls:
            folder = with_close_calls(name, stems, pages_root)
        else:
            folder = built(name, stems, pages_root, title)
        o = Opened(page, folder)

        def on_request(req: Request) -> None:
            if not req.url.startswith(("file://", "data:", "blob:")):
                o.network.append(req.url)

        def on_console(msg: ConsoleMessage) -> None:
            if msg.type in ("error", "warning"):
                o.console.append(f"{msg.type}: {msg.text}")

        page.on("request", on_request)
        page.on("console", on_console)
        page.on("pageerror", lambda exc: o.console.append(f"pageerror: {exc}"))
        page.route(
            "**/*", lambda route: route.continue_() if route.request.url.startswith("file://") else route.abort()
        )
        page.goto((folder / "index.html").as_uri())
        for _ in range(200):  # polled: the page's CSP forbids Playwright's string evaluation
            if page.evaluate("window.Woodshed && window.Woodshed.ready === true"):
                break
            page.wait_for_timeout(25)
        opened.append(o)
        return o

    yield open_
    for o in opened:
        assert o.network == [], f"the page tried the network: {o.network}"
        assert o.console == [], f"console errors or warnings: {o.console}"
