"""Instrument parts read from separated stems: drum groove, bass line, comping rhythm, voicings, vocal range."""

from __future__ import annotations

import warnings
from dataclasses import dataclass

import librosa
import numpy as np
import numpy.typing as npt

from woodshed.audio import SR
from woodshed.grid import BeatGrid
from woodshed.model import BassNote, Groove, VocalRange

HOP = 256
SILENT_RMS = 1e-3  # a stem below this level is treated as empty
# A drum band whose strongest hits stay below this multiple of the stem's RMS is not played: on a
# hi-hat-only stem the low band measures 2, real hits 170 to 800, funk hi-hats 46 (see the tests).
BAND_FLOOR = 8.0
MIN_VOICING = 0.3  # least mean pyin voicing probability of a sung note
VOICE_FLOOR = 10 ** (-40 / 20)  # RMS of the quietest singing (bleed sits near -50 dBFS and below)
QUIET_NOTE = 0.1  # a note 20 dB below the loud sung notes is bleed, not singing
SNARE_BODY = 0.1  # least mid-band hit, against the high band, for a snare (synthetic snare 0.8, hi-hat 0.02)
Audio = npt.NDArray[np.float32]
Floats = npt.NDArray[np.float64]


@dataclass(frozen=True)
class Grid:
    """Sixteenth-note slots per bar (four per beat), in seconds."""

    bars: list[Floats]
    beats_per_bar: int

    @classmethod
    def from_beats(cls, beats: Floats, first_beat: int, beats_per_bar: int, n_bars: int | None = None) -> Grid:
        """Bars from beat index `first_beat` (negative for a pickup before the first tracked beat).

        Slots before the start of the file are possible (a pickup at time zero): readers clamp them.
        """
        count = (len(beats) - first_beat) // beats_per_bar if n_bars is None else n_bars
        return cls(BeatGrid.of(beats).sixteenths(first_beat, beats_per_bar, count), beats_per_bar)

    @property
    def sixteenth(self) -> float:
        return float(np.median(np.diff(self.bars[0]))) if self.bars else 0.125

    def span(self, bar: int) -> tuple[float, float]:
        """Start and end of a bar in seconds, clamped at the start of the file."""
        slots = self.bars[bar]
        return max(0.0, float(slots[0])), max(0.0, float(slots[-1]) + self.sixteenth)


def _onsets(y: Audio, hop: int = HOP) -> tuple[Floats, Floats]:
    env = librosa.onset.onset_strength(y=y, sr=SR, hop_length=hop)
    return np.asarray(env, dtype=np.float64), librosa.times_like(env, sr=SR, hop_length=hop)


def _peak(env: Floats, times: Floats, t: float, before: float = 0.03, after: float = 0.03) -> float:
    m = (times >= t - before) & (times <= t + after)
    return float(np.max(env[m])) if m.any() else 0.0


def _silent(y: Audio) -> bool:
    return y.size == 0 or float(np.sqrt(np.mean(y**2))) < SILENT_RMS


def _rms(y: Audio, start: float, end: float) -> float:
    seg = y[int(start * SR) : int(end * SR)]
    return float(np.sqrt(np.mean(seg**2))) if seg.size else 0.0


def drum_grid_shift(drums: Audio, beats: Floats) -> float:
    """Median offset of the strong drum hits from the beat grid: trackers often lag by tens of ms."""
    env, _ = _onsets(drums)
    onsets = librosa.onset.onset_detect(onset_envelope=env, sr=SR, hop_length=HOP, units="time")
    frames = librosa.time_to_frames(onsets, sr=SR, hop_length=HOP)
    loud = np.percentile(env, 95)
    strong = [o for o, f in zip(onsets, frames, strict=True) if env[min(f, len(env) - 1)] > loud]
    period = float(np.median(np.diff(beats)))
    offsets = [o - beats[int(np.argmin(np.abs(beats - o)))] for o in strong]
    offsets = [d for d in offsets if abs(d) < period / 3]
    return float(np.median(offsets)) if len(offsets) >= 10 else 0.0


