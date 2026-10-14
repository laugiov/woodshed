"""Audio decoding of untrusted files: clear errors, bounded work, no network."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from woodshed import audio
from woodshed.errors import AudioError, WoodshedError


def test_errors_share_one_base() -> None:
    assert issubclass(AudioError, WoodshedError)


needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")


@needs_ffmpeg
def test_a_concat_list_disguised_as_mp3_cannot_read_another_file(tmp_path: Path) -> None:
    # Without the format whitelist, ffmpeg reads this as a concat list and decodes secret.wav.
    secret = tmp_path / "secret.wav"
    sf.write(secret, np.full(22050, 0.5), 22050)
    disguised = tmp_path / "song.mp3"
    disguised.write_text(f"ffconcat version 1.0\nfile {secret.name}\n")
    with pytest.raises(AudioError):
        audio.load(disguised)


@needs_ffmpeg
def test_an_hls_playlist_with_a_local_segment_is_refused(tmp_path: Path) -> None:
    # Without the format whitelist, ffmpeg decodes the segment this playlist points to.
    segment = tmp_path / "seg.mp3"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=d=1", "-y", str(segment)], check=True)
    playlist = tmp_path / "song.m3u8"
    playlist.write_text(f"#EXTM3U\n#EXT-X-TARGETDURATION:1\n#EXTINF:1,\n{segment.name}\n#EXT-X-ENDLIST\n")
    with pytest.raises(AudioError, match="not supported"):
        audio.load(playlist)


@needs_ffmpeg
@pytest.mark.parametrize(
    ("ext", "codec"),
    [
        ("mp3", "libmp3lame"), ("m4a", "aac"), ("mp4", "aac"), ("ogg", "libvorbis"), ("opus", "libopus"),
        ("flac", "flac"), ("webm", "libopus"), ("mkv", "aac"), ("aiff", "pcm_s16be"), ("wma", "wmav2"),
        ("avi", "pcm_s16le"), ("ts", "aac"), ("mpg", "mp2"), ("ac3", "ac3"), ("wv", "wavpack"), ("au", "pcm_s16be"),
        ("flv", "aac"), ("eac3", "eac3"), ("tta", "tta"), ("caf", "pcm_s16le"), ("w64", "pcm_s16le"), ("aac", "aac"),
    ],
)  # fmt: skip
def test_common_formats_pass_the_whitelist(tmp_path: Path, ext: str, codec: str) -> None:
    out = tmp_path / f"tone.{ext}"
    cmd = ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=f=440:d=1", "-c:a", codec, "-y", str(out)]
    if subprocess.run(cmd, check=False).returncode != 0:
        pytest.skip(f"this ffmpeg cannot encode {codec}")
    assert abs(audio.load(out).size / audio.SR - 1.0) < 0.1


def test_a_decoder_that_hangs_is_an_audio_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    song = tmp_path / "song.wav"
    sf.write(song, np.zeros(22050), 22050)

    def hang(*args: object, **kwargs: object) -> None:
        raise subprocess.TimeoutExpired(cmd="ffmpeg", timeout=audio.TIMEOUT_SECONDS)

    monkeypatch.setattr("woodshed.audio.shutil.which", lambda _name: "/usr/bin/ffmpeg")
    monkeypatch.setattr("woodshed.audio.subprocess.run", hang)
    with pytest.raises(AudioError, match="longer than"):
        audio.load(song)


def test_a_file_without_audio_says_so(tmp_path: Path) -> None:
    empty = tmp_path / "empty.wav"
    sf.write(empty, np.zeros(0), 22050)
    with pytest.raises(AudioError, match="no audio"):
        audio.load(empty)


def test_files_over_the_limit_are_refused_not_cut_silently(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(audio, "MAX_SECONDS", 2)
    long = tmp_path / "long.wav"
    sf.write(long, np.zeros(22050 * 5), 22050)
    with pytest.raises(AudioError, match="the limit is"):
        audio.load(long)


def test_a_length_missing_from_the_header_is_still_capped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(audio, "MAX_SECONDS", 2)
    monkeypatch.setattr(audio, "duration", lambda _path: 0.0)  # unknown length, as in some streams
    long = tmp_path / "long.wav"
    sf.write(long, np.full(22050 * 5, 0.1), 22050)
    assert audio.load(long).size == 2 * audio.SR


def test_stereo_decoding_keeps_both_channels(tmp_path: Path) -> None:
    song = tmp_path / "stereo.wav"
    left, right = np.full(22050, 0.25), np.full(22050, -0.5)
    sf.write(song, np.stack([left, right], axis=1), 22050)
    y = audio.load(song, sr=22050, channels=2)
    assert y.shape == (2, 22050)
    assert y[0].mean() == pytest.approx(0.25, abs=1e-3) and y[1].mean() == pytest.approx(-0.5, abs=1e-3)


def test_a_file_name_starting_with_a_dash_is_not_an_option(tmp_path: Path) -> None:
    odd = tmp_path / "-y.wav"
    sf.write(odd, np.full(22050, 0.1), 22050)
    assert audio.load(odd).size == audio.SR


@needs_ffmpeg
def test_the_length_probe_cannot_read_another_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Header reading falls back to ffprobe for non-WAV files: it must have the same whitelist.
    secret = tmp_path / "secret.wav"
    sf.write(secret, np.full(22050 * 3, 0.5), 22050)
    disguised = tmp_path / "song.mp3"
    disguised.write_text(f"ffconcat version 1.0\nfile {secret.name}\nduration 3.0\n")
    with pytest.raises(AudioError):
        audio.duration(disguised)  # without the whitelist, ffprobe opens the list and answers 3.0


@needs_ffmpeg
def test_odd_stereo_lengths_decode_in_channel_order(tmp_path: Path) -> None:
    song = tmp_path / "odd.wav"
    sf.write(song, np.stack([np.full(1001, 0.25), np.full(1001, -0.5)], axis=1), 22050)
    y = audio.load(song, sr=22050, channels=2)
    assert y.shape == (2, 1001) and y.flags.c_contiguous and y.dtype == np.float32
    assert y[0].mean() == pytest.approx(0.25, abs=1e-3) and y[1].mean() == pytest.approx(-0.5, abs=1e-3)
