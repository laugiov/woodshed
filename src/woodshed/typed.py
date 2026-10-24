"""The words typed by hand (spec 029): a sung line typed as a singer writes it under the bars, kept beside the
band's fixes of the placed words (spec 028's store), with no speech model.

    When you walk, | I stum- ble _ on

The words before the first `|` start on beat one of the line's first bar; `|` is a bar line, the word after it on
the next bar's beat one (`| |`: a bar with no new word). In a bar the words share the beats by syllables; `_` is one
more syllable holding the word before it (at the start of a line, a rest); a word ending with `-` is joined to the
next ("stum-ble"); "(ooh)" is a backing vocal. Every place is an index in the song's tracked beats (`at`), every
time is computed here from the beats: the page never sends one. The page reads a line the same way
(core/typed-words.js), checked against this on tests/words_typed_cases.json.
"""

from __future__ import annotations

import itertools
import math
import re
import unicodedata
from collections.abc import Sequence
from typing import Any

MAX_BARS = 16  # bars in one typed line
MAX_WORDS = 40  # as a line fixed on the sheet (app.LINE_WORDS_MAX)
MAX_CHARS = 200  # code points (app.WORD_TEXT_MAX)
KEY = re.compile(r"t[0-9a-f]{8}")  # a typed line's key in the store, beside the placed lines' indices
# One syllable: a group of vowels (Latin, Cyrillic, Greek), or one character of Chinese, Japanese or Korean.
VOWELS = re.compile("[aeiouyàâäéèêëîïôöùûüáíóúýãõåæœøаеёиоуыэюяіїєαεηιουωάέήίόύώϊϋΐΰ]+")  # noqa: RUF001
CJK = re.compile("[぀-ヿ㐀-䶿一-鿿가-힯豈-﫿]")
BACKING = re.compile(r"\(([^)]*)\)")
HOLD = "_"

# Said to the page when a request is refused (the page translates them).
OVERLAP = "another typed line is sung there: move it or take it off first"
NEXT = "the next line starts here: join the lines first"
BEFORE = "the line before is still sung here"


class TypedError(ValueError):
    """A typed line the notation or the song cannot hold: `code` names why (the page says it in words), `bar`
    the song's bar (from 1) when one bar is the reason."""

    def __init__(self, code: str, bar: int | None = None) -> None:
        super().__init__(f"text: {code}" + (f" (bar {bar})" if bar is not None else ""))
        self.code, self.bar = code, bar


def _ms(t: float) -> float:
    """Rounded to the millisecond as the page rounds (Math.round, halves up)."""
    return math.floor(t * 1000 + 0.5) / 1000


SILENT = re.compile("([b-df-hj-np-tv-z])(e|es|ed)$")  # a final e not sung: "care", "comes", "walked"


def _silent_e(w: str) -> bool:
    """A final e, es or ed after a consonant, not sung ("love", "time", "walked"), but "wanted", "roses",
    "places" and "table" sing it."""
    m = SILENT.search(w)
    if m is None:
        return False
    c, end = m.groups()
    if end == "ed":
        return c not in "td"
    if end == "es":
        return c not in "sxz" and not w.endswith(("ches", "shes", "ges", "ces"))
    return not (c == "l" and len(w) >= 3 and w[-3] not in "aeiouy")


def syllables(word: str) -> int:
    """How many syllables a word takes in its bar: its vowel groups (a final silent e dropped when another is
    there, "qu" a consonant), one per CJK character, at least one. The page counts them the same way."""
    w = word.lower()
    cjk = len(CJK.findall(w))
    letters = re.sub(r"[\W\d_]", "", CJK.sub(" ", w)).replace("qu", "q")
    n = len(VOWELS.findall(letters))
    if n > 1 and _silent_e(letters):
        n -= 1
    return max(1, cjk + n)


def _beat_length(beats: Sequence[float], per: int, last: bool) -> float:
    n = len(beats)
    span = min(n - 1, per)
    return (beats[-1] - beats[-1 - span]) / span if last else (beats[span] - beats[0]) / span


