"""The recording in another key (spec 007): the render with the real ffmpeg and its Rubber Band filter."""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from woodshed import pitch
from woodshed.errors import WoodshedError
from woodshed.stems import CEILING

RATE = 44100

needs_rubberband = pytest.mark.skipif(
    not pitch.available() and os.environ.get("WOODSHED_REQUIRE_PITCH") != "1",
    reason="ffmpeg with the rubberband filter is not installed",
)


def test_the_ci_that_needs_rubberband_has_it() -> None:
    if os.environ.get("WOODSHED_REQUIRE_PITCH") == "1":
        assert pitch.available(), "WOODSHED_REQUIRE_PITCH=1 but ffmpeg has no rubberband filter"


def write(path: Path, signal: np.ndarray) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(path, np.stack([signal, signal], axis=1), RATE, subtype="PCM_24", format="FLAC")
    return path


def harmonic(f0: float, seconds: float, peak: float) -> np.ndarray:
    t = np.arange(int(seconds * RATE)) / RATE
    tone = sum(np.sin(2 * np.pi * f0 * k * t) / k for k in (1, 2, 3, 4))
    return np.asarray(tone / np.max(np.abs(tone)) * peak, dtype=np.float64)


def fundamental(signal: np.ndarray) -> float:
    spectrum = np.abs(np.fft.rfft(signal * np.hanning(len(signal))))
    freqs = np.fft.rfftfreq(len(signal), 1 / RATE)
    band = (freqs > 150) & (freqs < 400)
    return float(freqs[band][np.argmax(spectrum[band])])


def page_track(tmp_path: Path, signal: np.ndarray, track: str = "mix") -> tuple[Path, Path]:
    src = write(tmp_path / "Song.woodshed" / "audio" / f"{track}.flac", signal)
    return src, src.parent / pitch.KEY_DIR / pitch.key_dir(2) / f"{track}.flac"


@needs_rubberband
@pytest.mark.parametrize("track", ["mix", "solo-bass"])  # formants kept, formants shifted
def test_a_track_two_semitones_up_is_in_tune_as_long_and_at_its_level(tmp_path: Path, track: str) -> None:
    src, dst = page_track(tmp_path, harmonic(220.0, 3.0, 0.5), track)
    pitch.render(src, dst, 2, track, pitch.fingerprint(src))
    out, rate = sf.read(dst)
    original, _ = sf.read(src)
    info = sf.info(str(dst))
    assert rate == RATE and info.subtype == "PCM_24" and info.format == "FLAC"
    assert out.shape == original.shape  # the same length to the sample: the beats stay where they are
    mid = out[RATE // 2 : RATE * 5 // 2, 0]
    assert abs(fundamental(mid) - 220.0 * 2 ** (2 / 12)) < 0.01 * 246.9
    level = 20 * np.log10(np.sqrt(np.mean(out**2)) / np.sqrt(np.mean(original**2)))
    assert abs(level) < 0.5  # switching key does not change the level
    assert not list(dst.parent.glob(".*"))  # no temporary file left


@needs_rubberband
def test_a_track_at_the_ceiling_never_clips(tmp_path: Path) -> None:
    # A shift moves the waveform's peaks: a track already at the tracks' ceiling would clip at its own level.
    # Never distorted: it plays a little quieter instead.
    src, dst = page_track(tmp_path, harmonic(220.0, 3.0, 0.999))
    pitch.render(src, dst, 2, "mix", pitch.fingerprint(src))
    out, _ = sf.read(dst)
    original, _ = sf.read(src)
    assert np.max(np.abs(out)) <= CEILING + 1e-4
    assert np.sqrt(np.mean(out**2)) <= np.sqrt(np.mean(original**2)) * 1.06


@needs_rubberband
@pytest.mark.parametrize("track", ["mix", "solo-vocals", "minus-vocals"])
def test_the_rendered_track_stays_on_the_beat(tmp_path: Path, track: str) -> None:
    # Short bursts at known times over a quiet tone: each burst of the render where it was.
    signal = harmonic(196.0, 6.0, 0.05)
    times = [0.5 + 0.61 * k for k in range(8)]
    burst = np.sin(2 * np.pi * 1000 * np.arange(int(0.02 * RATE)) / RATE) * 0.8
    for t in times:
        start = int(t * RATE)
        signal[start : start + len(burst)] += burst
    src, dst = page_track(tmp_path, signal, track)
    pitch.render(src, dst, 2, track, pitch.fingerprint(src))
    out, _ = sf.read(dst)
    envelope = np.abs(out[:, 0])
    for t in times:
        window = envelope[int((t - 0.05) * RATE) : int((t + 0.05) * RATE)]
        onset = (int((t - 0.05) * RATE) + int(np.argmax(window > 0.3))) / RATE
        assert abs(onset - t) < 0.010, (track, t, onset)


def test_what_is_never_rendered(tmp_path: Path) -> None:
    src, dst = page_track(tmp_path, harmonic(220.0, 1.0, 0.5), "solo-drums")
    for semitones, track in ((2, "solo-drums"), (0, "mix"), (7, "mix"), (-7, "mix")):
        with pytest.raises(WoodshedError):
            pitch.render(src, dst, semitones, track, pitch.fingerprint(src))


def test_the_key_folders_have_no_plus_in_their_url() -> None:
    assert [pitch.key_dir(n) for n in (2, -3, 6, -6)] == ["up2", "down3", "up6", "down6"]


@needs_rubberband
def test_a_page_rebuilt_during_the_render_gets_nothing(tmp_path: Path) -> None:
    src, dst = page_track(tmp_path, harmonic(220.0, 1.0, 0.5))
    before = pitch.fingerprint(src)
    write(src, harmonic(330.0, 1.0, 0.5))  # the page rebuilt: another analysis' file
    os.utime(src, ns=(before[1] + 10**9, before[1] + 10**9))
    with pytest.raises(pitch.Cancelled):
        pitch.render(src, dst, 2, "mix", before)
    assert not dst.exists() and not list(dst.parent.glob(".*"))


def test_a_render_stopped_leaves_nothing(tmp_path: Path) -> None:
    src, dst = page_track(tmp_path, harmonic(220.0, 1.0, 0.5))
    if not pitch.available():
        pytest.skip("ffmpeg with the rubberband filter is not installed")
    with pytest.raises(pitch.Cancelled):
        pitch.render(src, dst, 2, "mix", pitch.fingerprint(src), should_stop=lambda: True)
    assert not dst.exists() and not list(dst.parent.glob(".*"))


def test_old_keys_are_pruned_and_leftovers_cleaned(tmp_path: Path) -> None:
    audio = tmp_path / "Song.woodshed" / "audio"
    for key in ("up2", "down3", "up5"):
        write(audio / pitch.KEY_DIR / key / "mix.flac", harmonic(220.0, 0.1, 0.5))
    (audio / pitch.KEY_DIR / "up2" / ".mix.1234.part").write_bytes(b"cut by a stop")
    pitch.clean_leftovers(tmp_path)
    assert not (audio / pitch.KEY_DIR / "up2" / ".mix.1234.part").exists()
    assert pitch.prune(audio, {"up2", "up5"}) == ["down3"]
    assert sorted(p.name for p in (audio / pitch.KEY_DIR).iterdir()) == ["up2", "up5"]
