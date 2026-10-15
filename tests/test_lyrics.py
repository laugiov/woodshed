"""Lyrics on the chart: pasted words placed on the voice, chords on the syllables.

The speech model is not run here: a synthetic voice gives, frame by frame, the letters a model
would hear, sung at known times. Verses are heard clearly; choruses are blurred, as backing
vocals and held vowels blur them for the real model."""

from __future__ import annotations

import json
import string
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from woodshed import cli, lyrics

LABELS = ["-", "*", "'", *string.ascii_lowercase]
F = lyrics.FRAME


def voice(
    sung: list[tuple[str, float, float]], length: float, blur: frozenset[str] | set[str] = frozenset(), seed: int = 1
) -> lyrics.Voice:
    """A voice singing each (text, start, end); lines in `blur` are heard as other letters, though
    their true letters keep a fair score (an aligner can still follow them)."""
    rng = np.random.default_rng(seed)
    frames = int(length / F)
    em = np.full((frames, len(LABELS)), -8.0, np.float32)
    em[:, 0] = 0.0  # blank
    em[:, 1] = 0.0  # the wildcard: free, as in the real model
    on = np.zeros(frames, bool)
    for text, start, end in sung:
        letters = (
            lyrics.letters_of(text.replace(" ", ""))
            if " " not in text
            else "".join(lyrics.letters_of(w) for w in text.split())
        )
        a, b = int(start / F), int(end / F)
        on[a:b] = True
        step = (b - a) / len(letters)
        for i, c in enumerate(letters):
            f = a + int(i * step)
            k = LABELS.index(c)
            if text in blur:
                wrong = LABELS.index(rng.choice(list(string.ascii_lowercase)))
                em[f : f + 2, wrong] = 0.0
                em[f : f + 2, k] = -1.0
                em[f : f + 2, 0] = -3.0
            else:
                em[f : f + 2, k] = 0.0
                em[f : f + 2, 0] = -5.0
    return lyrics.Voice(em, LABELS, on)


def song(bars: int, chords: list[tuple[int, str]], bpm: float = 120.0) -> dict[str, Any]:
    """A chart: four beats a bar from time 0; chords as (pc, quality) changing on each bar."""
    beat = 60 / bpm
    out = []
    for u in range(bars):
        pc, q = chords[u % len(chords)]
        out.append({"chords": [{"pc": pc, "quality": q, "beats": 4}]})
    return {"beats": [k * beat for k in range(bars * 4 + 1)], "first_beat": 0, "beats_per_bar": 4, "bpm": bpm,
            "bars": out}  # fmt: skip


VERSE_1 = ["morning comes in on the harbour road", "the radio hums what the night forgot"]
CHORUS = ["hold on hold on to the northern light", "we are only halfway through the night"]
VERSE_2 = ["somebody sings on the overpass tonight", "the bridge is wet and the lights are low"]
VERSE_3 = ["a paper boat goes down the river slow", "and nobody knows where the letters go"]


# Reading the pasted text.


def test_pasted_text_is_cleaned_into_sung_lines() -> None:
    text = """\ufeff[Verse 1]
G              D
Morning comes in on the harbour road,
the radio hums (radio hums)

[Chorus]
Em   C
Hold on to the northern light (x2)
(ooh, ooh)
"""
    lines = lyrics.parse(text)
    assert [ln.text for ln in lines] == [
        "Morning comes in on the harbour road,",
        "the radio hums (radio hums)",
        "Hold on to the northern light",
        "Hold on to the northern light",
    ]
    assert lines[0].tag == "Verse 1" and lines[2].tag == "Chorus" and lines[0].block != lines[2].block
    assert lines[1].backing == ["radio hums"] and lines[1].letters == "theradiohums"
    assert lines[3].backing == ["ooh, ooh"]  # a line of backing vocals goes with the line before


