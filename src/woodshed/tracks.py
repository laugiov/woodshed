"""The audio tracks of a page: the full mix and, with stems, the mix without each instrument and
each instrument alone. The page plays one track at a time, so tracks never drift apart.

Lossless 24-bit FLAC at 44.1 kHz. One common gain keeps every track below full scale, so switching
tracks never changes the level. Tracks are written block by block: nine 4-minute stereo tracks
would not fit comfortably in memory at once.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import numpy as np
import numpy.typing as npt
import soundfile as sf

from woodshed import audio
from woodshed.parts import heard, window_rms
from woodshed.stems import CEILING, FOUR, RATE, Model, Stems
from woodshed.view import Track

BLOCK = RATE * 10  # samples per block
LABELS = {
    "drums": "drums",
    "bass": "bass",
    "other": "guitars and keys",
    "vocals": "vocals",
    "guitar": "guitar",
    "keys": "keys",
}
# A six-stem page's keys: Demucs's piano and what lands in no other stem (synths, organ, strings, brass); its
# piano alone is weak (spec 010).
KEYS = ("piano", "other")
Stereo = npt.NDArray[np.float32]  # (2, n)


def instruments(model: Model) -> tuple[str, ...]:
    """The instruments a page has a track for, alone and left out, with this separation."""
    return FOUR.stems if model is FOUR else ("drums", "bass", "vocals", "guitar", "keys")


def track_list(names: Sequence[str] | bool) -> list[Track]:
    """The page's tracks: the mix, then each instrument left out and alone. `True`: the four-stem list."""
    names = FOUR.stems if names is True else () if names is False else tuple(names)
    tracks = [Track("mix", "Full mix", "audio/mix.flac")]
    tracks += [Track(f"minus-{s}", f"Without {LABELS[s]}", f"audio/minus-{s}.flac") for s in names]
    tracks += [Track(f"solo-{s}", f"{LABELS[s].capitalize()} alone", f"audio/solo-{s}.flac") for s in names]
    return tracks


def _stem_block(handle: sf.SoundFile, start: int, length: int, gain: float) -> Stereo:
    handle.seek(start)
    block = handle.read(length, dtype="float32", always_2d=True).T / gain  # undo the stems' storage gain
    if block.shape[1] < length:  # stems can be a few samples shorter than the mix
        block = np.pad(block, ((0, 0), (0, length - block.shape[1])))
    return np.asarray(block[:2], dtype=np.float32)


def write_tracks(source: Path, stems: Stems | None, folder: Path) -> list[Track]:
    """Write every track into `folder/audio/`, and return the list the page offers. On a six-stem page a guitar
    or keys that is not heard gets no track (the page says so)."""
    out = folder / "audio"
    out.mkdir(parents=True, exist_ok=True)
    mix = audio.load(source, sr=RATE, channels=2)
    n = mix.shape[1]
    handles = {} if stems is None else {name: sf.SoundFile(stems.paths[name]) for name in stems.paths}
    try:
        stem_gain = 1.0 if stems is None else stems.gain

        def part(name: str, start: int, length: int) -> Stereo:
            if name == "keys":
                return sum(
                    (_stem_block(handles[k], start, length, stem_gain) for k in KEYS), np.zeros((2, length), np.float32)
                )
            return _stem_block(handles[name], start, length, stem_gain)

        def block_of(track: str, start: int) -> Stereo:
            length = min(BLOCK, n - start)
            if track == "mix":
                return mix[:, start : start + length]
            kind, name = track.split("-", 1)
            stem = part(name, start, length)
            return stem if kind == "solo" else mix[:, start : start + length] - stem

        names = instruments(stems.model) if stems is not None else ()
        if stems is not None and stems.model is not FOUR:
            # Heard or not, judged at the original level on what each instrument plays (parts.heard).
            levels = {
                name: np.concatenate([window_rms(part(name, s, min(BLOCK, n - s)), RATE) for s in range(0, n, BLOCK)])
                for name in names
            }
            loudest = max(float(np.sqrt(np.mean(w**2))) if w.size else 0.0 for w in levels.values())
            names = tuple(name for name in names if name not in ("guitar", "keys") or heard(levels[name], loudest))
        tracks = track_list(names)
        peak = max(
            float(np.max(np.abs(block_of(t.id, start)), initial=0.0)) for t in tracks for start in range(0, n, BLOCK)
        )
        gain = 1.0 if peak <= CEILING else CEILING / peak
        for t in tracks:
            with sf.SoundFile(folder / t.file, "w", RATE, 2, subtype="PCM_24", format="FLAC") as f:
                for start in range(0, n, BLOCK):
                    f.write((block_of(t.id, start) * gain).T)
    finally:
        for h in handles.values():
            h.close()
    return tracks
