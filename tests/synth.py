"""Deterministic synthetic songs with exact ground truth: chords, beats, downbeats and stems.

Every engine test runs on these, so they stay short and cheap to render. The instruments are plain
additive synthesis: the goal is a known answer, not a nice sound.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

import numpy as np
import soundfile as sf

SR = 22050
NOTES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
FLATS = {"Db": "C#", "Eb": "D#", "Gb": "F#", "Ab": "G#", "Bb": "A#"}
QUALITIES = {"": (0, 4, 7), "m": (0, 3, 7), "7": (0, 4, 7, 10), "m7": (0, 3, 7, 10), "maj7": (0, 4, 7, 11)}


@dataclass(frozen=True)
class Spec:
    bpm: float
    beats_per_bar: int
    chords: tuple[tuple[str, int], ...]  # (label, beats)
    lead_in: float = 1.0  # seconds of silence before the first beat
    tail: float = 1.0
    bass: str = "root"  # "root" on every beat, or "riff" (root plus the half step below)
    hats: str = "eighths"  # "eighths" or "offbeat16" (funk)
    melody: bool = False


@dataclass
class Song:
    name: str
    mix: np.ndarray
    stems: dict[str, np.ndarray]
    chords: list[tuple[float, float, str]]
    beats: np.ndarray
    downbeats: np.ndarray
    key: str
    spec: Spec = field(repr=False)


@dataclass(frozen=True)
class Written:
    wav: Path
    lab: Path


def _loop(seq: list[tuple[str, int]], times: int) -> tuple[tuple[str, int], ...]:
    return tuple(seq * times)


SONGS: dict[str, Spec] = {
    # Four chords, one per bar, twice.
    "pop": Spec(120, 4, _loop([("C", 4), ("G", 4), ("Am", 4), ("F", 4)], 2)),
    # Two chords per bar at a slow tempo: the classic trap for beat trackers and bar phase.
    "ballad": Spec(
        72, 4, _loop([("C", 2), ("G", 2), ("Am", 2), ("F", 2), ("C", 2), ("G", 2), ("F", 2), ("C", 2)], 2), melody=True
    ),
    # Three beats per bar.
    "waltz": Spec(132, 3, _loop([("D", 3), ("A", 3), ("Bm", 3), ("G", 3)], 3)),
    # Chromatic funk bass, loud melody, off-beat sixteenth hats: the funk cover's difficulties.
    "funk": Spec(
        99,
        4,
        (("Ab", 8), ("Fm", 8), ("Db", 8), ("Bbm", 4), ("Eb", 4)),
        lead_in=1.5,
        bass="riff",
        hats="offbeat16",
        melody=True,
    ),
}
KEYS = {"pop": "C", "ballad": "C", "waltz": "D", "funk": "Ab"}


def parse(label: str) -> tuple[int, tuple[int, ...]]:
    root = label[:2] if len(label) > 1 and label[1] in "#b" else label[:1]
    pc = NOTES.index(FLATS.get(root, root))
    return pc, QUALITIES[label[len(root) :]]


def _hz(midi: float) -> float:
    return 440.0 * 2 ** ((midi - 69) / 12)


def _tone(freq: float, dur: float, amp: float, rng: np.random.Generator, decay: float = 2.5) -> np.ndarray:
    t = np.arange(int(dur * SR)) / SR
    # 10 ms attack, 15 ms release: a hard cut would click, and the click reads as a note onset.
    env = np.exp(-decay * t) * np.minimum(1.0, t / 0.01) * np.minimum(1.0, (dur - t) / 0.015)
    partials = sum((0.6**k) * np.sin(2 * np.pi * freq * (k + 1) * t + rng.uniform(0, 6.28)) for k in range(6))
    return np.asarray(amp * env * partials)


def _noise(dur: float, amp: float, rng: np.random.Generator, decay: float, highpass: bool) -> np.ndarray:
    n = rng.standard_normal(int(dur * SR))
    if highpass:
        n = np.diff(n, prepend=0.0)
    t = np.arange(n.size) / SR
    return np.asarray(amp * np.exp(-decay * t) * n)


def _kick(amp: float) -> np.ndarray:
    t = np.arange(int(0.3 * SR)) / SR
    freq = 120 * np.exp(-30 * t) + 45
    return np.asarray(amp * np.exp(-12 * t) * np.sin(2 * np.pi * np.cumsum(freq) / SR))


def _add(track: np.ndarray, sig: np.ndarray, at: float) -> None:
    i = round(at * SR)
    j = min(track.size, i + sig.size)
    if i < track.size:
        track[i:j] += sig[: j - i]


@cache
def _render_cached(name: str) -> Song:
    spec = SONGS[name]
    rng = np.random.default_rng(sum(map(ord, name)))
    beat = 60.0 / spec.bpm
    n_beats = sum(b for _, b in spec.chords)
    total = spec.lead_in + n_beats * beat + spec.tail
    n = round(total * SR)
    stems = {k: np.zeros(n) for k in ("drums", "bass", "other", "vocals")}

    spans: list[tuple[float, float, str]] = [(0.0, spec.lead_in, "N")]
    t, i = spec.lead_in, 0
    for label, beats in spec.chords:
        root, ivs = parse(label)
        spans.append((t, t + beats * beat, label))
        for b in range(beats):
            tb = t + b * beat
            pos = i % spec.beats_per_bar
            # Drums: kick on the first beat (and the middle of 4/4 bars), snare on the others' backbeats.
            if pos == 0 or (spec.beats_per_bar == 4 and pos == 2):
                _add(stems["drums"], _kick(0.8), tb)
            elif spec.beats_per_bar == 4 or pos == 1:
                _add(stems["drums"], _noise(0.18, 0.35, rng, 25, highpass=False), tb)
            if spec.hats == "eighths":
                for k in range(2):
                    _add(stems["drums"], _noise(0.06, 0.08, rng, 60, highpass=True), tb + k * beat / 2)
            else:
                for k in range(4):
                    _add(
                        stems["drums"],
                        _noise(0.05, 0.12 if k == 2 else 0.05, rng, 70, highpass=True),
                        tb + k * beat / 4,
                    )
            # Bass.
            if spec.bass == "root":
                _add(stems["bass"], _tone(_hz(36 + root), beat * 0.9, 0.3, rng, 1.5), tb)
            else:
                for k, step in enumerate((0, -1)):
                    _add(stems["bass"], _tone(_hz(36 + root + step), beat * 0.45, 0.4, rng, 4.0), tb + k * beat / 2)
            # Chords, on every beat, voiced around middle C.
            for iv in ivs:
                _add(stems["other"], _tone(_hz(60 + (root + iv) % 12), beat * 0.95, 0.1, rng), tb)
            # Melody: a chord tone or a passing note, one per beat.
            if spec.melody:
                step = int(rng.choice([0, 2, 4, 5, 7, 9]))
                _add(stems["vocals"], _tone(_hz(72 + (root + step) % 12), beat * 0.9, 0.12, rng, 1.0), tb)
            i += 1
        t += beats * beat
    spans.append((t, total, "N"))
    spans[-1] = (spans[-1][0], n / SR, "N")

    mix = sum(stems.values())
    peak = float(np.abs(mix).max()) * 1.1
    stems = {k: v / peak for k, v in stems.items()}
    mix = sum(stems.values())
    beats_t = spec.lead_in + beat * np.arange(n_beats)
    return Song(name, np.asarray(mix), stems, spans, beats_t, beats_t[:: spec.beats_per_bar], KEYS[name], spec)


def render(name: str) -> Song:
    """Render a song (cached): mix, stems and ground truth."""
    return _render_cached(name)


def write(name: str, folder: Path) -> Written:
    """Write the mix as WAV and the chords as a MIREX .lab file."""
    song = render(name)
    folder.mkdir(parents=True, exist_ok=True)
    wav, lab = folder / f"{name}.wav", folder / f"{name}.lab"
    sf.write(wav, song.mix, SR)
    lab.write_text("".join(f"{a:.4f} {b:.4f} {c}\n" for a, b, c in song.chords))
    return Written(wav, lab)