def beat_time(song: dict[str, Any], at: float) -> float:
    """The time of beat `at` (an index in song["beats"], halves and quarters between two beats), to the ms. Before
    the first tracked beat and after the last, the nearest bar's beat length carries on."""
    beats = song["beats"]
    n = len(beats)
    if n == 0:
        return 0.0
    if n == 1:
        return _ms(max(0.0, beats[0] + at * 60 / float(song["bpm"])))
    per = int(song["beats_per_bar"])
    if at > n - 1:
        t = beats[-1] + (at - (n - 1)) * _beat_length(beats, per, True)
    elif at < 0:
        t = beats[0] + at * _beat_length(beats, per, False)
    else:
        i = min(math.floor(at), n - 2)
        t = beats[i] + (at - i) * (beats[i + 1] - beats[i])
    return _ms(max(0.0, t))


def beat_at(song: dict[str, Any], t: float) -> float:
    """The beat index sounding at time t, with its fraction (beat_time backwards)."""
    beats = song["beats"]
    n = len(beats)
    if n < 2:
        return 0.0
    per = int(song["beats_per_bar"])
    if t >= beats[-1]:
        return float(n - 1 + (t - beats[-1]) / _beat_length(beats, per, True))
    if t < beats[0]:
        return float((t - beats[0]) / _beat_length(beats, per, False))
    lo, hi = 0, n - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if beats[mid] <= t:
            lo = mid
        else:
            hi = mid
    return float(lo + (t - beats[lo]) / (beats[lo + 1] - beats[lo]))


def bar_of(song: dict[str, Any], at: float) -> int:
    """The bar (from 0) beat `at` falls in, as the bar lines are now: a bar-line move keeps the beats and moves
    first_beat, so the same beat may read as another bar."""
    return math.floor((at - int(song["first_beat"])) / int(song["beats_per_bar"]) + 1e-9)


