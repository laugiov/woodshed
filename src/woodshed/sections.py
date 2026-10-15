"""Song sections (intro, verse, chorus...) from the chart's lines, their energy and the voice.

A band talks in sections: "from the second chorus". The chart is made of lines of four bars; a
section is a run of whole lines. The names are a guess, made from what can be measured:

- lines that play the same chords in the same order are one family; a run of one family, or of
  two families taking turns (an eight-bar verse made of two lines), is one block;
- a line heard only once, close to a neighbour in chords and loudness, joins that neighbour;
- blocks that sound alike get the same letter; among the letters heard more than once, the
  loudest is the chorus, the first heard is the verse, one always heard right before the chorus
  is the pre-chorus; a part heard once is the intro (first), the outro (last) or, when it is the
  only one, a bridge.

A guess from what is measured: when nothing comes back, the parts are only lettered.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from woodshed.model import Section

LINE_BARS = 4
FAMILY = 0.6  # chords in order alike: lines of one family
JOIN_CHORDS = 0.35  # a lone line joins a neighbour only if its chords are at least this alike...
JOIN_DB = 6.0  # ...and its loudness this close
LOUDER_DB = 1.5  # the chorus is the loudest repeated part when it stands out by this much
TURNS_DB = 3.0  # two lines taking turns are one part only at about the same loudness
LOOP_SHARE = 0.8  # a family this much of the song is the song's one loop: its loud and soft runs differ
STEP_DB = 4.0  # within a run of one family, a jump this loud starts a new part (quiet verse, loud chorus)
QUIET_START_DB = 4.0  # a first or last line this much quieter than its block is an intro or outro
VOICE = 0.25  # share of beats with a voice above which a line is sung

ROLE_NAMES = {
    "intro": "Intro",
    "verse": "Verse",
    "prechorus": "Pre-chorus",
    "chorus": "Chorus",
    "bridge": "Bridge",
    "instrumental": "Instrumental",
    "outro": "Outro",
}

BarChords = dict[tuple[int, str], int]  # (pc, quality) -> beats, in one bar


@dataclass(frozen=True)
class Line:
    bars: list[BarChords]
    energy_db: float
    sung: float | None  # share of beats with a voice; None without the vocal track


def _overlap(a: BarChords, b: BarChords) -> float:
    keys = a.keys() | b.keys()
    if not keys:
        return 1.0  # two silent bars
    return sum(min(a.get(k, 0), b.get(k, 0)) for k in keys) / sum(max(a.get(k, 0), b.get(k, 0)) for k in keys)


def similarity(x: Line, y: Line) -> float:
    """Chords in the same order, bar by bar (a shorter line is compared with the start of the other)."""
    n = min(len(x.bars), len(y.bars))
    return float(np.mean([_overlap(a, b) for a, b in zip(x.bars, y.bars, strict=False)])) if n else 0.0


def families(lines: Sequence[Line]) -> list[int]:
    """Each line joins the first family whose first line it resembles, or starts a new one."""
    heads: list[int] = []
    out = []
    for i, line in enumerate(lines):
        scores = [similarity(line, lines[h]) for h in heads]
        best = int(np.argmax(scores)) if scores else -1
        if best >= 0 and scores[best] >= FAMILY:
            out.append(best)
        else:
            heads.append(i)
            out.append(len(heads) - 1)
    return out


def _blocks(fam: Sequence[int], lines: Sequence[Line]) -> list[list[int]]:
    """[start, end) blocks of lines:

    - a run of one family, cut where the loudness jumps (a song on one chord loop, quiet verses,
      loud choruses);
    - two families taking turns over four lines or more at about the same loudness: one block
      (two lines making one eight-bar verse, not a verse and a chorus);
    - three different lines at about the same loudness coming back in the same order at least
      twice: one block per round (a 12-bar blues is three lines a round; a one-line verse,
      pre-chorus and chorus are not, they climb in loudness).
    """
    n, out, i = len(fam), [], 0
    loud = [line.energy_db for line in lines]
    while i < n:
        level = max(loud[i : i + 3], default=0.0) - min(loud[i : i + 3], default=0.0) <= TURNS_DB
        if i + 6 <= n and level and len(set(fam[i : i + 3])) == 3 and fam[i : i + 3] == fam[i + 3 : i + 6]:
            k = i + 3
            while k + 3 <= n and fam[k : k + 3] == fam[i : i + 3]:
                out.append([k - 3, k])
                k += 3
            out.append([k - 3, k])
            i = k
            continue
        j = i + 1
        while j < n and fam[j] == fam[i] and abs(loud[j] - loud[j - 1]) < STEP_DB:
            j += 1
        if j - i == 1 and j < n and fam[j] != fam[i]:
            k = i + 2
            while k < n and fam[k] == fam[i + (k - i) % 2]:
                k += 1
            even = [loud[x] for x in range(i, k, 2)]
            odd = [loud[x] for x in range(i + 1, k, 2)]
            if k - i >= 4 and abs(float(np.mean(even)) - float(np.mean(odd))) <= TURNS_DB:
                j = k
        out.append([i, j])
        i = j
    return out


def _join_lone_lines(blocks: list[list[int]], lines: Sequence[Line], fam: Sequence[int]) -> list[list[int]]:
    heard = Counter(fam)
    blocks = [b[:] for b in blocks]
    changed = True
    while changed and len(blocks) > 1:
        changed = False
        for k, (a, b) in enumerate(blocks):
            if b - a != 1 or heard[fam[a]] > 1:
                continue
            best: tuple[float, int] | None = None
            for n in (k - 1, k + 1):
                if not 0 <= n < len(blocks):
                    continue
                other = range(*blocks[n])
                chords = max(similarity(lines[a], lines[i]) for i in other)
                gap = abs(lines[a].energy_db - float(np.mean([lines[i].energy_db for i in other])))
                if chords >= JOIN_CHORDS and gap <= JOIN_DB and (best is None or gap - 4 * chords < best[0]):
                    best = (gap - 4 * chords, n)
            if best is not None:
                n = best[1]
                blocks[n] = [min(blocks[n][0], a), max(blocks[n][1], b)]
                del blocks[k]
                changed = True
                break
    return blocks


def _split_ends(blocks: list[list[int]], lines: Sequence[Line]) -> tuple[list[list[int]], dict[int, str]]:
    """A first (last) line quieter than the rest of its block, or not sung when the rest is, is an
    intro (outro) of its own, whatever its chords: returned with the roles it forces."""

    def apart(i: int, rest: range) -> bool:
        quiet = lines[i].energy_db < float(np.mean([lines[r].energy_db for r in rest])) - QUIET_START_DB
        sung = [lines[r].sung for r in rest]
        own = lines[i].sung
        unsung = own is not None and own < VOICE and all(s is not None and s >= VOICE for s in sung)
        return quiet or unsung

    forced: dict[int, str] = {}
    if blocks and blocks[0][1] - blocks[0][0] > 1 and apart(blocks[0][0], range(blocks[0][0] + 1, blocks[0][1])):
        a, b = blocks[0]
        blocks[0:1] = [[a, a + 1], [a + 1, b]]
        forced[0] = "intro"
    if blocks and blocks[-1][1] - blocks[-1][0] > 1 and apart(blocks[-1][1] - 1, range(*blocks[-1])[:-1]):
        a, b = blocks[-1]
        blocks[-1:] = [[a, b - 1], [b - 1, b]]
        forced[len(blocks) - 1] = "outro"
    return blocks, forced


def _letters(blocks: Sequence[list[int]], fam: Sequence[int], lines: Sequence[Line]) -> list[int]:
    """Blocks of the same music share a letter: the same main family of lines (not "alike line by
    line": a chorus can share half its bars with a line of the verse, as in many ballads), and, for
    a family heard both soft and loud (one chord loop for the whole song), the same loudness."""
    main = [Counter(fam[a:b]).most_common(1)[0][0] for a, b in blocks]
    loud = [float(np.mean([lines[i].energy_db for i in range(a, b)])) for a, b in blocks]
    level = [0] * len(blocks)
    total = sum(b - a for a, b in blocks)
    for f in set(main):
        mine = [k for k in range(len(blocks)) if main[k] == f]
        if sum(blocks[k][1] - blocks[k][0] for k in mine) < LOOP_SHARE * total:
            continue  # only a loop that carries most of the song is split by loudness
        low, high = min(loud[k] for k in mine), max(loud[k] for k in mine)
        if high - low >= STEP_DB:
            for k in mine:
                level[k] = int(loud[k] >= (low + high) / 2)
    keys = list(zip(main, level, strict=True))
    out: list[int] = []
    for k in range(len(blocks)):
        found = next((out[j] for j in range(k) if keys[j] == keys[k]), -1)
        out.append(found if found >= 0 else max(out, default=-1) + 1)
    return out


def _roles(blocks: Sequence[list[int]], letters: Sequence[int], lines: Sequence[Line]) -> tuple[list[str], set[int]]:
    """A role per block, and the blocks found to be verses only from where they stand (before a
    pre-chorus): consecutive ones are one verse.

    A part heard only at both ends (an intro riff played again as the outro) does not count as
    coming back: it is not a verse heard twice."""
    n = len(blocks)
    loud = [float(np.mean([lines[i].energy_db for i in range(a, b)])) for a, b in blocks]
    sung = [[lines[i].sung for i in range(a, b)] for a, b in blocks]
    count = Counter(letters)
    ends_only = {x for x in count if n >= 3 and all(k in (0, n - 1) for k in range(n) if letters[k] == x)}
    repeated = [
        x for x in dict.fromkeys(letters) if count[x] > 1 and x not in ends_only
    ]  # in order of first appearance
    roles = ["part"] * n
    if not repeated:  # nothing comes back: no verse or chorus to stand on, letters only
        return roles, set()

    def unsung(k: int) -> bool:
        return all(v is not None and v < VOICE for v in sung[k])

    energy = {x: float(np.mean([loud[k] for k in range(n) if letters[k] == x])) for x in repeated}
    top = max(repeated, key=lambda x: energy[x])
    others = [energy[x] for x in repeated if x != top]
    chorus = None
    if not others or energy[top] - max(others) >= LOUDER_DB:
        chorus = top
    elif len(repeated) > 1:
        chorus = repeated[1]  # no part stands out: the song starts with a verse
    verse = next((x for x in repeated if x != chorus), None)

    pre = None
    for x in repeated:
        if x == chorus or chorus is None:
            continue
        if not all(k + 1 < n and letters[k + 1] == chorus for k in range(n - 1) if letters[k] == x):
            continue
        # The first repeated part is the verse, unless parts heard once come before it each time:
        # then it is the pre-chorus and those parts are the verses.
        led = all(k > 0 and letters[k - 1] not in repeated for k in range(n - 1) if letters[k] == x)
        if x != verse or led:
            pre = x
            if x == verse:
                verse = next((y for y in repeated if y not in (chorus, x)), None)
            break
    named = {chorus: "chorus", verse: "verse", pre: "prechorus"}
    named.pop(None, None)
    for k in range(n):
        roles[k] = named.get(letters[k], "part")

    # The ends: the intro and the outro, unless they are sung parts of the song itself. A last
    # chorus stays a chorus; a short last line on the verse chords is the outro.
    if n >= 3:
        first, last = 0, n - 1
        role = named.get(letters[first])
        # A soft start on the chords that follow, before the band comes in.
        quiet = letters[first] == letters[first + 1] and loud[first] < loud[first + 1] - QUIET_START_DB
        roles[first] = role if role and not unsung(first) and not quiet else "intro"
        role = named.get(letters[last])
        short = blocks[last][1] - blocks[last][0] == 1
        keep = role == "chorus" or (role is not None and not short)
        quiet = letters[last] == letters[last - 1] and loud[last] < loud[last - 1] - QUIET_START_DB
        roles[last] = role if role and keep and not unsung(last) and not quiet else "outro"

    inferred: set[int] = set()
    if pre is not None and verse is None:
        for k in range(n):
            if letters[k] != pre or roles[k] != "prechorus":
                continue
            j = k - 1
            while j > 0 and roles[j] == "part":
                roles[j] = "verse"
                inferred.add(j)
                j -= 1

    # One part heard once in the middle is a bridge; several are more likely misheard lines.
    lone = [k for k in range(1, n - 1) if count[letters[k]] == 1 and roles[k] == "part"]
    if len(lone) == 1:
        roles[lone[0]] = "instrumental" if unsung(lone[0]) else "bridge"
    return roles, inferred


def _letter(n: int) -> str:
    return chr(ord("A") + n) if n < 26 else "Z" + str(n - 25)


def name_sections(roles: Sequence[str], letters: Sequence[int]) -> list[str]:
    """Verse 1, Verse 2, Chorus 1...; a part heard once has no number; unknown parts are lettered."""
    total = Counter(roles)
    seen: Counter[str] = Counter()
    out = []
    for role, letter in zip(roles, letters, strict=True):
        if role == "part":
            out.append(f"Part {_letter(letter)}")
            continue
        seen[role] += 1
        base = ROLE_NAMES[role]
        numbered = total[role] > 1 and role not in ("intro", "outro")
        out.append(f"{base} {seen[role]}" if numbered else base)
    return out


def find(lines: Sequence[Line]) -> list[tuple[int, int, str, str, str]]:
    """(first line, line after the last, name, role, letter) of each section."""
    if not lines:
        return []
    # A soft recording can keep its whole vocal track under the singing floor: no sung line at all
    # says nothing about the song, the voice is then unknown rather than absent.
    if all(line.sung is not None and line.sung < VOICE for line in lines):
        lines = [Line(line.bars, line.energy_db, None) for line in lines]
    fam = families(lines)
    blocks, forced = _split_ends(_join_lone_lines(_blocks(fam, lines), lines, fam), lines)
    letters = _letters(blocks, fam, lines)
    roles, inferred = _roles(blocks, letters, lines)
    for k, role in forced.items():
        roles[k] = role
    for k in range(len(blocks) - 1, 0, -1):  # verses found from where they stand: one block each
        if k in inferred and k - 1 in inferred:
            blocks[k - 1][1] = blocks[k][1]
            del blocks[k], letters[k], roles[k]
    names = name_sections(roles, letters)
    return [(a, b, nm, r, _letter(x)) for (a, b), nm, r, x in zip(blocks, names, roles, letters, strict=True)]


def lines_of(
    bar_chords: Sequence[Sequence[tuple[int, str, int]]],
    bar_times: Sequence[tuple[float, float]],
    beat_times: npt.NDArray[np.float64],
    energy_db: npt.NDArray[np.float64] | None,
    vocal: npt.NDArray[np.float64] | None,
) -> list[Line]:
    """The chart's lines with what sections are made from: chords per bar (pc, quality, beats),
    loudness (mean of the beats' energy) and the share of sung beats."""
    out = []
    for start in range(0, len(bar_chords), LINE_BARS):
        idx = range(start, min(start + LINE_BARS, len(bar_chords)))
        bars: list[BarChords] = []
        for i in idx:
            counts: BarChords = {}
            for pc, quality, beats in bar_chords[i]:
                if pc >= 0:
                    counts[(pc, quality)] = counts.get((pc, quality), 0) + beats
            bars.append(counts)
        t0, t1 = bar_times[idx[0]][0], bar_times[idx[-1]][1]
        inside = (beat_times >= t0) & (beat_times < t1)
        loud = float(np.mean(energy_db[inside])) if energy_db is not None and inside.any() else 0.0
        sung = float(np.mean(vocal[inside])) if vocal is not None and inside.any() else None
        out.append(Line(bars, loud, sung))
    return out


def sections(
    bar_chords: Sequence[Sequence[tuple[int, str, int]]],
    bar_times: Sequence[tuple[float, float]],
    beat_times: npt.NDArray[np.float64],
    energy_db: npt.NDArray[np.float64] | None = None,
    vocal: npt.NDArray[np.float64] | None = None,
) -> list[Section]:
    lines = lines_of(bar_chords, bar_times, beat_times, energy_db, vocal)
    n_bars = len(bar_chords)
    return [
        Section(name, role, letter, a * LINE_BARS, min(b * LINE_BARS, n_bars))
        for a, b, name, role, letter in find(lines)
    ]
