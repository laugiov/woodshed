"""Beat tracking."""

from __future__ import annotations

import tempfile
from pathlib import Path

import librosa
import numpy as np
import numpy.typing as npt

from woodshed.audio import SR

HOP = 512
Floats = npt.NDArray[np.float64]


class BeatError(Exception):
    """Too few beats to analyse the song."""


def track_librosa(y: npt.NDArray[np.float32]) -> tuple[float, Floats]:
    """librosa's tracker, with the beats it missed before the first detection added back."""
    tempo, frames = librosa.beat.beat_track(y=y, sr=SR, hop_length=HOP)
    if len(frames) < 4:
        raise BeatError("too few beats were detected in this recording")
    times = librosa.frames_to_time(frames, sr=SR, hop_length=HOP)
    period = float(np.median(np.diff(times)))
    first = float(times[0])
    back = []
    while first - period >= -0.3 * period:
        first -= period
        back.append(max(first, 0.0))
    return float(np.atleast_1d(tempo)[0]), np.concatenate([back[::-1], times]).astype(np.float64)


class MissingExtra(Exception):
    """An optional feature needs the stems extra."""


def tempo_octave_parity(labels: list[str], tempo: float) -> int | None:
    """Beat parity to keep when the tracker doubled the tempo, or None to keep every beat.

    A fast tempo where chord changes almost never fall on one of the two parities means the
    tracker counted eighth notes: the real beats are the other parity.
    """
    changes = [i for i in range(1, len(labels)) if labels[i] != labels[i - 1] and "N" not in (labels[i], labels[i - 1])]
    if tempo < 125 or len(changes) < 8:
        return None
    even = sum(1 for i in changes if i % 2 == 0) / len(changes)
    if max(even, 1 - even) < 0.8:
        return None
    return 0 if even >= 0.5 else 1


def halve(times: Floats, labels: list[str], parity: int) -> tuple[Floats, list[str], list[int]]:
    """Keep every other beat, starting at `parity`. Returns times, labels and kept indices."""
    keep = list(range(parity, len(labels), 2))
    return np.asarray(times)[keep], [labels[i] for i in keep], keep


def phase_from_downbeats(grid: Floats, downbeats: Floats, per_bar: int = 4) -> tuple[int, float]:
    """Beat-index residue holding the most detected downbeats, and its share.

    Trackers sometimes add downbeats on beat 3 when chords change every two beats; the true
    downbeats are still the majority residue.
    """
    idx = [int(np.argmin(np.abs(grid - d))) for d in downbeats]
    counts = np.bincount([i % per_bar for i in idx], minlength=per_bar)
    return int(np.argmax(counts)), float(np.max(counts)) / max(1, int(np.sum(counts)))


def pick_phase(labels: list[str], strength: Floats, per_bar: int = 4) -> int:
    """Bar phase from the labels: most chord changes on beat one, ties broken by the stronger accent."""
    counts = np.zeros(per_bar)
    for i in range(1, len(labels)):
        if labels[i] != labels[i - 1] and "N" not in (labels[i], labels[i - 1]):
            counts[i % per_bar] += 1
    top = float(np.max(counts))
    candidates = [p for p in range(per_bar) if counts[p] >= 0.9 * top]
    accents = [float(np.mean(strength[p::per_bar])) for p in range(per_bar)]
    return max(candidates, key=lambda p: accents[p])


def beat_this_available() -> bool:
    try:
        import beat_this.inference  # noqa: F401
    except ImportError:
        return False
    return True


def track_beat_this(path: Path) -> tuple[Floats, Floats]:
    """Beats and downbeats from beat_this (stems extra). The audio is re-encoded to a clean WAV
    first: its own loader rejects some valid files."""
    try:
        from beat_this.inference import File2Beats
    except ImportError as exc:
        raise MissingExtra('beat tracking with beat_this needs: pipx install "woodshed[stems]"') from exc
    import soundfile as sf

    from woodshed import audio

    y = audio.load(path, sr=44100)
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "beats.wav"
        sf.write(wav, y, 44100, subtype="PCM_16")
        found_beats, found_downbeats = File2Beats(checkpoint_path="final0", device="cpu", dbn=False)(str(wav))
    return np.asarray(found_beats, dtype=np.float64), np.asarray(found_downbeats, dtype=np.float64)
