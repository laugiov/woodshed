"""Instrument parts read from separated stems: drum groove, bass line, comping rhythm, voicings, vocal range."""

from __future__ import annotations

from dataclasses import dataclass

import librosa
import numpy as np
import numpy.typing as npt

from woodshed.audio import SR

HOP = 256
Audio = npt.NDArray[np.float32]
Floats = npt.NDArray[np.float64]


@dataclass(frozen=True)
class Grid:
    """Sixteenth-note slots per bar (four per beat), in seconds."""

    bars: list[Floats]
    beats_per_bar: int

    @classmethod
    def from_beats(cls, beats: Floats, first_beat: int, beats_per_bar: int, n_bars: int | None = None) -> Grid:
        beats = np.asarray(beats, dtype=np.float64)
        period = float(np.median(np.diff(beats)))

        def beat(i: int) -> float:
            return float(beats[i]) if i < len(beats) else float(beats[-1] + (i - len(beats) + 1) * period)

        count = (len(beats) - first_beat) // beats_per_bar if n_bars is None else n_bars
        bars = []
        for b in range(count):
            b0 = first_beat + b * beats_per_bar
            slots = [
                beat(b0 + q // 4) + (q % 4) * (beat(b0 + q // 4 + 1) - beat(b0 + q // 4)) / 4
                for q in range(beats_per_bar * 4)
            ]
            bars.append(np.array(slots))
        return cls(bars, beats_per_bar)

    @property
    def sixteenth(self) -> float:
        return float(np.median(np.diff(self.bars[0]))) if self.bars else 0.125

    def shifted(self, seconds: float) -> Grid:
        return Grid([b + seconds for b in self.bars], self.beats_per_bar)


@dataclass(frozen=True)
class Groove:
    kick: list[float]  # share of bars with a hit on each slot
    snare: list[float]
    hat: list[float]
    agreement: dict[str, float]  # share of slots matching the main groove, per instrument
    bars: int


@dataclass(frozen=True)
class BassNote:
    midi: int
    confidence: float


@dataclass(frozen=True)
class VocalRange:
    low: int  # MIDI, 10th percentile of sung notes: the usual range, not the extremes
    high: int  # MIDI, 90th percentile
    voiced_share: float


def _onsets(y: Audio, hop: int = HOP) -> tuple[Floats, Floats]:
    env = librosa.onset.onset_strength(y=y, sr=SR, hop_length=hop)
    return np.asarray(env, dtype=np.float64), librosa.times_like(env, sr=SR, hop_length=hop)


def _peak(env: Floats, times: Floats, t: float, before: float = 0.03, after: float = 0.03) -> float:
    m = (times >= t - before) & (times <= t + after)
    return float(np.max(env[m])) if m.any() else 0.0


def drum_grid_shift(drums: Audio, beats: Floats) -> float:
    """Median offset of the strong drum hits from the beat grid: trackers often lag by tens of ms."""
    env, _ = _onsets(drums)
    onsets = librosa.onset.onset_detect(onset_envelope=env, sr=SR, hop_length=HOP, units="time")
    frames = librosa.time_to_frames(onsets, sr=SR, hop_length=HOP)
    strong = [o for o, f in zip(onsets, frames, strict=True) if env[min(f, len(env) - 1)] > np.percentile(env, 95)]
    period = float(np.median(np.diff(beats)))
    offsets = [o - beats[int(np.argmin(np.abs(beats - o)))] for o in strong]
    offsets = [d for d in offsets if abs(d) < period / 3]
    return float(np.median(offsets)) if len(offsets) >= 10 else 0.0


def drum_groove(drums: Audio, grid: Grid) -> Groove | None:
    """Kick, snare and hi-hat per sixteenth, as the share of bars where each slot is hit."""
    if float(np.sqrt(np.mean(drums**2))) < 1e-3 or len(grid.bars) < 4:
        return None
    power = np.abs(librosa.stft(drums, n_fft=1024, hop_length=HOP)) ** 2
    freqs = librosa.fft_frequencies(sr=SR, n_fft=1024)
    times = librosa.frames_to_time(np.arange(power.shape[1]), sr=SR, hop_length=HOP)

    def band(lo: float, hi: float) -> Floats:
        # Linear energy: a log scale lets the snare's faint low end look like a kick.
        energy = np.sqrt(power[(freqs >= lo) & (freqs < hi)].sum(axis=0))
        return np.asarray(np.maximum(0, np.diff(energy, prepend=energy[0])), dtype=np.float64)

    def hits(curve: Floats) -> Floats:
        m = np.array([[_peak(curve, times, t, 0.025, 0.035) for t in bar] for bar in grid.bars])
        return np.asarray(m / (np.percentile(m, 95) + 1e-9), dtype=np.float64)

    low, mid, high = hits(band(30, 110)), hits(band(180, 600)), hits(band(7000, 11000))
    kick = low > 0.5
    # A snare has body (mids) and wires (highs); with the kick it can also land on the same slot.
    snare = ((mid > 0.3) & (high > 0.7) & (low < 0.5)) | ((mid > 0.6) & (high > 0.5) & (mid > 0.8 * low))
    hat = high > 0.2
    # Bars where the drums actually play: drums often come in late (Let It Be).
    loudness = np.array(
        [float(np.sqrt(np.mean(drums[int(b[0] * SR) : int((b[-1] + grid.sixteenth) * SR)] ** 2))) for b in grid.bars]
    )
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
    env, times = _onsets(other)
    m = np.array([[_peak(env, times, t) for t in bar] for bar in grid.bars])
    return [round(float(x), 2) for x in (m > 0.5 * np.percentile(m, 95)).mean(0)]


def voicings(other: Audio, grid: Grid, threshold: float = 0.62) -> list[list[int]]:
    """Pitch classes sounding in each bar on the chord instruments, strongest first (up to four)."""
    chroma = librosa.feature.chroma_cqt(y=librosa.effects.harmonic(other, margin=4), sr=SR, hop_length=512)
    out = []
    for bar in grid.bars:
        a, b = librosa.time_to_frames([bar[0], bar[-1] + grid.sixteenth], sr=SR, hop_length=512)
        v = np.median(chroma[:, a : max(int(b), int(a) + 1)], axis=1)
        v = v / (v.max() + 1e-9)
        out.append([int(i) for i in np.argsort(-v) if v[i] > threshold][:4])
    return out


def vocal_range(vocals: Audio, min_share: float = 0.15) -> VocalRange | None:
    """Range of the sung notes, or None when the track is mostly silent.

    Measured note by note (median pitch of each sustained note), so attacks and slides do not
    widen the range.
    """
    # Up to F6 (1400 Hz): with a lower ceiling, high soprano notes are read an octave down.
    f0, voiced, _ = librosa.pyin(vocals, fmin=80, fmax=1400, sr=SR, frame_length=2048, hop_length=HOP)
    share = float(np.mean(voiced))
    if share <= min_share:
        return None
    midi = librosa.hz_to_midi(f0)
    notes, start = [], None
    for i, v in enumerate([*voiced, False]):
        if v and start is None:
            start = i
        elif not v and start is not None:
            if i - start >= 3:
                notes.append(float(np.nanmedian(midi[start:i])))
            start = None
    if not notes:
        return None
    return VocalRange(int(np.round(np.percentile(notes, 10))), int(np.round(np.percentile(notes, 90))), round(share, 2))
