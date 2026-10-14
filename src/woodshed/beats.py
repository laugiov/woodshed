"""Beat tracking: librosa in the core, beat_this (beats and downbeats) with the stems extra."""

from __future__ import annotations

import tempfile
from pathlib import Path

import librosa
import numpy as np
import numpy.typing as npt

from woodshed.audio import SR
from woodshed.errors import BeatError, MissingExtra, StemsError

HOP = 512
Floats = npt.NDArray[np.float64]
STEMS_HINT = 'beat tracking with beat_this needs the stems extra: pipx install "woodshed[stems]"'


def track_librosa(y: npt.NDArray[np.float32]) -> tuple[float, Floats]:
    """librosa's tracker, with the beats it missed before the first detection added back."""
    tempo, frames = librosa.beat.beat_track(y=y, sr=SR, hop_length=HOP)
    if len(frames) < 4:
        raise BeatError("too few beats were detected: is this music?")
    times = librosa.frames_to_time(frames, sr=SR, hop_length=HOP)
    period = float(np.median(np.diff(times)))
    first = float(times[0])
    back = []
    while first - period >= -0.3 * period:
        first -= period
        back.append(max(first, 0.0))
    return float(np.atleast_1d(tempo)[0]), np.concatenate([back[::-1], times]).astype(np.float64)


def beat_this_available() -> bool:
    try:
        import beat_this.inference  # noqa: F401
    except ImportError:
        return False
    return True


def track_beat_this(path: Path, offline: bool = False) -> tuple[Floats, Floats]:
    """Beats and downbeats from beat_this. The audio is re-encoded to a clean WAV first: its own
    loader rejects some valid files."""
    try:
        from beat_this.inference import File2Beats
    except ImportError as exc:
        raise MissingExtra(STEMS_HINT) from exc
    import soundfile as sf

    from woodshed import audio
    from woodshed.models import offline_cause, torch_models

    y = audio.load(path, sr=44100)
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "beats.wav"
        sf.write(wav, y, 44100, subtype="PCM_16")
        try:
            with torch_models(offline):
                found_beats, found_downbeats = File2Beats(checkpoint_path="final0", device="cpu", dbn=False)(str(wav))
        except Exception as exc:  # the library raises plain ValueError and RuntimeError
            refusal = offline_cause(exc)
            if refusal is not None:  # beat_this wraps a refused download in its own ValueError
                raise StemsError(str(refusal)) from exc
            raise StemsError(f"beat tracking with beat_this failed: {exc}") from exc
    beats, downbeats = np.asarray(found_beats, dtype=np.float64), np.asarray(found_downbeats, dtype=np.float64)
    if len(beats) < 4:
        raise BeatError("too few beats were detected: is this music?")
    return beats, downbeats
