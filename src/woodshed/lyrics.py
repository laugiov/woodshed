"""Lyrics on the chart: pasted words placed on the recording's voice, chords on their syllables.

The words come from the user (pasted); the program only finds when each one is sung, on the
isolated vocal track:

1. `listen`: a multilingual speech model (MMS, through torchaudio, with the stems extra) gives
   every 20 ms the log-probability of each letter, and of a wildcard; where the vocal track is
   silent no letter can be sung (a solo, an intro).
2. `anchors`: lines the model clearly hears (its own transcription of a sung phrase close to the
   text), kept in the order of the text. The lead voice of a verse is heard well; a chorus with
   backing vocals and held vowels is not, so choruses are rarely anchors.
3. `plan`: between two anchors, the lines in between, minus the lines sung only once that the
   model did not hear (a verse cut from this version) and minus what cannot fit the singing time
   (an excerpt). Lines placed without an anchor are marked "to check".
4. `ctc_align`: each run of lines aligned exactly in its window, a wildcard between lines (backing
   vocals, ad-libs); every letter gets its time.
5. `place_chords`: each chord change of the chart on the syllable sung then, or on the next one
   when it comes just before it (a push), else in a gap.

Measured on the owner's songs (a piano ballad, an English excerpt; a French pop song, a French
excerpt): with the text really sung, every chord lands where the published chord sheet
puts it.
"""

from __future__ import annotations

import bisect
import itertools
import json
import math
import os
import re
import unicodedata
import uuid
import zipfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt

from woodshed.errors import WoodshedError
from woodshed.sections import ROLE_NAMES

FRAME = 0.02  # seconds per model frame (wav2vec2 at 16 kHz)
VOICE_DB = 25.0  # the voice: within this of its loud singing...
VOICE_FLOOR = 10 ** (-45 / 20)  # ...and above -45 dBFS RMS
MARGIN = 0.3  # seconds of margin around the voice
GAP_JOIN = 0.8  # sung runs closer than this are one phrase
SHORTEST = 0.3  # a phrase shorter than this is noise
ANCHOR_CER = 0.45  # letter error rate under which a phrase is heard as these lines...
ANCHOR_LETTERS = 15  # ...when it holds at least this many heard letters
FAST = 0.06  # seconds a letter takes, fast singing: a window shorter than this cannot hold the text
SLOW = 0.30  # seconds a letter takes, slow singing: more time than this per letter is room for more lines
LYRICS = "lyrics.json"  # in the page folder, next to woodshed.json
LYRICS_JS = "lyrics.js"  # the same data, read by the page from disk too
CHORD = (  # a chord name, as chord sites write them: G, F#m7b5, Bb/D, Csus4, E7(#9) excepted
    r"[A-G](?:#|b|♯|♭)?(?:maj|min|m|M|dim|aug|sus|add|°|ø|\+)?\d*"
    r"(?:(?:sus|add|maj|b|#|♭|♯|\+|-)\d+)*(?:/[A-G](?:#|b|♯|♭)?)?"
)
CHORD_TOKEN = re.compile(rf"^{CHORD}$")
INLINE_CHORD = re.compile(rf"\[{CHORD}\]")  # ChordPro: [Am]Rain on the [C]roof
REPEAT = re.compile(r"(?:\s+|\s*[(\[])\s*x\s*(\d)\s*[)\]]?\s*$", re.IGNORECASE)  # " x2", "(x2)", not "box 5"
COUNT = re.compile(r"\s*[(\[]?\s*x\s*(\d)\s*[)\]]?\s*", re.IGNORECASE)  # after a part's name: "x2", "(x2)"
TAG = re.compile(r"^\s*\[([^\]]+)\]\s*(.*)$")
SECTION_WORDS = (
    r"refrain|chorus|couplet|verse|bridge|pont|intro|outro|solo|interlude|hook|"
    r"pre-?chorus|pr[eé]-?refrain"
)
# A part's name on its own row: the part word, then only a number, a roman numeral or "final", then
# ":" or "x2" (a lyric line "Solo tonight" stays a lyric line).
SECTION = re.compile(
    rf"^\s*({SECTION_WORDS})(?:\s+(?:\d+|[ivx]+\b|final|last|bis))?\s*:?\s*(?:[(\[]?\s*x\s*(\d)\s*[)\]]?)?\s*:?\s*$",
    re.IGNORECASE,
)

Floats = npt.NDArray[np.float64]


class LyricsError(WoodshedError):
    pass


@dataclass
class Word:
    text: str  # as pasted
    letters: str  # what the model can hear: a to z and the apostrophe


@dataclass
class Line:
    text: str
    words: list[Word]
    block: int  # the paragraph, or the tagged part, it belongs to
    tag: str | None = None
    backing: list[str] = field(default_factory=list)  # words in brackets: backing vocals

    @property
    def letters(self) -> str:
        return "".join(w.letters for w in self.words)


def letters_of(raw: str) -> str:
    text = unicodedata.normalize("NFKD", raw.lower().replace("\u2019", "'"))  # typographic apostrophe
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z']", "", text).strip("'")


