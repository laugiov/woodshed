"""The text chart (`woodshed chart`): a timeline and a bar grid, as the original chords.py printed."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from woodshed.engine import Decoded, detect

TOO_DOUBTFUL = 0.25  # above this share of doubtful beats, the chart says not to trust it


@dataclass(frozen=True)
class Chart:
    text: str
    data: dict[str, Any]


def fmt_time(t: float) -> str:
    return f"{int(t // 60)}:{t % 60:05.2f}"


def _beats(res: Decoded) -> list[dict[str, Any]]:
    return [
        {"time": round(float(t), 3), "chord": label, "energy_db": round(float(db), 1), "doubtful": bool(doubt)}
        for t, label, db, doubt in zip(res.beat_times, res.labels, res.energy_db, res.doubtful, strict=True)
    ]


def segments_of(beats: list[dict[str, Any]], period: float) -> list[dict[str, Any]]:
    """Consecutive beats holding the same chord, as one segment."""
    groups: list[list[dict[str, Any]]] = []
    for b in beats:
        if groups and groups[-1][0]["chord"] == b["chord"]:
            groups[-1].append(b)
        else:
            groups.append([b])
    out = []
    for i, group in enumerate(groups):
        start = group[0]["time"]
        end = groups[i + 1][0]["time"] if i + 1 < len(groups) else start + period * len(group)
        n = len(group)
        doubtful = sum(b["doubtful"] for b in group) * 2 >= n
        chord = group[0]["chord"]
        out.append({"start": round(start, 3), "end": round(end, 3), "chord": chord, "beats": n, "doubtful": doubtful})
    return out


def bars_of(beats: list[dict[str, Any]], per_bar: int, offset: int) -> list[list[dict[str, Any] | None]]:
    """Bars of `per_bar` beats; the beats before the song starts are empty (None)."""
    seq: list[dict[str, Any] | None] = [None] * offset + list(beats)
    return [seq[i : i + per_bar] for i in range(0, len(seq), per_bar)]


def _doubtful_ratio(beats: list[dict[str, Any]]) -> float:
    voiced = [b for b in beats if b["chord"] != "N"]
    return float(sum(b["doubtful"] for b in voiced)) / max(len(voiced), 1)


def _grid_lines(beats: list[dict[str, Any]], per_bar: int, offset: int, auto: bool) -> list[str]:
    lines = ["", f"== Grid ({per_bar} beats per bar, offset {offset} {'auto' if auto else 'manual'}) =="]
    cells = []
    for bar in bars_of(beats, per_bar, offset):
        parts: list[str] = []
        prev = None
        for b in bar:
            if b is None:
                parts.append("-")
                continue
            parts.append(b["chord"] + ("?" if b["doubtful"] else "") if b["chord"] != prev else ".")
            prev = b["chord"]
        cells.append(parts)
    width = max(3, max((len(p) for c in cells for p in c), default=0))
    joined = [" ".join(f"{p:<{width}}" for p in c) for c in cells]
    lines += ["| " + " | ".join(joined[i : i + 4]) + " |" for i in range(0, len(joined), 4)]
    return lines


def chart(path: str | Path, sevenths: bool = False, beats_per_bar: int = 4, offset: int | None = None) -> Chart:
    res = detect(path, sevenths, beats_per_bar)
    used = res.offset if offset is None else offset
    beats = _beats(res)
    period = float(np.median(np.diff(res.beat_times)))
    segments = segments_of(beats, period)
    lines = [f"Tempo: {res.tempo:.0f} BPM | key: {res.key_name} | tuning offset: {res.tuning:+.2f} semitone"]
    lines += ["", "== Timeline =="]
    for sg in segments:
        note = "  (silence)" if sg["chord"] == "N" else "  ?" if sg["doubtful"] else ""
        lines.append(f"{fmt_time(sg['start'])}  {sg['chord']}{note}")
    lines += _grid_lines(beats, beats_per_bar, used, offset is None)
    voiced = [b for b in beats if b["chord"] != "N"]
    doubtful = sum(b["doubtful"] for b in voiced)
    ratio = _doubtful_ratio(beats)
    lines += ["", f'Doubtful beats: {doubtful}/{len(voiced)} ({ratio:.0%}), marked "?"']
    if ratio > TOO_DOUBTFUL:
        lines.append("WARNING: more than a quarter of the beats are doubtful, do not take this chart as it is.")
    data = {
        "file": os.path.basename(path),
        "tempo_bpm": round(res.tempo, 1),
        "tuning_semitones": round(res.tuning, 3),
        "key": res.key_name,
        "sevenths": sevenths,
        "beats_per_bar": beats_per_bar,
        "offset": used,
        "offset_auto": offset is None,
        "doubtful_ratio": round(ratio, 3),
        "segments": segments,
        "bars": [[b["chord"] if b else None for b in bar] for bar in bars_of(beats, beats_per_bar, used)],
        "beats": beats,
    }
    return Chart("\n".join(lines) + "\n", data)
