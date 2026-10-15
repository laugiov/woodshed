"""Audio decoding. ffmpeg handles every format; libsndfile is the fallback for WAV and FLAC."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import numpy as np
import numpy.typing as npt
import soundfile as sf

from woodshed.errors import AudioError

SR = 22050
MAX_SECONDS = 30 * 60  # longer files are cut: memory and analysis time grow with duration
TIMEOUT_SECONDS = 600

__all__ = ["MAX_SECONDS", "SR", "AudioError", "load"]


def load(path: str | Path, sr: int = SR, channels: int = 1) -> npt.NDArray[np.float32]:
    """Decode to float32 at `sr`, through 16-bit PCM: shape (n,) in mono, (channels, n) otherwise.

    This is the only decoder of user files (stem separation goes through it too), so its limits
    apply everywhere: media containers only, local files only, a time limit and a length limit.
    ffmpeg when installed, else soundfile and librosa for WAV, FLAC and Ogg: the two paths resample
    differently, so their samples can differ slightly.
    """
    src = Path(path).expanduser().resolve()
    if not src.is_file():
        raise AudioError(f"{path}: file not found")
    try:
        seconds = duration(src)
    except AudioError:
        seconds = 0.0  # unknown from the header: the decoder's own cut (-t) still applies
    if seconds > MAX_SECONDS:
        raise AudioError(f"{src.name} lasts {seconds / 60:.0f} minutes: the limit is {MAX_SECONDS // 60}")
    decode = _load_with_ffmpeg if shutil.which("ffmpeg") else _load_without_ffmpeg
    y = decode(src, sr, channels)
    if y.size == 0:
        raise AudioError(f"{path}: the file contains no audio")
    return y


def duration(path: str | Path) -> float:
    """Length in seconds, read from the file header (no decoding)."""
    src = Path(path).expanduser().resolve()
    try:
        return float(sf.info(src).duration)
    except (RuntimeError, sf.LibsndfileError):
        pass
    if not shutil.which("ffprobe"):
        raise AudioError(f"{src.name}: cannot read its length without ffmpeg installed")
    cmd = [
        "ffprobe", "-v", "error", "-format_whitelist", FORMATS, "-protocol_whitelist", "file,pipe",
        "-show_entries", "format=duration", "-of", "csv=p=0", str(src),
    ]  # fmt: skip
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=60)
        return float(proc.stdout.strip())
    except (subprocess.TimeoutExpired, ValueError) as exc:
        raise AudioError(f"{src.name}: could not read its length") from exc


# File extensions a songbook folder is scanned for.
MEDIA = frozenset(
    [
        ".mp3",
        ".wav",
        ".flac",
        ".ogg",
        ".oga",
        ".opus",
        ".m4a",
        ".aac",
        ".aif",
        ".aiff",
        ".wma",
        ".wv",
        ".ac3",
        ".mp4",
        ".m4v",
        ".mov",
        ".mkv",
        ".webm",
        ".avi",
        ".mpg",
        ".ts",
    ]
)

# Demuxers for the audio and video files musicians have. Playlist and list formats (hls, concat,
# m3u, ffconcat) are left out on purpose. The ones ffmpeg can encode are tested in test_audio.py.
FORMATS = (
    "wav,w64,mp3,flac,ogg,mov,matroska,aac,aiff,asf,caf,"  # the usual audio files and mp4/mkv/webm video
    "avi,flv,mpegts,mpeg,ac3,eac3,dts,wv,tta,ape,au,amr,dsf,mpc,mpc8,tak,shn"  # rarer; none refers to files
)


def _load_with_ffmpeg(src: Path, sr: int, channels: int) -> npt.NDArray[np.float32]:
    cmd = [
        "ffmpeg", "-nostdin", "-v", "error",
        # Media containers only. ffmpeg picks the demuxer from the content, not the extension: a
        # concat or HLS playlist named song.mp3 would otherwise read other local files.
        "-format_whitelist", FORMATS,
        # Local file and pipe only, whatever a container refers to.
        "-protocol_whitelist", "file,pipe",
        # An absolute path keeps file names starting with "-" from being read as options.
        "-i", str(src),
        "-vn", "-ac", str(channels), "-ar", str(sr), "-t", str(MAX_SECONDS), "-f", "s16le", "-",
    ]  # fmt: skip
    try:
        proc = subprocess.run(cmd, capture_output=True, check=False, timeout=TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired as exc:
        raise AudioError(f"{src.name}: decoding took longer than {TIMEOUT_SECONDS} s") from exc
    if proc.returncode < 0:  # killed by a signal: a bug of this ffmpeg build, not of the file alone
        signal = -proc.returncode
        raise AudioError(f"{src.name}: ffmpeg crashed reading it (signal {signal}); try another ffmpeg version")
    if proc.returncode != 0:
        if b"not on whitelist" in proc.stderr:
            raise AudioError(f"{src.name}: this kind of file is not supported (not an audio or video container)")
        raise AudioError(f"{src.name}: could not read the audio ({_last_line(proc.stderr)})")
    raw = np.frombuffer(proc.stdout, dtype="<i2")
    if channels > 1:  # interleaved frames to (channels, n), on int16 before the float copy
        raw = raw[: raw.size - raw.size % channels].reshape(-1, channels).T
    pcm = np.ascontiguousarray(raw, dtype=np.float32)
    pcm /= 32768.0  # in place: a 30-minute stereo file is 635 MB as float32
    return pcm


def _last_line(err: bytes) -> str:
    text = err.decode("utf-8", "replace").strip().splitlines()
    return text[-1] if text else "unknown error"


def _load_without_ffmpeg(src: Path, sr: int, channels: int) -> npt.NDArray[np.float32]:
    import librosa

    try:
        info = sf.info(src)
        frames = min(info.frames, int(MAX_SECONDS * info.samplerate))
        data, rate = sf.read(src, dtype="int16", always_2d=True, frames=frames)
    except (RuntimeError, sf.LibsndfileError) as exc:
        raise AudioError(f"{src.name}: could not read the audio, and ffmpeg is not installed ({exc})") from exc
    pcm = data.astype(np.float32).T / 32768.0  # (file channels, n)
    if channels == 1:
        out = pcm.mean(axis=0)
    else:  # as ffmpeg does: a mono file is copied to every channel, extra channels are averaged
        out = np.repeat(pcm.mean(axis=0, keepdims=True), channels, axis=0) if pcm.shape[0] != channels else pcm
    if rate != sr and out.size:
        out = librosa.resample(out, orig_sr=rate, target_sr=sr, axis=-1)
    return np.asarray(out, dtype=np.float32)
