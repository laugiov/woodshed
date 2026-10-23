"""The singer's key without ffmpeg's filter (spec 017): the Rubber Band program, found and run as ffmpeg is.

The lookup, the command line, stops and errors run against a fake program (fast, everywhere but Windows); the
sound itself against the real one, when it is found (`WOODSHED_REQUIRE_RUBBERBAND=1`: it must be).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time
from collections import namedtuple
from collections.abc import Iterator
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from woodshed import pitch
from woodshed.errors import WoodshedError
from woodshed.stems import CEILING

RATE = 44100
REQUIRED = os.environ.get("WOODSHED_REQUIRE_RUBBERBAND") == "1"

FAKE = """#!{python}
import json, os, sys, time
import numpy as np
import soundfile as sf
args = sys.argv[1:]
if args == ["-V"]:
    sys.stderr.write("{version}\\n")
    sys.exit(0)
src, out = args[-2], args[-1]
info = sf.info(src)
data, rate = sf.read(src, dtype="float64", always_2d=True)
log = os.environ.get("FAKE_RB_LOG")
if log:
    with open(log, "a") as f:
        f.write(json.dumps({{"args": args, "cwd": os.getcwd(), "subtype": info.subtype,
                            "peak": float(np.max(np.abs(data)))}}) + "\\n")
time.sleep(float(os.environ.get("FAKE_RB_SECONDS", "0")))
if os.environ.get("FAKE_RB_FAIL"):
    sys.stderr.write("ERROR: Failed to open input file /srv/jane/My Songs/" + src + "\\n")
    sys.exit(1)
if os.environ.get("FAKE_RB_CLIP"):
    data = np.clip(data * 8, -1.0, 1.0)
sf.write(out, data, rate, subtype=info.subtype, format="WAV")
"""

fake_only = pytest.mark.skipif(sys.platform == "win32", reason="the fake program is a script with a shebang")


def fake_program(folder: Path, version: str = "4.0.0") -> Path:
    """A `rubberband` that copies its input (or fails, sleeps, clips: FAKE_RB_*), and says `version` to -V."""
    folder.mkdir(parents=True, exist_ok=True)
    program = folder / "rubberband"
    program.write_text(FAKE.format(python=sys.executable, version=version), encoding="utf-8")
    program.chmod(0o755)
    return program


@pytest.fixture
def clean_lookup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """No ffmpeg filter, an empty tools folder and a PATH with nothing but this test's programs (and nice)."""
    empty = tmp_path / "tools"
    empty.mkdir()
    monkeypatch.setenv("WOODSHED_TOOLS", str(empty))
    path = tmp_path / "path"
    path.mkdir()
    nice = shutil.which("nice")
    if nice:
        (path / "nice").symlink_to(nice)
    monkeypatch.setenv("PATH", str(path))
    monkeypatch.setattr(pitch, "available", lambda: False)
    pitch.program.cache_clear()
    yield path
    pitch.program.cache_clear()


def write(path: Path, signal: np.ndarray) -> Path:
    """A page's track: 24-bit FLAC, stereo from a 1-D signal, as it is from a 2-D one."""
    path.parent.mkdir(parents=True, exist_ok=True)
    frames = np.stack([signal, signal], axis=1) if signal.ndim == 1 else signal
    sf.write(path, frames, RATE, subtype="PCM_24", format="FLAC")
    return path


def harmonic(f0: float, seconds: float, peak: float) -> np.ndarray:
    t = np.arange(int(seconds * RATE)) / RATE
    tone = sum(np.sin(2 * np.pi * f0 * k * t) / k for k in (1, 2, 3, 4))
    return np.asarray(tone / np.max(np.abs(tone)) * peak, dtype=np.float64)


def page_track(tmp_path: Path, signal: np.ndarray, track: str = "mix", semitones: int = 2) -> tuple[Path, Path]:
    src = write(tmp_path / "Song.woodshed" / "audio" / f"{track}.flac", signal)
    return src, src.parent / pitch.KEY_DIR / pitch.key_dir(semitones) / f"{track}.flac"


def leftovers(dst: Path) -> list[str]:
    return sorted(p.name for p in dst.parent.glob(".*")) if dst.parent.is_dir() else []


# Where the program is found.