def chord_row(row: str) -> bool:
    """A row of chords above the words (as on chord sites): dropped, the chart has the chords."""
    tokens = [t for t in re.split(r"[\s|]+", row) if t and t not in {"-", "/", "%", "N.C.", "NC"}]
    return bool(tokens) and all(CHORD_TOKEN.match(t) for t in tokens)


def _tag(row: str) -> tuple[str, int, str] | None:
    """A part's name: "[Chorus]", "[Refrain] (x2)", "Refrain x2", "Couplet 2 :". Returns the name,
    how many times the part is sung, and words that follow on the same row."""
    m = TAG.match(row)
    if m and not CHORD_TOKEN.match(m.group(1).strip()):
        rest = m.group(2).strip()
        times = COUNT.fullmatch(rest)
        if times or not rest:
            return m.group(1).strip(), int(times.group(1)) if times else 1, ""
        return m.group(1).strip(), 1, rest
    m = SECTION.match(row)
    if m:
        return row.split(":")[0].strip(), int(m.group(2)) if m.group(2) else 1, ""
    return None


SAME_PART = {
    "refrain": "chorus",
    "couplet": "verse",
    "pont": "bridge",
    "prerefrain": "prechorus",
}


def _base(tag: str | None) -> str:
    """A part's kind, in either language: "Refrain 2" and "[Chorus]" are the same part."""
    first = re.match(r"\s*([^\s\d:(\[\]]+)", (tag or "").lower())
    name = letters_of(first.group(1)) if first else ""
    return SAME_PART.get(name, name)


def parse(text: str) -> list[Line]:
    """The pasted text as sung lines.

    Parts start at a blank line or a part's name ("[Chorus]", "Refrain x2", "Couplet 2 :"); a name
    with no words under it repeats the last part of that name; "x2" repeats a part or a line.
    Rows of chords and chords in brackets inside the words ([Am]Rain on the roof) are dropped; words in
    brackets are backing vocals, kept apart."""
    lines: list[Line] = []
    blocks: list[tuple[str | None, list[Line]]] = []
    current: list[Line] = []
    tag: str | None = None
    times = 1

    def close() -> None:
        nonlocal current, tag, times
        if current:
            blocks.append((tag, current))
            for _ in range(times - 1):
                blocks.append((tag, [Line(ln.text, list(ln.words), 0, ln.tag, list(ln.backing)) for ln in current]))
        elif tag is not None:  # a part's name alone: that part again
            same = [b for t, b in blocks if _base(t) == _base(tag)]
            if same:
                for _ in range(times):
                    blocks.append((tag, [Line(ln.text, list(ln.words), 0, tag, list(ln.backing)) for ln in same[-1]]))
        current, tag, times = [], None, 1

    for raw in text.replace("\ufeff", "").splitlines():
        row = raw.strip()
        if not row:
            close()
            continue
        named = _tag(row)
        if named:
            close()
            tag, times, row = named
            if not row:
                continue
        row = INLINE_CHORD.sub("", row).strip()
        if not row or chord_row(row):
            continue
        repeat = 1
        rep = REPEAT.search(row)
        if rep and rep.start() > 0:
            repeat, row = int(rep.group(1)), row[: rep.start()].strip()
        backing = re.findall(r"\(([^)]*)\)", row)
        lead = re.sub(r"\([^)]*\)", " ", row)
        words = [Word(w, letters_of(w)) for w in re.split(r"[\s\-]+", lead) if letters_of(w)]
        if not words:  # backing vocals only: with the line before
            if current:
                current[-1].backing += backing
            elif blocks:
                blocks[-1][1][-1].backing += backing
            continue
        for _ in range(repeat):
            current.append(Line(row, list(words), 0, tag, list(backing)))
    close()
    for k, (_, block) in enumerate(blocks):
        for ln in block:
            ln.block = k
            lines.append(ln)
    return lines


# The voice: letter log-probabilities every 20 ms, and where it sings.


@dataclass
class Voice:
    emission: npt.NDArray[np.float32]  # frames x labels, log-probabilities
    labels: list[str]  # "-" the blank, "*" the wildcard, then letters
    sung: npt.NDArray[np.bool_]  # per frame: the voice is heard
    frame: float = FRAME

    @property
    def blank(self) -> int:
        return self.labels.index("-")

    @property
    def star(self) -> int:
        return self.labels.index("*")

    def masked(self) -> npt.NDArray[np.float32]:
        """No letter where the voice is silent: only the blank and the wildcard there."""
        em: npt.NDArray[np.float32] = self.emission.copy()
        silent = ~self.sung
        keep = np.zeros(em.shape[1], bool)
        keep[[self.blank, self.star]] = True
        em[np.ix_(silent, ~keep)] = -1e4
        return em