def _clean(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", text).replace("\ufeff", " ").split())  # a byte order mark: a space


def _tokens(segment: str) -> list[str]:
    return [t for t in BACKING.sub(" ", segment).split() if t != "-"]


def _bars(text: str) -> tuple[list[str], int]:
    """The line's bars as typed (each with its words, holds and backing vocals), and how many bars with no word
    came first (they move the line's start: the line starts with its first word's bar)."""
    raw = [" ".join(s.split()) for s in text.split("|")]
    if len(raw) > MAX_BARS:
        raise TypedError("bars")
    lead = 0
    while lead < len(raw) and not [t for t in _tokens(raw[lead]) if t != HOLD]:
        lead += 1
    if lead == len(raw):
        raise TypedError("empty")
    return raw[lead:], lead


def _joined(words: Sequence[str]) -> str:
    out = ""
    for w in words:
        joined = len(w) > 1 and w.endswith("-")
        out += w[:-1] if joined else w + " "
    return out.strip()


def typed_line(
    text: str, at: float, song: dict[str, Any], old: dict[str, Any] | None = None, until: float | None = None
) -> dict[str, Any]:
    """A line typed in the notation, from beat `at` (the index in song["beats"] of its first bar's beat one): its
    text, backing vocals, notation as typed, and words with their beats and times. `old`: the line as stored
    before ({"notation", "words"}): the words of a bar whose text did not change stay where they were (a word
    moved by hand stays put). `until`: the next typed line's first start, which its last word never passes."""
    text = _clean(text)
    if not text:
        raise TypedError("empty")
    if len(text) > MAX_CHARS:
        raise TypedError("length")
    bars, lead = _bars(text)
    per, count = int(song["beats_per_bar"]), len(song["bars"])
    at += lead * per
    backing = [b.strip() for b in BACKING.findall(text) if b.strip()]
    texts: list[str] = []
    starts: list[float] = []  # in beats
    hold_end: list[float] = []  # the end of each word's syllables and of the holds after it, in beats
    last = -1  # the last word begun: a hold holds it, across a bar line too
    for k, segment in enumerate(bars):
        tokens = _tokens(segment)
        start = at + k * per
        if not 0 <= bar_of(song, start) < count:
            raise TypedError("end")
        units: list[int] = []  # the word each syllable belongs to; -1: a hold
        for tok in tokens:
            if tok == HOLD:
                units.append(-1)
                continue
            texts.append(tok)
            units.extend([len(texts) - 1] * syllables(tok))
        size = len(units)
        if not size:
            continue
        grid = next((g for g in (1.0, 0.5, 0.25) if size <= per / g), None)
        if grid is None:
            raise TypedError("crowded", bar_of(song, start) + 1)
        slots = round(per / grid)
        pos = [start + math.floor(j * slots / size) * grid for j in range(size)] + [start + per]
        for j, w in enumerate(units):
            if w > last:  # a word begins
                starts.append(pos[j])
                hold_end.append(pos[j + 1])
                last = w
            elif last >= 0:  # its next syllable, or a hold
                hold_end[last] = pos[j + 1]
    if not texts:
        raise TypedError("empty")
    if len(texts) > MAX_WORDS:
        raise TypedError("words")
    kept = _kept(bars, at, song, old)
    out: list[dict[str, Any]] = [
        dict(kept[k]) if k in kept else {"text": tok, "at": starts[k], "start": beat_time(song, starts[k])}
        for k, tok in enumerate(texts)
    ]
    for k, word in enumerate(out):
        nxt = out[k + 1]["start"] if k + 1 < len(out) else None
        if k in kept:
            word["end"] = word["end"] if nxt is None else min(word["end"], nxt)
        else:
            word["end"] = nxt if nxt is not None else beat_time(song, hold_end[k])
        if nxt is None and until is not None and until > word["start"]:
            word["end"] = min(word["end"], until)
        word["end"] = max(word["end"], word["start"])
    return {"text": _joined(texts), "backing": backing, "notation": " ".join(" | ".join(bars).split()), "words": out}


def _kept(
    bars: Sequence[str], at: float, song: dict[str, Any], old: dict[str, Any] | None
) -> dict[int, dict[str, Any]]:
    """The words of the bars typed as before, by their index in the new line: as they were stored."""
    if not old or not isinstance(old.get("notation"), str) or not old.get("words"):
        return {}
    try:
        old_bars, _ = _bars(_clean(old["notation"]))
    except TypedError:
        return {}
    old_words = old["words"]
    counts = [sum(1 for t in _tokens(s) if t != HOLD) for s in old_bars]
    if sum(counts) != len(old_words) or not all(isinstance(w.get("at"), (int, float)) for w in old_words):
        return {}
    old_start = bar_of(song, old_words[0]["at"])
    by_bar: dict[int, tuple[str, list[dict[str, Any]]]] = {}
    i = 0
    for k, (s, n) in enumerate(zip(old_bars, counts, strict=True)):
        by_bar[old_start + k] = (s, old_words[i : i + n])
        i += n
    out: dict[int, dict[str, Any]] = {}
    start = bar_of(song, at)
    i = 0
    for k, s in enumerate(bars):
        n = sum(1 for t in _tokens(s) if t != HOLD)
        was = by_bar.get(start + k)
        if was is not None and was[0] == s and len(was[1]) == n:
            for j in range(n):
                out[i + j] = was[1][j]
        i += n
    return out


def notation_after_move(
    notation: str, before: Sequence[dict[str, Any]], after: Sequence[dict[str, Any]], song: dict[str, Any]
) -> str:
    """The notation of a typed line once a word moved: each bar typed as before when it holds the same words,
    else its words written plainly (their beats are kept in the store; the notation only reads back)."""
    try:
        old_bars, _ = _bars(_clean(notation))
    except TypedError:
        old_bars = []
    counts = [sum(1 for t in _tokens(s) if t != HOLD) for s in old_bars]
    old_by_bar: dict[int, tuple[str, list[int]]] = {}
    if sum(counts) == len(before):
        start = bar_of(song, before[0]["at"])
        i = 0
        for k, (s, n) in enumerate(zip(old_bars, counts, strict=True)):
            old_by_bar[start + k] = (s, list(range(i, i + n)))
            i += n
    bars_of = [bar_of(song, w["at"]) for w in after]
    first, last = bars_of[0], bars_of[-1]
    out = []
    for b in range(first, last + 1):
        mine = [k for k, x in enumerate(bars_of) if x == b]
        was = old_by_bar.get(b)
        out.append(was[0] if was is not None and was[1] == mine else " ".join(after[k]["text"] for k in mine))
    return " | ".join(out)


def move(
    words: Sequence[dict[str, Any]], wi: int, at: float, song: dict[str, Any], lo: float, hi: float
) -> list[dict[str, Any]]:
    """Word `wi` of a line put on beat `at`: the words it overtakes pushed half a beat on (the line's order never
    changes), each moved word keeping its length; the others exactly as they were. Refused (TypedError NEXT or
    BEFORE) when a word would start at or after `hi` (the next line's start) or before `lo` (the line before's
    end). Typed words keep their `at`; placed words get none."""
    if not 0 <= wi < len(words) or not isinstance(words[wi].get("start"), (int, float)):
        raise TypedError("word")
    timed = [k for k, w in enumerate(words) if isinstance(w.get("start"), (int, float))]
    ats = {k: (words[k]["at"] if "at" in words[k] else beat_at(song, words[k]["start"])) for k in timed}
    new = dict(ats)
    new[wi] = at
    changed = {wi}
    pos = timed.index(wi)
    for a, b in zip(timed[pos:], timed[pos + 1 :], strict=False):  # later words overtaken
        if new[b] <= new[a]:
            new[b] = new[a] + 0.5
            changed.add(b)
    for a, b in zip(reversed(timed[: pos + 1]), reversed(timed[:pos]), strict=False):  # earlier ones
        if new[b] >= new[a]:
            new[b] = new[a] - 0.5
            changed.add(b)
    out = [dict(w) for w in words]
    for k in changed:
        start = beat_time(song, new[k])
        if start >= hi:
            raise TypedError("next")
        if start < lo or new[k] < 0:
            raise TypedError("before")
        length = max(0.0, words[k]["end"] - words[k]["start"]) if isinstance(words[k].get("end"), (int, float)) else 0.0
        out[k]["start"], out[k]["end"] = start, _ms(start + length)
        if "at" in words[k]:
            out[k]["at"] = new[k]
    for i, k in enumerate(timed):  # no word lasts past the next one's start, nor past the next line
        nxt = out[timed[i + 1]]["start"] if i + 1 < len(timed) else hi
        if k in changed or out[k]["end"] > nxt:
            out[k]["end"] = max(out[k]["start"], min(out[k]["end"], nxt))
    return out


def span(line: Any) -> tuple[float, float] | None:
    """A line's time, its first word's start to its last word's end."""
    words = [w for w in (line.get("words") or []) if isinstance(w, dict)] if isinstance(line, dict) else []
    times = [
        (w["start"], w["end"])
        for w in words
        if isinstance(w.get("start"), (int, float)) and isinstance(w.get("end"), (int, float))
    ]
    return (min(s for s, _ in times), max(e for _, e in times)) if times else None


def with_typed(data: dict[str, Any], entries: dict[str, Any]) -> dict[str, Any]:
    """The typed lines on the sheet (W.typedWords.withTyped in the page): added after the placement's lines (whose
    indices the band's fixes name), in time order; a placed line whose time meets a typed line's is covered:
    off the sheet while the typed line is there."""
    typed = []
    for k, e in entries.items():
        if not (isinstance(k, str) and KEY.fullmatch(k) and isinstance(e, dict) and e.get("typed") is True):
            continue
        lines = e.get("lines")
        if not isinstance(lines, list) or not lines or not isinstance(lines[0], dict):
            continue
        ln = lines[0]
        line = {
            "text": ln.get("text", ""), "tag": ln.get("tag") or "", "block": -1,
            "backing": list(ln.get("backing") or []),
            "sung": True, "check": None, "typed": True, "key": k, "words": [dict(w) for w in ln.get("words") or []],
        }  # fmt: skip
        if span(line) is not None:
            typed.append(line)
    if not typed:
        return data
    typed.sort(key=lambda ln: span(ln)[0])  # type: ignore[index]
    spans = [span(ln) for ln in typed]
    lines = list(data.get("lines") or [])
    for i, ln in enumerate(lines):
        if not isinstance(ln, dict) or not ln.get("sung"):
            continue
        s = span(ln)
        if s is not None and any(s[0] < t[1] and t[0] < s[1] for t in spans if t is not None):
            lines[i] = {**ln, "sung": False, "covered": True}
    return {**data, "lines": lines + typed}


# A whole text laid by tapping along (spec 029-2): each line starts where a tap fell.

LAST_BARS = 2  # the last line tapped has no next tap: its words fit in two bars at most
QUARTER = 4  # taps snap to the nearest quarter beat


def snap(at: float) -> float:
    """A tap's beat index snapped to the nearest quarter beat (halves up), as the page snaps it before sending."""
    return math.floor(at * QUARTER + 0.5) / QUARTER


def _bar_notation(texts: Sequence[str], ats: Sequence[float], song: dict[str, Any]) -> str:
    """The words of a laid line written in the notation, a `|` at each bar line: the line editor reads it back."""
    bars = [bar_of(song, a) for a in ats]
    return " | ".join(
        " ".join(t for t, b in zip(texts, bars, strict=True) if b == k) for k in range(bars[0], bars[-1] + 1)
    )


def tapped_lines(lines: Sequence[tuple[str, str]], taps: Sequence[float], song: dict[str, Any]) -> list[dict[str, Any]]:
    """The lines (text, part name) laid from the taps, one tap a line from the first (snapped to a quarter beat): a
    line starts on its tap and owns the beats up to the next tap (the last one two bars at most). Its syllables take
    one beat each from the tap, or a half, or a quarter, the coarsest that fits; more than that, evenly in time. A
    word starts on its first syllable; `_` holds the word before it one syllable more. Lines after the last tap are
    not laid. Every time computed from the beats."""
    per = int(song["beats_per_bar"])
    end = int(song["first_beat"]) + len(song["bars"]) * per
    ats = [snap(float(t)) for t in taps]
    if len(ats) > len(lines):
        raise TypedError("taps")
    if any(b <= a for a, b in itertools.pairwise(ats)):
        raise TypedError("taps")
    if any(a < 0 or a >= end for a in ats):
        raise TypedError("end")
    out = []
    for i, at in enumerate(ats):
        text, tag = lines[i]
        clean = _clean(text)
        until = ats[i + 1] if i + 1 < len(ats) else min(end, at + LAST_BARS * per)
        span_ = until - at
        texts: list[str] = []
        units: list[int] = []
        for tok in _tokens(clean):
            if tok == "|":
                continue
            if tok == HOLD:
                units.append(-1)
                continue
            texts.append(tok)
            units.extend([len(texts) - 1] * syllables(tok))
        while units and units[0] == -1:  # a rest before the first word: the tap is where the words start
            units.pop(0)
        if not texts:
            raise TypedError("empty")
        if len(texts) > MAX_WORDS:
            raise TypedError("words")
        size = len(units)
        grid = next((g for g in (1.0, 0.5, 0.25) if size * g <= span_ + 1e-9), span_ / size)
        pos = [at + j * grid for j in range(size + 1)]
        starts: list[float] = []
        hold_end: list[float] = []
        last = -1
        for j, w in enumerate(units):
            if w > last:
                starts.append(pos[j])
                hold_end.append(pos[j + 1])
                last = w
            else:
                hold_end[last] = pos[j + 1]
        stop = beat_time(song, until)
        words: list[dict[str, Any]] = []
        for k, tok in enumerate(texts):
            start = beat_time(song, starts[k])
            nxt = beat_time(song, starts[k + 1]) if k + 1 < len(texts) else min(beat_time(song, hold_end[k]), stop)
            words.append({"text": tok, "at": starts[k], "start": start, "end": max(start, nxt)})
        out.append({
            "text": _joined(texts), "tag": tag, "backing": [b.strip() for b in BACKING.findall(clean) if b.strip()],
            "notation": _bar_notation(texts, starts, song), "words": words,
        })  # fmt: skip
    return out
