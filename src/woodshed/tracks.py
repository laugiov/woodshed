"""The audio tracks of a page: the full mix and, with stems, the mix without each instrument and
each instrument alone. The page plays one track at a time, so tracks never drift apart.

Lossless 24-bit FLAC at 44.1 kHz. One common gain keeps every track below full scale, so switching
tracks never changes the level. Tracks are written block by block: nine 4-minute stereo tracks
would not fit comfortably in memory at once.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import numpy.typing as npt
import soundfile as sf

from woodshed import audio
from woodshed.stems import CEILING, RATE, STEM_NAMES, Stems
from woodshed.view import Track

BLOCK = RATE * 10  # samples per block
LABELS = {"drums": "drums", "bass": "bass", "other": "guitars and keys", "vocals": "vocals"}
Stereo = npt.NDArray[np.float32]  # (2, n)


def track_list(with_stems: bool) -> list[Track]:
    tracks = [Track("mix", "Full mix", "audio/mix.flac")]
    if with_stems:
        tracks += [Track(f"minus-{s}", f"Without {LABELS[s]}", f"audio/minus-{s}.flac") for s in STEM_NAMES]
        tracks += [Track(f"solo-{s}", f"{LABELS[s].capitalize()} alone", f"audio/solo-{s}.flac") for s in STEM_NAMES]
    return tracks


def _stem_block(handle: sf.SoundFile, start: int, length: int, gain: float) -> Stereo:
    handle.seek(start)
    block = handle.read(length, dtype="float32", always_2d=True).T / gain  # undo the stems' storage gain
    if block.shape[1] < length:  # stems can be a few samples shorter than the mix
        block = np.pad(block, ((0, 0), (0, length - block.shape[1])))
    return np.asarray(block[:2], dtype=np.float32)


def write_tracks(source: Path, stems: Stems | None, folder: Path) -> list[Track]:
    """Write every track into `folder/audio/`, and return the list the page offers."""
    tracks = track_list(stems is not None)
    out = folder / "audio"
    out.mkdir(parents=True, exist_ok=True)
    mix = audio.load(source, sr=RATE, channels=2)
    n = mix.shape[1]
    handles = {} if stems is None else {name: sf.SoundFile(stems.paths[name]) for name in STEM_NAMES}
    try:
        stem_gain = 1.0 if stems is None else stems.gain

        def block_of(track: str, start: int) -> Stereo:
            length = min(BLOCK, n - start)
            if track == "mix":
                return mix[:, start : start + length]
            kind, name = track.split("-", 1)
            stem = _stem_block(handles[name], start, length, stem_gain)
            return stem if kind == "solo" else mix[:, start : start + length] - stem

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