def voice_mask(vocals: npt.NDArray[np.float32], sr: int, frames: int, frame: float = FRAME) -> npt.NDArray[np.bool_]:
    hop = max(1, round(frame * sr))
    n = len(vocals) // hop
    level = np.sqrt(np.mean(vocals[: n * hop].reshape(n, hop).astype(np.float64) ** 2, axis=1)) if n else np.zeros(0)
    audible = level[level > 1e-4]
    if audible.size == 0:
        return np.zeros(frames, bool)
    on = level >= max(10 ** (-VOICE_DB / 20) * np.percentile(audible, 90), VOICE_FLOOR)
    width = max(1, int(MARGIN / frame))
    on = np.convolve(on.astype(float), np.ones(2 * width + 1), "same") > 0
    out = np.zeros(frames, bool)
    out[: min(frames, len(on))] = on[:frames]
    return out


MODEL_RATE = 16000  # the speech model's sample rate
HOP, RECEPTIVE = 320, 400  # wav2vec2: a frame every 320 samples, each seeing 400
WINDOW = MODEL_RATE * 30  # attention over a whole song would need gigabytes: 30 s at a time
CACHE = "mms_fa-2.npz"  # next to the stems; 2: windows that keep the 20 ms grid exact


def windows(samples: int) -> list[tuple[int, int]]:
    """Sample ranges for the model, 30 s apart. Each takes 80 samples more than 30 s, so it gives
    exactly 1500 frames: frame f is at f x 20 ms all through the song (cut at 30 s, a window gives
    1499 frames, and the words drift 20 ms early per 30 s)."""
    extra = RECEPTIVE - HOP
    return [(s, min(samples, s + WINDOW + extra)) for s in range(0, samples, WINDOW) if samples - s >= RECEPTIVE]


def listen(
    vocals_path: Path, cache: Path, offline: bool = False, progress: Callable[[float], None] | None = None
) -> Voice:
    """Run the speech model on the vocal track (cached next to the stems). `progress` hears the
    share of the voice heard so far, 0 to 1."""
    from woodshed import audio

    vocals = audio.load(vocals_path)
    stored = cache / CACHE
    loaded = None
    if stored.exists():
        try:
            with np.load(stored) as npz:
                loaded = npz["emission"], [str(x) for x in npz["labels"]]
        except (OSError, ValueError, KeyError, zipfile.BadZipFile):
            loaded = None  # a damaged file: heard again
    if loaded is None:
        emission, labels = _run_model(vocals, audio.SR, offline, progress)
        tmp = cache / f".{CACHE}.{os.getpid()}.{uuid.uuid4().hex[:8]}.npz"
        try:
            np.savez_compressed(tmp, emission=emission.astype(np.float16), labels=np.array(labels))
            tmp.replace(stored)
        finally:
            tmp.unlink(missing_ok=True)
    else:
        emission, labels = loaded
    emission = emission.astype(np.float32)
    return Voice(emission, labels, voice_mask(vocals, audio.SR, emission.shape[0]))


def _run_model(
    vocals: npt.NDArray[np.float32], sr: int, offline: bool, progress: Callable[[float], None] | None = None
) -> tuple[npt.NDArray[np.float32], list[str]]:
    try:
        import torch
        import torchaudio
    except ImportError as exc:
        from woodshed.errors import MissingExtra

        raise MissingExtra('placing lyrics needs the stems extra: pipx install "woodshed[stems]"') from exc
    from woodshed import models

    bundle = torchaudio.pipelines.MMS_FA
    with models._torch_hub(offline):
        model = bundle.get_model(with_star=True)
    wave = torchaudio.functional.resample(torch.from_numpy(vocals).float()[None], sr, MODEL_RATE)
    parts = []
    spans = windows(wave.shape[1])
    with torch.inference_mode():
        for k, (a, b) in enumerate(spans):
            parts.append(model(wave[:, a:b])[0][0])
            if progress is not None:
                progress((k + 1) / len(spans))
    emission: npt.NDArray[np.float32] = torch.cat(parts).numpy().astype(np.float32)
    return emission, list(bundle.get_labels(star="*"))


# Exact alignment: a CTC Viterbi path (the model's blank between letters), in numpy.