def drum_groove(drums: Audio, grid: Grid) -> Groove | None:
    """Kick, snare and hi-hat per sixteenth, as the share of bars where each slot is hit."""
    if _silent(drums) or len(grid.bars) < 4:
        return None
    rms = float(np.sqrt(np.mean(drums**2)))
    power = np.abs(librosa.stft(drums, n_fft=1024, hop_length=HOP)) ** 2
    freqs = librosa.fft_frequencies(sr=SR, n_fft=1024)
    times = librosa.frames_to_time(np.arange(power.shape[1]), sr=SR, hop_length=HOP)

    def band(lo: float, hi: float) -> Floats:
        # Linear energy: a log scale lets the snare's faint low end look like a kick.
        energy = np.sqrt(power[(freqs >= lo) & (freqs < hi)].sum(axis=0))
        return np.asarray(np.maximum(0, np.diff(energy, prepend=energy[0])), dtype=np.float64)

    def peaks(curve: Floats) -> Floats:
        return np.array([[_peak(curve, times, t, 0.025, 0.035) for t in bar] for bar in grid.bars])

    def scaled(m: Floats) -> Floats:
        """1 for the band's loud hits; an unplayed band is not scaled up to 1."""
        return np.asarray(m / max(float(np.percentile(m, 95)), BAND_FLOOR * rms), dtype=np.float64)

    raw_mid, raw_high = peaks(band(180, 600)), peaks(band(7000, 11000))
    low, mid, high = scaled(peaks(band(30, 110))), scaled(raw_mid), scaled(raw_high)
    kick = low > 0.5
    # A snare has body (mids) and wires (highs); with the kick it can also land on the same slot.
    # The body is measured against the wires: a hi-hat's mids are about 40 times weaker than its highs.
    body = raw_mid > SNARE_BODY * raw_high
    snare = body & (((mid > 0.3) & (high > 0.7) & (low < 0.5)) | ((mid > 0.6) & (high > 0.5) & (mid > 0.8 * low)))
    hat = high > 0.2
    # Bars where the drums actually play: drums often come in late (a piano ballad).
    loudness = np.array([_rms(drums, *grid.span(b)) for b in range(len(grid.bars))])
    active = loudness > 0.3 * np.percentile(loudness, 90)
    if active.sum() < 4:
        return None
    k, s, h = kick[active], snare[active], hat[active]

    def agreement(b: npt.NDArray[np.bool_]) -> float:
        return round(float((b == (b.mean(0) > 0.5)).mean()), 2)

    return Groove(
        kick=[round(float(x), 2) for x in k.mean(0)],
        snare=[round(float(x), 2) for x in s.mean(0)],
        hat=[round(float(x), 2) for x in h.mean(0)],
        agreement={"kick": agreement(k), "snare": agreement(s), "hat": agreement(h)},
        bars=int(active.sum()),
    )


def bass_line(bass: Audio, grid: Grid) -> list[list[BassNote | None]]:
    """The note started on each sixteenth, per bar, or None where no note starts."""
    if _silent(bass):
        return [[None] * (grid.beats_per_bar * 4) for _ in grid.bars]
    f0, voiced, prob = librosa.pyin(bass, fmin=30, fmax=300, sr=SR, frame_length=2048, hop_length=HOP)
    times = librosa.times_like(f0, sr=SR, hop_length=HOP)
    env, _ = _onsets(bass)
    # Peak-picked onsets, not a level threshold: a clean bass has long decays that a threshold
    # would mistake for new notes.
    onsets = librosa.onset.onset_detect(onset_envelope=env, sr=SR, hop_length=HOP, units="time")
    width = grid.sixteenth * 0.9
    # Onset detectors report attacks slightly late, so the window is wider after the slot.
    before, after = min(0.03, grid.sixteenth / 3), min(0.05, grid.sixteenth * 0.45)
    line: list[list[BassNote | None]] = []
    for bar in grid.bars:
        notes: list[BassNote | None] = []
        for t in bar:
            if not np.any((onsets >= t - before) & (onsets <= t + after)):
                notes.append(None)
                continue
            m = (times >= t) & (times < t + width) & voiced
            if m.sum() >= 2:
                midi = int(np.round(np.nanmedian(librosa.hz_to_midi(f0[m]))))
                notes.append(BassNote(midi, round(float(np.nanmean(prob[m])), 2)))
            else:
                notes.append(None)
        line.append(notes)
    return line


def comp_rhythm(other: Audio, grid: Grid) -> list[float]:
    """Share of bars where the chord instruments (keys, guitars) strike on each sixteenth."""
    if _silent(other):
        return [0.0] * (grid.beats_per_bar * 4)
    env, times = _onsets(other)
    m = np.array([[_peak(env, times, t) for t in bar] for bar in grid.bars])
    return [round(float(x), 2) for x in (m > 0.5 * np.percentile(m, 95)).mean(0)]


