"""Audio decoding. ffmpeg handles every format; libsndfile is the fallback for WAV and FLAC."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import numpy as np
import numpy.typing as npt

SR = 22050


class AudioError(Exception):
    """The file is missing or cannot be decoded."""


def load(path: str | Path, sr: int = SR) -> npt.NDArray[np.float32]:
    """Decode to mono float32 at `sr`, through 16-bit PCM so results do not depend on the decoder."""
    src = Path(path).expanduser().resolve()
    if not src.is_file():
        raise AudioError(f"{path}: file not found")
    if shutil.which("ffmpeg"):
        # An absolute path keeps file names starting with "-" from being read as options.
        cmd = [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-i",
            str(src),
            "-vn",
            "-ac",
            "1",
            "-ar",
            str(sr),
            "-f",
            "s16le",
            "-",
        ]
        proc = subprocess.run(cmd, capture_output=True, check=False)
        if proc.returncode == 0 and proc.stdout:
            return np.frombuffer(proc.stdout, dtype="<i2").astype(np.float32) / 32768.0
        raise AudioError(f"{path}: could not read the audio ({_first_line(proc.stderr)})")
    return _load_without_ffmpeg(src, sr)


def _first_line(err: bytes) -> str:
    text = err.decode("utf-8", "replace").strip().splitlines()
    return text[-1] if text else "unknown error"


def _load_without_ffmpeg(src: Path, sr: int) -> npt.NDArray[np.float32]:
    import librosa
    import soundfile as sf

    try:
        data, rate = sf.read(src, dtype="int16", always_2d=True)
    except (RuntimeError, sf.LibsndfileError) as exc:
        raise AudioError(f"{src.name}: could not read the audio, and ffmpeg is not installed ({exc})") from exc
    mono = data.astype(np.float32).mean(axis=1) / 32768.0
    if rate != sr:
        mono = librosa.resample(mono, orig_sr=rate, target_sr=sr)
    return np.asarray(mono, dtype=np.float32)