def test_the_tools_folder_per_system(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("WOODSHED_TOOLS", raising=False)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    home = Path.home()
    monkeypatch.setattr(sys, "platform", "darwin")
    assert pitch.tools_dir() == home / "Library" / "Application Support" / "woodshed" / "tools"
    monkeypatch.setattr(sys, "platform", "win32")
    assert pitch.tools_dir() == tmp_path / "Local" / "woodshed" / "tools"
    monkeypatch.setattr(sys, "platform", "linux")
    assert pitch.tools_dir() == home / ".local" / "share" / "woodshed" / "tools"
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    assert pitch.tools_dir() == tmp_path / "data" / "woodshed" / "tools"
    monkeypatch.setenv("WOODSHED_TOOLS", str(tmp_path / "mine"))
    assert pitch.tools_dir() == tmp_path / "mine"


@fake_only
def test_ffmpeg_s_filter_comes_first(clean_lookup: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_program(Path(os.environ["WOODSHED_TOOLS"]))
    monkeypatch.setattr(pitch, "available", lambda: True)
    found = pitch.tool()
    assert found is not None and found[0] == "ffmpeg"


@fake_only
def test_then_the_tools_folder_then_the_path(clean_lookup: Path) -> None:
    tools = Path(os.environ["WOODSHED_TOOLS"])
    on_path = fake_program(clean_lookup, "3.3.0")
    in_tools = fake_program(tools)
    assert pitch.tool() == ("rubberband", str(in_tools))  # the pinned one, before whatever the PATH holds
    in_tools.unlink()
    pitch.program.cache_clear()
    assert pitch.tool() == ("rubberband", str(on_path))


@fake_only
@pytest.mark.parametrize(("version", "found"), [("2.0.2", False), ("3.1.3", False), ("3.2.0", True), ("4.0.0", True)])
def test_a_program_older_than_3_2_is_not_used(clean_lookup: Path, version: str, found: bool) -> None:
    # Ubuntu 22.04's rubberband-cli is 2.0.2: no R3 engine (-3), no mono-compatible centre focus.
    fake_program(clean_lookup, version)
    assert (pitch.tool() is not None) is found


@fake_only
def test_nothing_found(clean_lookup: Path) -> None:
    assert pitch.tool() is None
    assert not pitch.blocked()


def blocked_program(folder: Path) -> Path:
    """The installers' program, there but refused by the system (Smart App Control, an antivirus)."""
    folder.mkdir(parents=True, exist_ok=True)
    program = folder / "rubberband"
    program.write_text("#!/bin/sh\nexit 126\n", encoding="utf-8")
    program.chmod(0o755)
    return program


@fake_only
def test_a_program_in_the_tools_folder_that_cannot_run_is_said_blocked(clean_lookup: Path) -> None:
    blocked_program(Path(os.environ["WOODSHED_TOOLS"]))
    assert pitch.tool() is None and pitch.blocked()
    fake_program(clean_lookup)  # another one on the PATH renders: nothing is blocked then
    pitch.program.cache_clear()
    assert pitch.tool() is not None and not pitch.blocked()


# The render with a fake program.


@fake_only
@pytest.mark.parametrize(
    ("track", "semitones", "formant"), [("mix", 2, True), ("solo-vocals", -3, True), ("solo-bass", 1, False)]
)
def test_the_command_line(
    clean_lookup: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, track: str, semitones: int, formant: bool
) -> None:
    program = fake_program(Path(os.environ["WOODSHED_TOOLS"]))
    log = tmp_path / "rb.log"
    monkeypatch.setenv("FAKE_RB_LOG", str(log))
    src, dst = page_track(tmp_path, harmonic(220.0, 1.0, 0.8), track, semitones)
    pitch.render(src, dst, semitones, track, pitch.fingerprint(src), using=("rubberband", str(program)))
    [call] = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    args, decoded, rendered = call["args"][:-2], call["args"][-2], call["args"][-1]
    assert args == [
        "-3",
        "--centre-focus",
        *(["-F"] if formant else []),
        "-p",
        str(semitones),
        "-q",
        "--ignore-clipping",
    ]
    # Relative ASCII names in the key's folder: libsndfile takes ANSI paths on Windows, and no folder in an error.
    assert Path(call["cwd"]).resolve() == dst.parent.resolve()
    for name in (decoded, rendered):
        assert name.startswith(".") and name.isascii() and "/" not in name and "\\" not in name
    # The source decoded to float, a quarter of its level: the program never meets a sample it would clamp.
    assert call["subtype"] == "FLOAT"
    assert call["peak"] == pytest.approx(0.8 / 4, abs=1e-4)
    out, _ = sf.read(dst)
    original, _ = sf.read(src)
    assert out.shape == original.shape and sf.info(str(dst)).subtype == "PCM_24"
    level = 20 * np.log10(np.sqrt(np.mean(out**2)) / np.sqrt(np.mean(original**2)))
    assert abs(level) < 0.01  # the level step gives the quarter back
    assert leftovers(dst) == []


@fake_only
def test_a_render_that_would_clip_is_refused(
    clean_lookup: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    program = fake_program(Path(os.environ["WOODSHED_TOOLS"]))
    monkeypatch.setenv("FAKE_RB_CLIP", "1")
    src, dst = page_track(tmp_path, harmonic(220.0, 1.0, 0.8))
    with pytest.raises(WoodshedError, match="could not change the key"):
        pitch.render(src, dst, 2, "mix", pitch.fingerprint(src), using=("rubberband", str(program)))
    assert not dst.exists() and leftovers(dst) == []


@fake_only
def test_a_failed_program_says_why_without_this_computer_s_folders(
    clean_lookup: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    program = fake_program(Path(os.environ["WOODSHED_TOOLS"]))
    monkeypatch.setenv("FAKE_RB_FAIL", "1")
    src, dst = page_track(tmp_path, harmonic(220.0, 1.0, 0.5))
    with pytest.raises(WoodshedError, match="could not change the key") as error:
        pitch.render(src, dst, 2, "mix", pitch.fingerprint(src), using=("rubberband", str(program)))
    assert (
        "jane" not in str(error.value) and "My Songs" not in str(error.value) and str(tmp_path) not in str(error.value)
    )
    assert not dst.exists() and leftovers(dst) == []
    # The program's own reason goes to the server's console, its folders cut.
    console = capsys.readouterr().err
    assert "Failed to open input file" in console and "/srv/jane/" not in console and str(tmp_path) not in console


@fake_only
def test_a_stop_before_the_program_leaves_nothing(clean_lookup: Path, tmp_path: Path) -> None:
    program = fake_program(Path(os.environ["WOODSHED_TOOLS"]))
    src, dst = page_track(tmp_path, harmonic(220.0, 1.0, 0.5))
    with pytest.raises(pitch.Cancelled):
        pitch.render(
            src, dst, 2, "mix", pitch.fingerprint(src), should_stop=lambda: True, using=("rubberband", str(program))
        )
    assert not dst.exists() and leftovers(dst) == []


@fake_only
def test_a_stop_while_the_program_runs_kills_it(
    clean_lookup: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    program = fake_program(Path(os.environ["WOODSHED_TOOLS"]))
    monkeypatch.setenv("FAKE_RB_SECONDS", "30")
    src, dst = page_track(tmp_path, harmonic(220.0, 1.0, 0.5))
    children: list[object] = []
    stop = threading.Event()
    threading.Timer(1.0, stop.set).start()
    started = time.monotonic()
    with pytest.raises(pitch.Cancelled):
        pitch.render(
            src, dst, 2, "mix", pitch.fingerprint(src), should_stop=stop.is_set,
            on_child=children.append, using=("rubberband", str(program)),
        )  # fmt: skip
    assert time.monotonic() - started < 10
    assert children[0] is not None and children[-1] is None  # the child was handed over, then let go
    assert not dst.exists() and leftovers(dst) == []


@fake_only
def test_a_stuck_program_is_killed(clean_lookup: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    program = fake_program(Path(os.environ["WOODSHED_TOOLS"]))
    monkeypatch.setenv("FAKE_RB_SECONDS", "30")
    monkeypatch.setattr(pitch, "LEAST", 1.0)
    monkeypatch.setattr(pitch, "SLOWEST", 0.1)
    src, dst = page_track(tmp_path, harmonic(220.0, 1.0, 0.5))
    with pytest.raises(WoodshedError, match="too long"):
        pitch.render(src, dst, 2, "mix", pitch.fingerprint(src), using=("rubberband", str(program)))
    assert not dst.exists() and leftovers(dst) == []


@fake_only
def test_the_program_needs_more_disk_than_ffmpeg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Two float WAVs in the middle (the decoded source and the render): about nine times the FLAC.
    root = tmp_path / "lib"
    write(root / "One.woodshed" / "audio" / "mix.flac", harmonic(220.0, 1.0, 0.5))
    size = (root / "One.woodshed" / "audio" / "mix.flac").stat().st_size
    usage = namedtuple("usage", "total used free")
    monkeypatch.setattr(shutil, "disk_usage", lambda path: usage(10**12, 0, size * 7))
    renders = pitch.Renders(root, busy=lambda: True)  # nothing is rendered: only the asking is tested
    try:
        monkeypatch.setattr(pitch, "tool", lambda: ("ffmpeg", "ffmpeg"))
        assert renders.ask("One.woodshed", "mix", 2) == "queued"
        monkeypatch.setattr(pitch, "tool", lambda: ("rubberband", "rubberband"))
        with pytest.raises(WoodshedError, match="free disk"):
            renders.ask("One.woodshed", "mix", 3)
    finally:
        renders.stop()


# The sound, with the real program.


def real_program() -> str | None:
    pitch.program.cache_clear()
    return pitch.program()


PROGRAM = real_program()
needs_program = pytest.mark.skipif(
    PROGRAM is None and not REQUIRED, reason="the Rubber Band program (3.2 or newer) is not installed"
)


def test_the_ci_that_needs_the_program_has_it() -> None:
    if REQUIRED:
        assert PROGRAM is not None, "WOODSHED_REQUIRE_RUBBERBAND=1 but no Rubber Band program 3.2 or newer"


def real_render(src: Path, dst: Path, semitones: int, track: str) -> np.ndarray:
    assert PROGRAM is not None
    pitch.render(src, dst, semitones, track, pitch.fingerprint(src), using=("rubberband", PROGRAM))
    out, _ = sf.read(dst, always_2d=True)
    return np.asarray(out)


def frequency(signal: np.ndarray, low: float, high: float) -> float:
    """The strongest partial between `low` and `high`, to a hundredth of a bin (parabolic interpolation)."""
    spectrum = np.log(np.abs(np.fft.rfft(signal * np.hanning(len(signal)), 4 * len(signal))) + 1e-12)
    bin_hz = RATE / (4 * len(signal))
    lo, hi = int(low / bin_hz), int(high / bin_hz)
    k = lo + int(np.argmax(spectrum[lo:hi]))
    a, b, c = spectrum[k - 1], spectrum[k], spectrum[k + 1]
    return float((k + 0.5 * (a - c) / (a - 2 * b + c)) * bin_hz)


@needs_program
@pytest.mark.parametrize("channels", [1, 2])
@pytest.mark.parametrize(("track", "semitones"), [("mix", 2), ("solo-vocals", -3), ("solo-bass", 5)])
def test_in_tune_as_long_and_at_its_level(tmp_path: Path, channels: int, track: str, semitones: int) -> None:
    tone = harmonic(220.0, 4.0, 0.5)
    signal = tone if channels == 1 else np.stack([tone, np.roll(tone, 37) * 0.8], axis=1)
    src = tmp_path / "Song.woodshed" / "audio" / f"{track}.flac"
    src.parent.mkdir(parents=True)
    sf.write(src, signal, RATE, subtype="PCM_24", format="FLAC")
    dst = src.parent / pitch.KEY_DIR / pitch.key_dir(semitones) / f"{track}.flac"
    out = real_render(src, dst, semitones, track)
    original, _ = sf.read(src, always_2d=True)
    assert out.shape == original.shape  # the same length to the sample: the beats stay where they are
    assert np.sqrt(np.mean(out[-RATE // 4 :] ** 2)) > 0.5 * np.sqrt(np.mean(original**2))  # its end too: no padding
    level = 20 * np.log10(np.sqrt(np.mean(out**2)) / np.sqrt(np.mean(original**2)))
    assert abs(level) < 1.0
    want = 220.0 * 2 ** (semitones / 12)
    for channel in range(channels):
        got = frequency(out[RATE : 3 * RATE, channel], want * 0.8, want * 1.2)
        assert abs(1200 * np.log2(got / want)) < 3.0, (channel, got, want)
    assert leftovers(dst) == []


def interior(signal: np.ndarray) -> np.ndarray:
    return signal[RATE // 4 : -RATE // 4]  # the program's first and last frames differ with the level


def partials(signal: np.ndarray, f0: float, count: int) -> np.ndarray:
    """The levels (dB) of the first `count` partials of a tone on `f0`, from the strongest bin near each, the
    channels' powers summed: with the centre focus a channel is mid plus or minus side, whose phases move with
    the level; their summed power does not."""
    window = np.hanning(len(signal))[:, None]
    power = np.sum(np.abs(np.fft.rfft(signal * window, axis=0)) ** 2, axis=1)
    bin_hz = RATE / len(signal)
    levels = []
    for k in range(1, count + 1):
        centre = round(k * f0 / bin_hz)
        levels.append(10 * np.log10(np.max(power[centre - 3 : centre + 4])))
    return np.array(levels)


@needs_program
@pytest.mark.parametrize("track", ["mix", "solo-bass"])  # formants kept, formants shifted
def test_a_quarter_of_the_level_renders_the_same(tmp_path: Path, track: str) -> None:
    # The program's R3 engine is not scale-invariant sample by sample (its phases move with the input's level,
    # and a weak partial by about 1 dB either way, at any level): the strong partials and the whole must not.
    tone = harmonic(220.0, 3.0, 0.5)
    signal = np.stack([tone, np.roll(tone, 37)], axis=1)
    loud = real_render(*page_track(tmp_path / "a", signal, track), 2, track)
    quiet = 4 * real_render(*page_track(tmp_path / "b", signal * 0.25, track), 2, track)
    f0 = 220.0 * 2 ** (2 / 12)
    difference = partials(interior(loud), f0, 3) - partials(interior(quiet), f0, 3)
    assert np.max(np.abs(difference)) < 0.1, difference
    assert abs(20 * np.log10(np.sqrt(np.mean(loud**2)) / np.sqrt(np.mean(quiet**2)))) < 0.1


@needs_program
@pytest.mark.parametrize("track", ["mix", "solo-bass"])
def test_a_stereo_source_at_0_99_never_clamps(tmp_path: Path, track: str) -> None:
    # A shift moves the waveform's peaks above the source's, and the program clamps what goes over 1.0 (with
    # --ignore-clipping as without). Rendered a quarter down nothing goes over; the level step brings it back
    # as loud as the ceiling allows.
    t = np.arange(3 * RATE) / RATE
    wave = np.sign(np.sin(2 * np.pi * 220 * t)) * 0.6 + 0.38 * np.sin(2 * np.pi * 331 * t)
    wave = wave / np.max(np.abs(wave)) * 0.99
    signal = np.stack([wave, np.roll(wave, 37)], axis=1).astype(np.float32)
    src, dst = page_track(tmp_path, signal, track)
    out = real_render(src, dst, 2, track)
    assert np.max(np.abs(out)) == pytest.approx(CEILING, abs=1e-3)  # its peaks grew: as loud as the ceiling allows
    # The case is real: the same program given the source as it is clamps it.
    assert PROGRAM is not None
    sf.write(tmp_path / "as-is.wav", signal, RATE, subtype="FLOAT")
    formants = ["-F"] if track in pitch.FORMANTS_KEPT else []
    args = [PROGRAM, "-3", "--centre-focus", *formants, "-p", "2", "-q", "--ignore-clipping", "as-is.wav", "out.wav"]
    subprocess.run(args, cwd=tmp_path, check=True, capture_output=True)
    clamped, _ = sf.read(tmp_path / "out.wav")
    assert np.max(np.abs(clamped)) >= pitch.CLAMPED


@needs_program
@pytest.mark.parametrize("track", ["mix", "solo-bass"])
def test_the_rendered_track_stays_on_the_beat(tmp_path: Path, track: str) -> None:
    signal = harmonic(196.0, 6.0, 0.05)
    times = [0.5 + 0.61 * k for k in range(8)]
    burst = np.sin(2 * np.pi * 1000 * np.arange(int(0.02 * RATE)) / RATE) * 0.8
    for t in times:
        start = int(t * RATE)
        signal[start : start + len(burst)] += burst
    out = real_render(*page_track(tmp_path, signal, track), 2, track)
    envelope = np.abs(out[:, 0])
    for t in times:
        window = envelope[int((t - 0.05) * RATE) : int((t + 0.05) * RATE)]
        onset = (int((t - 0.05) * RATE) + int(np.argmax(window > 0.3))) / RATE
        assert abs(onset - t) < 0.010, (track, t, onset)