def ctc_align(
    log_probs: npt.NDArray[np.float32], tokens: Sequence[int], blank: int
) -> tuple[list[int], list[int], float]:
    """For each token, the first and the last frame where it is sung, and the path's log-probability.

    States alternate blank and token (2L+1). A token can follow the one before it directly unless
    they are the same letter (a double letter needs a blank between)."""
    T, L = log_probs.shape[0], len(tokens)
    S = 2 * L + 1
    if L == 0 or T < L:
        raise LyricsError("not enough time for the words")
    lab = np.full(S, blank)
    lab[1::2] = tokens
    skip = np.zeros(S, bool)
    skip[3::2] = np.asarray(tokens[1:]) != np.asarray(tokens[:-1])
    neg = -1e30
    score = np.full(S, neg)
    score[0], score[1] = log_probs[0, blank], log_probs[0, tokens[0]]
    back = np.zeros((T, S), np.int8)  # 0 stay, 1 from s-1, 2 from s-2
    for t in range(1, T):
        prev1 = np.concatenate([[neg], score[:-1]])
        prev2 = np.concatenate([[neg, neg], score[:-2]])
        prev2 = np.where(skip, prev2, neg)
        stacked = np.stack([score, prev1, prev2])
        choice = np.argmax(stacked, axis=0)
        score = stacked[choice, np.arange(S)] + log_probs[t, lab]
        back[t] = choice
    s = S - 1 if score[S - 1] >= score[S - 2] else S - 2
    total = float(score[s])
    if total < neg / 2:  # enough frames for the letters, not for the blanks double letters need
        raise LyricsError("not enough time for the words")
    first, last = [T] * L, [-1] * L
    for t in range(T - 1, -1, -1):
        if s % 2 == 1:
            first[s // 2] = t
            if last[s // 2] < 0:
                last[s // 2] = t
        s -= int(back[t, s])
    return first, last, total


# Which lines are sung where.


def phrases(sung: npt.NDArray[np.bool_], frame: float = FRAME) -> list[tuple[int, int]]:
    runs: list[list[int]] = []
    start = None
    for f, on in enumerate(np.append(sung, False)):
        if on and start is None:
            start = f
        elif not on and start is not None:
            if runs and (start - runs[-1][1]) * frame < GAP_JOIN:
                runs[-1][1] = f
            else:
                runs.append([start, f])
            start = None
    return [(a, b) for a, b in runs if (b - a) * frame >= SHORTEST]


def heard(voice: Voice, a: int, b: int) -> str:
    """What the model hears in frames [a, b), with no text to guide it."""
    em = voice.emission[a:b].copy()
    em[:, voice.star] = -1e9
    out, prev = [], -1
    for i in em.argmax(axis=1):
        if i != prev and i != voice.blank:
            out.append(voice.labels[i])
        prev = int(i)
    return "".join(out)


def cer(heard_text: str, text: str) -> float:
    """Letter error rate of what was heard against the text."""
    d = np.arange(len(text) + 1)
    for i, ch in enumerate(heard_text, 1):
        prev, d[0] = d.copy(), i
        for j, ct in enumerate(text, 1):
            d[j] = min(prev[j] + 1, d[j - 1] + 1, prev[j - 1] + (ch != ct))
    return float(d[len(text)]) / max(1, len(text))


@dataclass(frozen=True)
class Anchor:
    first: int  # first line
    count: int  # lines
    start: int  # frames
    end: int
    error: float


def anchors(lines: Sequence[Line], voice: Voice, spans: Sequence[tuple[int, int]]) -> list[Anchor]:
    """Phrases the model hears as 1 to 3 consecutive lines; the best chain in the text's order."""
    found: list[Anchor] = []
    for a, b in spans:
        h = heard(voice, a, b)
        if len(h) < ANCHOR_LETTERS:
            continue
        best: Anchor | None = None
        for m in (1, 2, 3):
            for i in range(len(lines) - m + 1):
                text = "".join(lines[k].letters for k in range(i, i + m))
                if len(h) < 0.6 * len(text):  # a few letters heard match too many lines
                    continue
                e = cer(h, text)
                if e <= ANCHOR_CER and (best is None or e < best.error):
                    best = Anchor(i, m, a, b, e)
        if best is not None:
            found.append(best)
    chain = _chain(lines, found)
    # A phrase holds about as many lines as its length allows: two lines heard in a phrase long
    # enough for four (choruses heard badly) is a chance match. Checked once the usual time
    # between line starts is known from the first chain.
    usual = line_time(chain, voice.sung, voice.frame)
    if usual:
        fits = [x for x in found if 0.5 <= x.count * usual / ((x.end - x.start) * voice.frame) <= 2.0]
        chain = _chain(lines, fits)
    return chain


def _chain(lines: Sequence[Line], found: list[Anchor]) -> list[Anchor]:
    """The best chain going forward in the text and in time, the clearest first."""
    found = sorted(found, key=lambda x: x.start)
    gain = [sum(len(lines[x.first + d].letters) for d in range(x.count)) * (1 - x.error) for x in found]
    best_total = list(gain)
    prev = [-1] * len(found)
    for j in range(len(found)):
        for i in range(j):
            if found[i].first + found[i].count <= found[j].first and best_total[i] + gain[j] > best_total[j]:
                best_total[j], prev[j] = best_total[i] + gain[j], i
    if not found:
        return []
    j = int(np.argmax(best_total))
    chain = []
    while j >= 0:
        chain.append(found[j])
        j = prev[j]
    return chain[::-1]


def repeated(lines: Sequence[Line]) -> list[bool]:
    """Lines whose text comes back elsewhere with a neighbour (a chorus), as opposed to lines sung
    once (a verse): a verse the model did not hear is taken as not sung in this recording."""
    texts = [ln.letters for ln in lines]
    out = []
    for i, t in enumerate(texts):
        same = [j for j, u in enumerate(texts) if j != i and cer(t, u) <= 0.2]
        out.append(bool(same))
    return out


@dataclass
class Segment:
    lines: list[int]
    start: int
    end: int
    anchored: bool  # its first line is a line the model heard


LINE_ROOM = 0.85  # a line needs this share of the usual time between two line starts


def line_time(chain: Sequence[Anchor], sung: npt.NDArray[np.bool_], frame: float) -> float | None:
    """The usual singing time of a line, measured between anchors that follow each other in the
    text (a song's lines are its musical phrases: about the same length). Singing time, as the
    room it is compared with: pauses and solos do not count."""
    steps = [
        float(sung[a.start : b.start].sum()) * frame / (b.first - a.first)
        for a, b in itertools.pairwise(chain)
        if 0 < b.first - a.first <= 2
    ]
    return float(np.median(steps)) if steps else None


def plan(lines: Sequence[Line], voice: Voice, chain: Sequence[Anchor]) -> tuple[list[Segment], dict[int, str]]:
    """Runs of lines and their windows, and the lines left out with the reason.

    An anchor marks where its line starts. Between two anchors (or before the first, after the
    last) the lines of the text in between are sung in order, except a line sung once in the text
    that the model did not hear (a verse cut from this version), and except what the singing time
    cannot hold (an excerpt): each line needs about the usual time between two line starts."""
    n, frames = len(lines), voice.sung.shape[0]
    again = repeated(lines)
    usual = line_time(chain, voice.sung, voice.frame)
    marks = [(0, 0, False)] + [(x.first, x.start, True) for x in chain] + [(n, frames, False)]
    segments: list[Segment] = []
    left: dict[int, str] = {}
    heard_lines = {x.first + d for x in chain for d in range(x.count)}
    for (line_from, start, anchored), (line_to, end, _) in itertools.pairwise(marks):
        candidates = list(range(line_from, line_to))
        room = float(voice.sung[start:end].sum()) * voice.frame
        need = LINE_ROOM * usual if usual else None

        def fits(chosen: list[int], room: float = room, need: float | None = need) -> bool:
            if need is not None:
                return len(chosen) * need <= room + 1e-9
            return sum(len(lines[i].letters) for i in chosen) * FAST * 2 <= room + 1e-9

        kept = list(candidates)
        # Too many lines for the time: first out, the lines sung once that the model did not hear
        # (a verse cut from this version), from the end; then the last lines (an excerpt).
        for i in reversed(candidates):
            if fits(kept):
                break
            if i not in heard_lines and not again[i]:
                kept.remove(i)
                left[i] = "not heard: maybe not sung in this recording"
        while kept and not fits(kept) and kept[-1] not in heard_lines:
            left[kept.pop()] = "no room left: maybe not sung in this recording"
        if kept and end > start:
            segments.append(Segment(kept, start, end, anchored))
    return segments, left


# Placing: words in time, chords on syllables.


def place_words(
    lines: Sequence[Line], voice: Voice, segments: Sequence[Segment]
) -> dict[int, list[tuple[float, float]]]:
    """Each line's words as (start, end) seconds."""
    em = voice.masked()
    dictionary = {c: i for i, c in enumerate(voice.labels)}
    out: dict[int, list[tuple[float, float]]] = {}
    runs = phrases(voice.sung, voice.frame)
    for seg in segments:
        tokens, owner = [voice.star], []
        for li in seg.lines:
            for wi, w in enumerate(lines[li].words):
                for c in w.letters:
                    owner.append((li, wi))
                    tokens.append(dictionary[c])
            tokens.append(voice.star)
        letters = [k for k, t in enumerate(tokens) if t != voice.star]
        try:
            first, last, _ = ctc_align(em[seg.start : seg.end], tokens, voice.blank)
        except LyricsError:
            continue
        times: dict[tuple[int, int], list[tuple[int, int]]] = {}
        for k, (li, wi) in zip(letters, owner, strict=True):
            times.setdefault((li, wi), []).append((first[k], last[k]))
        spans = [
            (
                (seg.start + times[(li, wi)][0][0]) * voice.frame,
                (seg.start + times[(li, wi)][-1][1] + 1) * voice.frame,
                li,
            )
            for li in seg.lines
            for wi in range(len(lines[li].words))
        ]
        # A word lasts until the next word starts or the voice stops: the model's wildcard is free,
        # so a held vowel's frames are not reliably the letter's.
        for k, (start, end, li) in enumerate(spans):
            nxt = spans[k + 1][0] if k + 1 < len(spans) else seg.end * voice.frame
            run_end = next(
                (b * voice.frame for a, b in runs if a * voice.frame <= end - voice.frame < b * voice.frame), end
            )
            out.setdefault(li, []).append((start, max(end, min(nxt, run_end))))
    return out


def chord_changes(song: dict[str, Any]) -> list[tuple[float, int, int]]:
    """(time, bar, chord index) of each change of chord in the chart."""
    beats, first, per = song["beats"], song["first_beat"], song["beats_per_bar"]
    out, prev = [], None
    for u, bar in enumerate(song["bars"]):
        pos = 0
        for k, c in enumerate(bar["chords"]):
            name = (c["pc"], c["quality"])
            i = first + u * per + pos
            if name != prev and 0 <= i < len(beats):
                out.append((float(beats[i]), u, k))
            prev = name
            pos += c["beats"]
    return out


def place_chords(
    changes: Sequence[tuple[float, int, int]],
    words: dict[int, list[tuple[float, float]]],
    bpm: float,
    per_bar: int,
) -> list[dict[str, Any]]:
    """Each change on the word sung then: the next word if it starts within a short push after
    the change, else the word still sung or held (up to half a bar after it ends), else a gap."""
    push = min(60 / bpm / 2, 0.2)
    hold = 60 / bpm * per_bar / 2
    flat = sorted((s, e, li, wi) for li, ws in words.items() for wi, (s, e) in enumerate(ws) if s == s)
    starts = [w[0] for w in flat]
    out = []
    for t, bar, index in changes:
        k = int(np.searchsorted(starts, t))
        place: dict[str, Any] = {"bar": bar, "index": index, "line": None, "word": None, "push": False}
        if k < len(flat) and flat[k][0] - t <= push:
            place.update(line=flat[k][2], word=flat[k][3], push=flat[k][0] > t + 0.05)
        elif k > 0 and t - flat[k - 1][1] < hold:
            place.update(line=flat[k - 1][2], word=flat[k - 1][3])
        out.append(place)
    return out


SQUEEZED = 0.4  # a line sung in less than this share of the usual line time is not sung there


def _ratio(line: Line, words: Sequence[tuple[float, float]], usual: float | None) -> float:
    """How long the line is sung against the least it needs: under 1, it is squeezed."""
    spans = [(s, e) for s, e in words if s == s]
    if not spans:
        return 0.0
    length = max(e for _, e in spans) - min(s for s, _ in spans)
    return length / max(len(line.letters) * FAST * 0.5, SQUEEZED * usual if usual else 0.0, 1e-9)


def _squeezed(line: Line, words: Sequence[tuple[float, float]], usual: float | None) -> bool:
    return _ratio(line, words, usual) < 1.0


def place(text: str, voice: Voice, song: dict[str, Any], language: str = "auto") -> dict[str, Any]:
    """The lyrics file of a page: lines with their words in time, chords on the words."""
    lines = parse(text)
    if not lines:
        raise LyricsError("no words in the text")
    unknown = {c for ln in lines for c in ln.letters if c not in voice.labels}
    if unknown:
        raise LyricsError("letters the model cannot hear: " + "".join(sorted(unknown)))
    chain = anchors(lines, voice, phrases(voice.sung, voice.frame))
    segments, left = plan(lines, voice, chain)
    anchored = {x.first + d for x in chain for d in range(x.count)}
    usual = line_time(chain, voice.sung, voice.frame)
    # A line squeezed into a fraction of a second is not sung there: the most squeezed one out,
    # the rest placed again; one at a time, as too many lines squeeze their neighbours too.
    for _ in range(len(lines)):
        words = place_words(lines, voice, segments)
        ratio = {li: _ratio(lines[li], ws, usual) for li, ws in words.items() if li not in anchored}
        squeezed = [li for li, r in ratio.items() if r < 1.0]
        if not squeezed:
            break
        worst = min(squeezed, key=lambda li: ratio[li])
        left[worst] = "squeezed out: maybe not sung in this recording"
        segments = [
            Segment([i for i in seg.lines if i != worst], seg.start, seg.end, seg.anchored)
            for seg in segments
            if set(seg.lines) - {worst}
        ]
    else:
        words = place_words(lines, voice, segments)  # the loop ran out: the last removal placed
    for li in range(len(lines)):
        if li not in words and li not in left:
            left[li] = "could not be placed here: listen, then place it by hand"
    out_lines = []
    for li, line in enumerate(lines):
        ws = words.get(li)
        check = left.get(li)
        if ws is not None and li not in anchored and check is None:
            check = "placed by the order of the text: listen to it"
        if ws is not None and _squeezed(line, ws, usual):
            check = "squeezed: the words may not be sung here"
        out_lines.append(
            {
                "text": line.text,
                "tag": line.tag,
                "block": line.block,
                "backing": line.backing,
                "sung": ws is not None,
                "check": check,
                "words": [
                    {
                        "text": w.text,
                        "start": None if ws is None or ws[k][0] != ws[k][0] else round(ws[k][0], 3),
                        "end": None if ws is None or ws[k][1] != ws[k][1] else round(ws[k][1], 3),
                    }
                    for k, w in enumerate(line.words)
                ],
            }
        )
    chords = place_chords(chord_changes(song), words, float(song["bpm"]), int(song["beats_per_bar"]))
    out = {"version": 1, "language": language, "text": text, "lines": out_lines, "chords": chords}
    named = sections_by_words(song, out)
    if named is not None:
        out["sections"] = named
    return out


# Naming the parts by their words.

SHARED_LINES = 0.5  # two parts sharing this share of the lines of the shorter one are one part


def bar_starts(song: dict[str, Any]) -> list[float]:
    """The time each bar starts: its first beat, or counted on from the tracked beats."""
    beats, first, per = song["beats"], int(song["first_beat"]), int(song["beats_per_bar"])
    beat = 60 / float(song["bpm"])
    out = []
    for u, bar in enumerate(song["bars"]):
        i = first + u * per
        if isinstance(bar.get("start"), (int, float)):
            out.append(float(bar["start"]))
        elif 0 <= i < len(beats):
            out.append(float(beats[i]))
        else:
            edge = 0 if i < 0 else len(beats) - 1
            out.append(float(beats[edge]) + (i - edge) * beat if beats else i * beat)
    return out


def fitting_sections(sections: Any, bars: int) -> list[dict[str, Any]] | None:
    """Saved part names that fit a chart of `bars` bars (in order, no overlap, within its bars), as
    the page checks them (core/lyrics.js); anything else is None: the chart's own names are used."""
    if not isinstance(sections, list) or not sections:
        return None

    def whole(v: Any) -> bool:  # Number.isInteger in the page: 2 and 2.0 alike
        return isinstance(v, (int, float)) and not isinstance(v, bool) and float(v).is_integer()

    end = 0
    for sec in sections:
        ok = isinstance(sec, dict) and all(isinstance(sec.get(k), str) for k in ("name", "role", "letter"))
        if not ok or not (whole(sec.get("start")) and whole(sec.get("end"))):
            return None
        if not (end <= sec["start"] < sec["end"] <= bars):
            return None
        end = sec["end"]
    keys = ("name", "role", "letter")
    return [{**{k: sec[k] for k in keys}, "start": int(sec["start"]), "end": int(sec["end"])} for sec in sections]


def sections_by_words(song: dict[str, Any], data: dict[str, Any]) -> list[dict[str, Any]] | None:
    """The chart's sections named again with the words placed on the song, or None when the words
    agree with them. The analysis names parts by their chords and loudness; the words say more:
    the same lines are the same part (a chorus whose chords were read differently the first time),
    a part sung each time just before the chorus is the pre-chorus, and the end of a stanza stays
    with its verse."""
    secs = [dict(sec) for sec in song.get("sections") or []]
    if len(secs) < 2:
        return None
    starts = bar_starts(song)
    half_bar = 60 / float(song["bpm"]) * int(song["beats_per_bar"]) / 2
    first_bars = [sec["start"] for sec in secs]
    keys: list[list[str]] = [[] for _ in secs]
    blocks: list[set[Any]] = [set() for _ in secs]
    for line in data.get("lines") or []:
        times = [w["start"] for w in line.get("words") or [] if isinstance(w.get("start"), (int, float))]
        key = letters_of(str(line.get("text", "")))
        if not line.get("sung") or not times or not key:
            continue
        u = max(0, bisect.bisect_right(starts, min(times) + half_bar) - 1)  # the bar it is sung in
        k = max(0, bisect.bisect_right(first_bars, u) - 1)
        keys[k].append(key)
        blocks[k].add(line.get("block"))

    # The end of a stanza, in a part the chart could not name, stays with the verse it ends (when
    # the words were pasted in stanzas: without blank lines, one stanza says nothing).
    stanzas = len({b for found in blocks for b in found}) > 1
    parts: list[dict[str, Any]] = []
    for k, sec in enumerate(secs):
        prev = parts[-1] if parts else None
        joins = prev and stanzas and sec["role"] == "part" and prev["role"] == "verse"
        if prev and joins and keys[k] and blocks[k] <= prev["blocks"]:
            prev["end"] = sec["end"]
            prev["keys"] += keys[k]
            continue
        parts.append({**sec, "keys": list(keys[k]), "blocks": set(blocks[k])})

    # One part per music (the chart's letter) and per words (the lines they share).
    n = len(parts)
    root = list(range(n))

    def find(i: int) -> int:
        while root[i] != i:
            root[i] = root[root[i]]
            i = root[i]
        return i

    def same_words(i: int, j: int) -> bool:
        """At least half the lines of the shorter part, and two of them (one for a one-line part):
        a hook line sung in a verse too does not make the verse the chorus."""
        a, b = set(parts[i]["keys"]), set(parts[j]["keys"])
        if not a or not b:
            return False
        shorter = min(len(a), len(b))
        return len(a & b) >= (1 if shorter == 1 else max(2, math.ceil(SHARED_LINES * shorter)))

    known: list[set[str]] = [{sec["role"]} for sec in parts]  # the roles the chart gave, per group
    for i, j in itertools.combinations(range(n), 2):
        ri, rj = find(i), find(j)
        if ri == rj or not (parts[i]["letter"] == parts[j]["letter"] or same_words(i, j)):
            continue
        apart = ("verse" in known[ri] and "chorus" in known[rj]) or ("chorus" in known[ri] and "verse" in known[rj])
        if apart:
            continue  # a verse and a chorus the chart told apart stay apart
        root[ri] = rj
        known[rj] |= known[ri]
    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)

    # A role per part: what one of its sections was known as; the chorus, else the part sung again
    # with the same words; the pre-chorus, the part always sung just before the chorus.
    role: dict[int, str] = {}
    for g, members in groups.items():
        given = [parts[m]["role"] for m in members]
        role[g] = next((r for r in ("chorus", "verse", "prechorus", "bridge", "instrumental") if r in given), given[0])
    if "chorus" not in role.values():  # the part sung again with the same words
        sung_again = [
            g for g, ms in groups.items()
            if role[g] == "part" and any(same_words(a, b) for a, b in itertools.combinations(ms, 2))
        ]  # fmt: skip
        if sung_again:
            role[max(sung_again, key=lambda g: (len(groups[g]), -groups[g][0]))] = "chorus"
    choruses = {g for g in groups if role[g] == "chorus"}
    for g, members in groups.items():
        if role[g] == "part" and len(members) > 1 and all(m + 1 < n and find(m + 1) in choruses for m in members):
            role[g] = "prechorus"

    # One letter per part (the chorus keeps its own), then the names, numbered as the chart does.
    letter = {}
    for g, members in groups.items():
        lead = next((m for m in members if parts[m]["role"] == role[g]), members[0])
        letter[g] = parts[lead]["letter"]
    roles = []
    for i, sec in enumerate(parts):
        ends = sec["role"] in ("intro", "outro") and i in (0, n - 1)
        silent = not sec["keys"] and sec["role"] != "part"  # no words to say otherwise: a solo stays a solo
        roles.append(sec["role"] if ends or silent else role[find(i)])
    total: dict[str, int] = {}
    for r in roles:
        total[r] = total.get(r, 0) + 1
    seen: dict[str, int] = {}
    out = []
    for i, sec in enumerate(parts):
        r = roles[i]
        if r == "part":
            name = f"Part {letter[find(i)]}"
        else:
            seen[r] = seen.get(r, 0) + 1
            numbered = total[r] > 1 and r not in ("intro", "outro")
            name = f"{ROLE_NAMES[r]} {seen[r]}" if numbered else ROLE_NAMES[r]
        out.append({"name": name, "role": r, "letter": letter[find(i)], "start": sec["start"], "end": sec["end"]})
    before = [{k: sec[k] for k in ("name", "role", "letter", "start", "end")} for sec in secs]
    return None if out == before else out


# Files.


def write(folder: Path, data: dict[str, Any]) -> None:
    """lyrics.json (the data) and lyrics.js (the same, for a page opened from disk)."""
    from woodshed.build import script_json

    text = json.dumps(data, ensure_ascii=False, indent=1)
    # Whole files or nothing: a phone may read them while they are written.
    for name, content in ((LYRICS, text + "\n"), (LYRICS_JS, "window.WOODSHED_LYRICS = " + script_json(data) + ";\n")):
        part = folder / f".{name}.{uuid.uuid4().hex}.part"
        try:
            part.write_text(content, encoding="utf-8")
            part.replace(folder / name)
        finally:
            part.unlink(missing_ok=True)


LISTENING = "listening to the voice: about a minute (MMS speech model by Meta, CC BY-NC 4.0, on this computer)"


def add_to_page(
    page: Path,
    text: str,
    offline: bool = False,
    say: Callable[[str], None] = print,
    progress: Callable[[float], None] | None = None,
) -> dict[str, Any]:
    """Place the words on a page: lyrics.json and lyrics.js, and the songbook file with the words.

    Shared by `woodshed lyrics` and the library app. The page needs its instrument tracks in the cache.
    `progress` hears how far it is, 0 to 1: listening to the voice is most of the time.
    """
    step = progress or (lambda f: None)
    cache = stems_folder(page)
    if not (cache / CACHE).exists():
        say(LISTENING)
    step(0.0)
    voice = listen(cache / "vocals.flac", cache, offline, lambda f: step(0.9 * f))
    say("placing the words on the voice and the chords on the words")
    step(0.9)
    chart = page_song(page)
    data = place(text, voice, chart)
    write(page, data)
    if (page / "exports").is_dir():  # the songbook file of the page, with the words now
        from woodshed import exports

        exports.write_chordpro(chart, page / "exports", data)
    step(1.0)
    return data


def page_song(folder: Path) -> dict[str, Any]:
    text = (folder / "index.html").read_text(encoding="utf-8")
    from woodshed.build import DATA_BLOCK

    m = DATA_BLOCK.search(text)
    if not m:
        raise LyricsError(f"{folder}: not a woodshed page")
    song: dict[str, Any] = json.loads(m.group(1))["song"]
    return song


def stems_folder(page: Path) -> Path:
    """The cached stems of the recording a page was built from."""
    from woodshed import stems
    from woodshed.cache import cache_dir
    from woodshed.run import MANIFEST

    try:
        manifest = json.loads((page / MANIFEST).read_text(encoding="utf-8"))
        source = manifest["settings"]["source"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise LyricsError(f"{page}: no manifest; rebuild the page first") from exc
    folder = cache_dir() / "stems" / f"{stems.MODEL}-{source}"
    if not (folder / "vocals.flac").is_file():
        raise LyricsError(f"{page}: the instrument tracks of this song are not in the cache; build it with stems")
    return folder