@pytest.mark.parametrize(
    "text",
    [
        "[Chorus]\nHold on\nwe are halfway\n\nthe bridge is wet\n\n[Chorus]\n",  # a name alone: that part again
        "[Chorus]\nHold on\nwe are halfway\n\nthe bridge is wet\n\nRefrain :\n",  # a French site's way
        "Refrain\nHold on\nwe are halfway\n\nthe bridge is wet\n\nREFRAIN x1\n",
    ],
)
def test_a_part_named_again_is_sung_again(text: str) -> None:
    assert [ln.text for ln in lyrics.parse(text)] == [
        "Hold on",
        "we are halfway",
        "the bridge is wet",
        "Hold on",
        "we are halfway",
    ]


@pytest.mark.parametrize("name", ["Refrain x2", "REFRAIN 2 x2", "Chorus (x2)", "[Chorus] x2"])
def test_a_part_name_with_a_count_sings_the_part_that_many_times(name: str) -> None:
    lines = lyrics.parse(f"{name}\nHold on\n")
    assert [ln.text for ln in lines] == ["Hold on", "Hold on"]


@pytest.mark.parametrize("row", ["Solo tonight", "Bridge over water", "Hook me up", "verse here", "I got a box 5"])
def test_lyric_lines_that_look_like_part_names_stay_lyrics(row: str) -> None:
    assert [ln.text for ln in lyrics.parse(row)] == [row]


def test_a_part_sung_twice_and_chords_inside_the_words() -> None:
    text = "[Chorus] (x2)\n[Am]Let it [C]be, let it be\nG7sus4  F#m7b5  Bb/D\nwhisper words\n"
    lines = lyrics.parse(text)
    assert [ln.text for ln in lines] == ["Let it be, let it be", "whisper words"] * 2
    assert lines[0].tag == "Chorus" and lines[2].block != lines[0].block


def test_letters_are_what_a_voice_can_sing() -> None:
    assert lyrics.letters_of("Dîtes-vous") == "ditesvous"
    assert lyrics.letters_of("J\u2019en") == "j'en" and lyrics.letters_of("\u2018") == ""  # typographic quotes
    assert [w.letters for w in lyrics.parse("Aimez-moi-à genoux")[0].words] == ["aimez", "moi", "a", "genoux"]
    assert lyrics.parse("\n\nG  D  Em\n\n") == []


# The exact alignment.


def test_the_alignment_finds_each_letter() -> None:
    v = voice([("abc", 0.2, 0.8)], 1.2)
    first, last, _ = lyrics.ctc_align(v.emission, [LABELS.index(c) for c in "abc"], 0)
    assert [round(f * F, 2) for f in first] == [0.2, 0.4, 0.6]
    assert all(b >= a for a, b in zip(first, last, strict=True))


def test_a_double_letter_needs_the_blank_between() -> None:
    v = voice([("aab", 0.2, 0.8)], 1.2)
    first, _, _ = lyrics.ctc_align(v.emission, [LABELS.index(c) for c in "aab"], 0)
    assert first[0] < first[1] < first[2]


@pytest.mark.parametrize(("frames", "letters"), [(2, "abc"), (2, "aa"), (3, "aab")])
def test_too_many_letters_for_the_time(frames: int, letters: str) -> None:
    # Two equal letters in a row need a blank between them: "aa" in 2 frames cannot be sung.
    with pytest.raises(lyrics.LyricsError):
        lyrics.ctc_align(np.zeros((frames, len(LABELS)), np.float32), [LABELS.index(c) for c in letters], 0)


def test_a_held_last_letter_belongs_to_its_word() -> None:
    v = voice([("be", 0.2, 0.6)], 2.0)
    v.sung[30:60] = True  # the voice holds the "e" until 1.2 s
    words = lyrics.place_words(
        [lyrics.Line("be", [lyrics.Word("be", "be")], 0)], v, [lyrics.Segment([0], 0, 100, True)]
    )
    assert words[0][0][1] == pytest.approx(1.2, abs=0.03)


