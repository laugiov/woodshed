"""Display tables for the page, computed by the theory module so that the page holds no theory.

For each of the 12 transpositions: the key name, the suggested capo, and the spelling of every
chord root. Roman numerals do not change with transposition. The page only looks names up.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cache
from importlib import resources
from typing import Any

from woodshed import theory
from woodshed.model import KeyRegion, Song

VIEW_VERSION = 2  # 2: a table per key region
QUALITIES = ("", "m", "7", "m7")


@dataclass(frozen=True)
class Track:
    id: str  # "mix", "minus-drums", "solo-bass"...
    label: str
    file: str  # path inside the page folder, with forward slashes


def _key_name(key: theory.Key) -> str:
    return theory.spell(key.tonic, key) + ("" if key.mode == "maj" else "m")


def view_region(region: KeyRegion) -> dict[str, Any]:
    keys = [theory.Key((region.key.tonic + t) % 12, region.key.mode) for t in range(12)]
    return {
        "bar": region.bar,
        "transpositions": [
            {"key": _key_name(k), "roots": [theory.spell_root((pc + t) % 12, k) for pc in range(12)]}
            for t, k in enumerate(keys)
        ],
        "romans": {q: [theory.roman(pc, q, region.key) for pc in range(12)] for q in QUALITIES},
    }


def _timed(song: Song) -> list[theory.TimedChord]:
    return [theory.TimedChord(c.pc, c.quality, c.beats) for bar in song.structure.bars for c in bar.chords if c.pc >= 0]


def view(
    song: Song, tracks: list[Track], pending_seconds: float | None = None, exports: list[str] | None = None
) -> dict[str, Any]:
    """The `view` block embedded next to the song: everything the page displays but does not compute."""
    timed = _timed(song)
    transpositions = []
    for t in range(12):
        key = theory.Key((song.key.tonic + t) % 12, song.key.mode)
        transpositions.append(
            {
                "key": _key_name(key),
                # Root names indexed by the pitch class found in the recording, spelled in the new key.
                "roots": [theory.spell_root((pc + t) % 12, key) for pc in range(12)],
                "capo": theory.suggest_capo(timed, t),
            }
        )
    return {
        "view_version": VIEW_VERSION,
        "transpositions": transpositions,
        # The song's key (the longest region): kept for the capo; names and numerals come from `regions`, whose
        # first is the key the song starts in (what the page shows as its key).
        "romans": {q: [theory.roman(pc, q, song.key) for pc in range(12)] for q in QUALITIES},
        # From each region's first bar: its key name and root spellings per transposition, and its numerals
        # (a Gb after a lift to Db, not F#; I V vi IV on both sides of the lift). Spec 012.
        "regions": [view_region(r) for r in (song.key_regions or [KeyRegion(0, song.key)])],
        "shapes": theory.SHAPES,
        "tracks": [{"id": t.id, "label": t.label, "file": t.file} for t in tracks],
        # While the stems are being separated, the page says when to reload.
        "pending": None if pending_seconds is None else {"eta_seconds": max(1, round(pending_seconds))},
        "exports": exports or [],  # files in the page folder, as written by the analysis
    }


@cache
def schema() -> dict[str, Any]:
    text = resources.files("woodshed").joinpath("view.schema.json").read_text(encoding="utf-8")
    result: dict[str, Any] = json.loads(text)
    return result