def voicings(other: Audio, grid: Grid, threshold: float = 0.62) -> list[list[int]]:
    """Pitch classes sounding in each bar on the chord instruments, strongest first (up to four)."""
    if _silent(other):
        return [[] for _ in grid.bars]
    harmonic = librosa.effects.harmonic(other, margin=4)
    with warnings.catch_warnings():
        # A stem with no pitched content (a hum, a constant) has no tuning to estimate: 0 then.
        warnings.filterwarnings("ignore", "Trying to estimate tuning from empty frequency set")
        tuning = float(librosa.estimate_tuning(y=harmonic, sr=SR))
    chroma = librosa.feature.chroma_cqt(y=harmonic, sr=SR, hop_length=512, tuning=tuning)
    out: list[list[int]] = []
    for i in range(len(grid.bars)):
        a, b = (int(f) for f in librosa.time_to_frames(grid.span(i), sr=SR, hop_length=512))
        if a >= chroma.shape[1] or b <= a:  # a bar of pure pickup silence before time zero
            out.append([])
            continue
        v = np.median(chroma[:, a:b], axis=1)
        v = v / (v.max() + 1e-9)
        out.append([int(i) for i in np.argsort(-v) if v[i] > threshold][:4])
    return out


def _runs(flags: npt.NDArray[np.bool_], min_len: int) -> list[tuple[int, int]]:
    """(start, end) of each run of True at least `min_len` frames long."""
    edges = np.flatnonzero(np.diff(np.concatenate([[0], flags.astype(np.int8), [0]])))
    return [(int(a), int(b)) for a, b in zip(edges[::2], edges[1::2], strict=True) if b - a >= min_len]


def vocal_activity(vocals: Audio, beat_times: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
    """Share of each beat where the voice sings: the vocal track within 20 dB of its loud singing
    (bleed from the other instruments sits about 30 dB below it)."""
    level = librosa.feature.rms(y=vocals, frame_length=2048, hop_length=HOP)[0]
    out = np.zeros(len(beat_times))
    audible = level[level >= SILENT_RMS]
    if audible.size == 0 or len(beat_times) == 0:
        return out
    # Against the loud singing, and an absolute floor: on an instrumental the stem holds only
    # bleed, which its own loudest moments must not turn into singing.
    on = (level >= max(QUIET_NOTE * np.percentile(audible, 90), VOICE_FLOOR)).astype(float)
    step = float(np.median(np.diff(beat_times))) if len(beat_times) > 1 else 0.5
    edges = librosa.time_to_frames(np.append(beat_times, beat_times[-1] + step), sr=SR, hop_length=HOP)
    for i in range(len(beat_times)):
        a, b = int(edges[i]), max(int(edges[i]) + 1, int(edges[i + 1]))
        part = on[a:b]
        out[i] = float(part.mean()) if part.size else 0.0
    return out


def vocal_range(vocals: Audio, min_share: float = 0.15) -> VocalRange | None:
    """Range of the sung notes, or None when the track is mostly silent.

    Measured note by note (median pitch of each sustained note), so attacks and slides do not
    widen the range. Only confident, audible notes count: the vocal stem carries faint bleed from
    the other instruments (on a piano ballad, the piano intro reads as notes a fifth below the voice,
    at a voicing probability of 0.01 and 30 dB below the singing).
    """
    # Up to F6 (1400 Hz): with a lower ceiling, high soprano notes are read an octave down.
    f0, voiced, prob = librosa.pyin(vocals, fmin=80, fmax=1400, sr=SR, frame_length=2048, hop_length=HOP)
    level = librosa.feature.rms(y=vocals, frame_length=2048, hop_length=HOP)[0][: len(f0)]
    midi = librosa.hz_to_midi(f0)
    runs = _runs(np.asarray(voiced), 3)
    if not runs:
        return None
    loud = np.array([float(np.median(level[a:b])) for a, b in runs])
    sure = np.array([float(np.mean(prob[a:b])) for a, b in runs])
    keep = (sure >= MIN_VOICING) & (loud >= QUIET_NOTE * np.percentile(loud, 90))
    sung = [r for r, k in zip(runs, keep, strict=True) if k]
    share = sum(b - a for a, b in sung) / len(f0)
    if share <= min_share:
        return None
    notes = [float(np.nanmedian(midi[a:b])) for a, b in sung]
    return VocalRange(int(np.round(np.percentile(notes, 10))), int(np.round(np.percentile(notes, 90))), round(share, 2))