def test_the_model_windows_keep_the_twenty_millisecond_grid() -> None:
    samples = lyrics.MODEL_RATE * 95
    spans = lyrics.windows(samples)
    frames = [(b - a - lyrics.RECEPTIVE) // lyrics.HOP + 1 for a, b in spans]
    assert frames[:3] == [1500, 1500, 1500]  # 30 s each: frame f is at f x 20 ms
    assert sum(frames) == samples // lyrics.HOP - 1


# Which lines are sung where.


def full_song(sung_lines: list[tuple[str, float]], length: float, blur: set[str]) -> lyrics.Voice:
    return voice([(t, s, s + 4.0) for t, s in sung_lines], length, blur)


def test_a_song_is_placed_line_by_line_choruses_by_their_order() -> None:
    order = [*VERSE_1, *CHORUS, *VERSE_2, *CHORUS]
    v = full_song([(t, 1 + 5 * k) for k, t in enumerate(order)], 42, set(CHORUS))
    data = lyrics.place("\n".join(order), v, song(21, [(7, "")]))
    starts = [ln["words"][0]["start"] for ln in data["lines"]]
    assert all(s is not None for s in starts)
    assert [round(s) for s in starts] == [1 + 5 * k for k in range(8)]
    checks = [ln["check"] for ln in data["lines"]]
    assert checks[0] is None and checks[2] is not None  # verses heard, choruses placed by order


def test_a_verse_cut_from_this_version_is_left_out() -> None:
    pasted = [*VERSE_1, *CHORUS, *VERSE_3, *VERSE_2, *CHORUS]
    sung = [*VERSE_1, *CHORUS, *VERSE_2, *CHORUS]  # this recording has no third verse
    v = full_song([(t, 1 + 5 * k) for k, t in enumerate(sung)], 42, set(CHORUS))
    data = lyrics.place("\n".join(pasted), v, song(21, [(7, "")]))
    placed = [ln["text"] for ln in data["lines"] if ln["sung"]]
    assert placed == sung
    assert all("not sung" in ln["check"] for ln in data["lines"] if ln["text"] in VERSE_3)


def test_lines_sung_without_a_pause_and_no_line_heard_clearly() -> None:
    # Lines follow each other closely (one phrase holds several), and every line is blurred: no
    # anchor, the lines are placed by their order and all are to check.
    order = [*VERSE_1, *CHORUS]
    v = voice([(t, 1 + 4.3 * k, 1 + 4.3 * k + 4.0) for k, t in enumerate(order)], 20, set(order))
    data = lyrics.place("\n".join(order), v, song(10, [(7, "")]))
    assert [ln["sung"] for ln in data["lines"]] == [True] * 4
    starts = [ln["words"][0]["start"] for ln in data["lines"]]
    assert starts == sorted(starts) and all(ln["check"] for ln in data["lines"])


def test_an_excerpt_keeps_the_lines_it_holds() -> None:
    pasted = [*VERSE_1, *CHORUS, *VERSE_2, *CHORUS, *VERSE_3]
    sung = [*VERSE_1, *CHORUS]  # the recording stops after the first chorus
    v = full_song([(t, 1 + 5 * k) for k, t in enumerate(sung)], 22, set(CHORUS))
    data = lyrics.place("\n".join(pasted), v, song(11, [(7, "")]))
    assert [ln["text"] for ln in data["lines"] if ln["sung"]] == sung


def test_no_words_and_letters_the_model_cannot_hear() -> None:
    v = voice([("abc", 0.2, 0.8)], 1.2)
    with pytest.raises(lyrics.LyricsError, match="no words"):
        lyrics.place("G D Em\n", v, song(1, [(7, "")]))
    v = lyrics.Voice(v.emission[:, :5], LABELS[:5], v.sung)
    with pytest.raises(lyrics.LyricsError, match="cannot hear"):
        lyrics.place("zebra\n", v, song(1, [(7, "")]))


# Chords on the words.


def test_a_chord_goes_on_the_word_sung_held_or_coming() -> None:
    words = {0: [(1.0, 1.4), (2.10, 2.5)], 1: [(6.0, 6.3)]}
    changes = [(1.0, 0, 0), (2.0, 1, 0), (3.0, 2, 0), (5.0, 3, 0), (1.2, 4, 0)]
    placed = lyrics.place_chords(changes, words, bpm=120, per_bar=4)
    assert [(p["line"], p["word"], p["push"]) for p in placed] == [
        (0, 0, False),  # on the word starting with it
        (0, 1, True),  # the word comes 0.1 s after the chord: a push
        (0, 1, False),  # the word is held
        (None, None, False),  # a rest: no word sung or held
        (0, 0, False),  # the word is still sung
    ]


def test_chord_changes_are_read_from_the_chart() -> None:
    chart = song(3, [(7, ""), (7, ""), (2, "")])
    assert lyrics.chord_changes(chart) == [(0.0, 0, 0), (4.0, 2, 0)]


# Files and the command.


def test_the_page_gets_its_lyrics_as_data_and_script(tmp_path: Path) -> None:
    data = {"version": 1, "lines": [{"text": "</script><b>x</b>"}], "chords": []}
    lyrics.write(tmp_path, data)
    assert json.loads((tmp_path / lyrics.LYRICS).read_text()) == data
    js = (tmp_path / lyrics.LYRICS_JS).read_text()
    assert js.startswith("window.WOODSHED_LYRICS = ") and "</script>" not in js


def test_a_page_without_stems_says_so(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WOODSHED_CACHE", str(tmp_path / "cache"))
    page = tmp_path / "x.woodshed"
    page.mkdir()
    with pytest.raises(lyrics.LyricsError, match="no manifest"):
        lyrics.stems_folder(page)
    (page / "woodshed.json").write_text(json.dumps({"settings": {"source": "abc"}}))
    with pytest.raises(lyrics.LyricsError, match="not in the cache"):
        lyrics.stems_folder(page)


def test_the_lyrics_command_writes_the_page_lyrics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    order = [*VERSE_1, *CHORUS]
    v = full_song([(t, 1 + 5 * k) for k, t in enumerate(order)], 22, set(CHORUS))
    page = tmp_path / "Song.woodshed"
    page.mkdir()
    monkeypatch.setattr(lyrics, "stems_folder", lambda p: tmp_path)
    monkeypatch.setattr(lyrics, "listen", lambda path, cache, offline=False: v)
    monkeypatch.setattr(lyrics, "page_song", lambda p: song(11, [(7, "")]))
    words = tmp_path / "words.txt"
    words.write_text("\n".join(order), encoding="utf-8")
    assert cli.main(["lyrics", str(page), str(words)]) == 0
    assert "4 of 4 lines placed" in capsys.readouterr().out
    data = json.loads((page / lyrics.LYRICS).read_text())
    assert data["lines"][0]["words"][0]["text"] == "morning" and data["chords"]


def test_a_damaged_model_cache_is_heard_again(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from woodshed import audio

    (tmp_path / lyrics.CACHE).write_bytes(b"not a zip")
    runs = []

    def model(vocals: Any, sr: int, offline: bool) -> tuple[Any, list[str]]:
        runs.append(1)
        return np.zeros((10, len(LABELS)), np.float32), LABELS

    monkeypatch.setattr(audio, "load", lambda path: np.zeros(audio.SR, np.float32))
    monkeypatch.setattr(lyrics, "_run_model", model)
    v = lyrics.listen(tmp_path / "vocals.flac", tmp_path)
    assert runs == [1] and v.emission.shape == (10, len(LABELS))
    lyrics.listen(tmp_path / "vocals.flac", tmp_path)  # cached now
    assert runs == [1] and not list(tmp_path.glob(".*"))


@pytest.mark.parametrize("encoding", ["utf-8-sig", "cp1252", "utf-16"])
def test_the_command_reads_text_files_from_windows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, encoding: str
) -> None:
    v = full_song([(t, 1 + 5 * k) for k, t in enumerate(VERSE_1)], 12, set())
    page = tmp_path / "Song.woodshed"
    page.mkdir()
    monkeypatch.setattr(lyrics, "stems_folder", lambda p: tmp_path)
    monkeypatch.setattr(lyrics, "listen", lambda path, cache, offline=False: v)
    monkeypatch.setattr(lyrics, "page_song", lambda p: song(6, [(7, "")]))
    words = tmp_path / "words.txt"
    words.write_bytes(("[Verse]\n" + "\n".join(VERSE_1) + "\nd\u00e9j\u00e0\n").encode(encoding))
    assert cli.main(["lyrics", str(page), str(words)]) == 0
    data = json.loads((page / lyrics.LYRICS).read_text())
    assert data["lines"][0]["tag"] == "Verse" and data["lines"][-1]["text"] == "d\u00e9j\u00e0"
