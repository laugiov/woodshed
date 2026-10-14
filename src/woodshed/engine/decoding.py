"""Chord decoding: template scores, repetition averaging, key prior and a bar-aware Viterbi."""

from __future__ import annotations

from dataclasses import dataclass, field

import librosa
import numpy as np
import numpy.typing as npt

from woodshed.engine.features import Features

Floats = npt.NDArray[np.float64]
Ints = npt.NDArray[np.int64]
Bools = npt.NDArray[np.bool_]

NOTES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
TRIADS = {"": (0, 4, 7), "m": (0, 3, 7)}
SEVENTHS = {"7": (0, 4, 7, 10), "m7": (0, 3, 7, 10)}
SILENCE_DB = -20.0
KK_MAJOR = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
KK_MINOR = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])


@dataclass(frozen=True)
class Config:
    bass_weight: float = 0.2  # bass (root evidence) against treble (chord colour)
    repeat_k: int = 4  # similar passages averaged per beat (0 disables)
    repeat_mix: float = 0.6  # share of the averaged chroma
    key_bonus: float = 0.03  # bonus for chords in the key
    seventh_weight: float = 0.6  # weight of the seventh in 7 and m7 templates
    seventh_penalty: float = 0.03  # a seventh chord must beat its triad
    sharpness: float = 25.0  # contrast of observation probabilities
    change_downbeat: float = 0.5  # probability of a chord change on beat one
    change_halfbar: float = 0.10  # ... at the half bar
    change_other: float = 0.02  # ... anywhere else


@dataclass(frozen=True)
class Decoded:
    labels: list[str]
    beat_times: Floats
    tempo: float
    tuning: float
    key_pc: int
    key_mode: str  # "maj" or "min"
    phase: int  # beat index residue of beat one
    offset: int  # beats to pad before the first beat so that bars start on beat one
    doubtful: Bools
    fit: Floats  # per beat, cosine fit of the chosen chord to the treble
    energy_db: Floats
    scores: Floats = field(repr=False)  # (n_chords, n_beats)
    names: list[str] = field(repr=False)

    @property
    def key_name(self) -> str:
        return NOTES[self.key_pc] + ("" if self.key_mode == "maj" else "m")


def build_chords(sevenths: bool, cfg: Config) -> tuple[list[str], Ints, list[str], Floats]:
    """Chord names, roots, qualities and unit-norm chroma templates."""
    qualities: dict[str, tuple[int, ...]] = dict(TRIADS)
    if sevenths:
        qualities.update(SEVENTHS)
    names, roots, quals, templates = [], [], [], []
    for root in range(12):
        for suffix, intervals in qualities.items():
            t = np.zeros(12)
            for k, i in enumerate(intervals):
                t[(root + i) % 12] = cfg.seventh_weight if k == 3 else 1.0
            templates.append(t / np.linalg.norm(t))
            names.append(NOTES[root] + suffix)
            roots.append(root)
            quals.append(suffix)
    return names, np.array(roots), quals, np.array(templates)


def unit(x: Floats) -> Floats:
    return np.asarray(x / (np.linalg.norm(x, axis=0, keepdims=True) + 1e-9))


def smooth_repeats(treble: Floats, bass: Floats, k: int, mix: float) -> tuple[Floats, Floats]:
    """Average each beat with the most similar beats elsewhere in the song."""
    if k <= 0 or treble.shape[1] < 4 * (k + 1):
        return treble, bass
    feats = np.vstack([unit(treble), unit(bass)])
    # Four-beat context: compare fragments of bars, not isolated beats.
    stacked = librosa.feature.stack_memory(feats, n_steps=4, mode="edge")
    rec = librosa.segment.recurrence_matrix(stacked, k=k, metric="cosine", mode="affinity", width=3, sym=True)
    t_rep = librosa.decompose.nn_filter(treble, rec=rec, aggregate=np.average)
    b_rep = librosa.decompose.nn_filter(bass, rec=rec, aggregate=np.average)
    has = rec.sum(axis=0) > 0
    return np.where(has, (1 - mix) * treble + mix * t_rep, treble), np.where(has, (1 - mix) * bass + mix * b_rep, bass)


def key_chords(tonic: int, mode: str, strict: bool = False) -> set[tuple[int, str]]:
    """Chords expected in a key. Outside strict mode, the major dominant of the minor mode is added."""
    major = tonic if mode == "maj" else (tonic + 3) % 12
    minor = (major + 9) % 12
    expected = {
        (major, ""), ((major + 2) % 12, "m"), ((major + 4) % 12, "m"), ((major + 5) % 12, ""),
        ((major + 7) % 12, ""), (minor, "m"), ((major + 2) % 12, "m7"), ((major + 4) % 12, "m7"),
        ((major + 7) % 12, "7"), (minor, "m7"),
    }  # fmt: skip
    if not strict:
        expected |= {((minor + 7) % 12, ""), ((minor + 7) % 12, "7")}
    return expected


def estimate_key(
    states: Ints, roots: Ints, quals: list[str], treble: Floats, bass: Floats, voiced: Bools
) -> tuple[int, str]:
    """Key holding the most chords of a first pass; Krumhansl profiles pick major or relative minor."""
    picked = [(int(roots[s]), quals[s]) for s in states if s >= 0]
    counts = [sum(c in key_chords(major, "maj", strict=True) for c in picked) for major in range(12)]
    major = int(np.argmax(counts))
    minor = (major + 9) % 12
    prof = (unit(treble[:, voiced]) + unit(bass[:, voiced])).sum(axis=1)
    r_major = np.corrcoef(prof, np.roll(KK_MAJOR, major))[0, 1]
    r_minor = np.corrcoef(prof, np.roll(KK_MINOR, minor))[0, 1]
    return (major, "maj") if r_major >= r_minor else (minor, "min")


def viterbi(log_obs: Floats, log_stay: Floats, log_move: Floats) -> Ints:
    """Viterbi where the probability of keeping the same chord depends on the beat."""
    n_states, n_steps = log_obs.shape
    score = log_obs[:, 0].copy()
    back = np.zeros((n_states, n_steps), dtype=np.int64)
    for t in range(1, n_steps):
        best = int(np.argmax(score))
        stay = score + log_stay[t]
        move = score[best] + log_move[t]
        back[:, t] = np.where(stay >= move, np.arange(n_states), best)
        score = np.maximum(stay, move) + log_obs[:, t]
    path = [int(np.argmax(score))]
    for t in range(n_steps - 1, 0, -1):
        path.append(int(back[path[-1], t]))
    return np.array(path[::-1], dtype=np.int64)


def change_probs(n_steps: int, beats_per_bar: int, phase: int, cfg: Config) -> Floats:
    """Probability of a chord change on each beat, from its place in the bar."""
    pos = (np.arange(n_steps) - phase) % beats_per_bar
    p = np.full(n_steps, cfg.change_other)
    if beats_per_bar % 2 == 0:
        p[pos == beats_per_bar // 2] = cfg.change_halfbar
    p[pos == 0] = cfg.change_downbeat
    return p


def best_phase(states: Ints, beats_per_bar: int) -> int:
    """Beat-one position that puts the most chord changes on bar lines."""
    changes = np.flatnonzero(np.diff(states) != 0) + 1
    if len(changes) == 0:
        return 0
    return int(np.argmax(np.bincount(changes % beats_per_bar, minlength=beats_per_bar)))


def doubtful_beats(labels: list[str], beats_per_bar: int, phase: int) -> Bools:
    """Beats of doubtful chords: starting off a bar line or half bar, or lasting a single beat."""
    n = len(labels)

    def on_grid(i: int) -> bool:
        pos = (i - phase) % beats_per_bar
        return pos == 0 or (beats_per_bar % 2 == 0 and pos == beats_per_bar // 2)

    flags = np.zeros(n, dtype=bool)
    start = 0
    for i in range(1, n + 1):
        if i == n or labels[i] != labels[start]:
            after_silence = start > 0 and labels[start - 1] == "N"
            off_grid = start > 0 and not after_silence and not on_grid(start)
            if labels[start] != "N" and (i - start == 1 or off_grid):
                flags[start:i] = True
            start = i
    return flags


def decode(
    feat: Features, sevenths: bool, beats_per_bar: int, cfg: Config | None = None, phase: int | None = None
) -> Decoded:
    cfg = cfg or Config()
    names, roots, quals, templates = build_chords(sevenths, cfg)
    silent = feat.energy_db < SILENCE_DB

    treble, bass = smooth_repeats(feat.treble, feat.bass, cfg.repeat_k, cfg.repeat_mix)
    treble_u = unit(treble)
    # Bass scaled to [0, 1] per beat and weighted by its clarity: a missing or blurred bass
    # (kick drum, noise) has a flat profile and barely counts.
    peak = bass.max(axis=0, keepdims=True) + 1e-9
    clarity = 1 - bass.mean(axis=0, keepdims=True) / peak
    bass_n = bass / peak * clarity

    fit = templates @ treble_u
    score = fit + cfg.bass_weight * bass_n[roots]
    score -= cfg.seventh_penalty * np.array([len(q) > 0 and q != "m" for q in quals])[:, None]

    def run(sc: Floats, fixed_phase: int | None) -> tuple[Ints, int]:
        # State N (no chord) is forced on silent beats and forbidden elsewhere.
        log_obs = cfg.sharpness * sc
        log_obs = log_obs - log_obs.max(axis=0, keepdims=True)
        log_obs[:, silent] = -1e3
        log_obs = np.vstack([log_obs, np.where(silent, 0.0, -1e3)])
        n_steps, n = log_obs.shape[1], sc.shape[0]
        ph = fixed_phase or 0
        for _ in range(0 if fixed_phase is not None else 2):
            p = change_probs(n_steps, beats_per_bar, ph, cfg)
            ph = best_phase(viterbi(log_obs, np.log(1 - p), np.log(p / n)), beats_per_bar)
        p = change_probs(n_steps, beats_per_bar, ph, cfg)
        states = viterbi(log_obs, np.log(1 - p), np.log(p / n))
        return np.where(states == n, -1, states), ph

    # A first pass on triads only, with no prior, sets the key and the bar phase: they must not
    # depend on the chosen chord vocabulary.
    triads = np.flatnonzero([q in TRIADS for q in quals])
    first, ph = run(score[triads], phase)
    first = np.where(first >= 0, triads[np.maximum(first, 0)], -1)
    voiced = ~silent if (~silent).any() else np.ones_like(silent)
    tonic, mode = estimate_key(first, roots, quals, treble, bass, voiced)
    in_key = key_chords(tonic, mode)
    bonus = np.array([(int(r), q) in in_key for r, q in zip(roots, quals, strict=True)])[:, None]
    score = score + cfg.key_bonus * bonus
    states, _ = run(score, ph)
    labels_all = [*names, "N"]
    states = np.where(states < 0, len(names), states)
    labels = [labels_all[s] for s in states]
    n_steps = len(states)
    chosen_fit = np.array([fit[s, i] if s < len(names) else np.nan for i, s in enumerate(states)])
    return Decoded(
        labels=labels,
        beat_times=feat.beat_times[:n_steps],
        tempo=feat.tempo,
        tuning=feat.tuning,
        key_pc=tonic,
        key_mode=mode,
        phase=ph,
        offset=(-ph) % beats_per_bar,
        doubtful=doubtful_beats(labels, beats_per_bar, ph),
        fit=chosen_fit,
        energy_db=feat.energy_db[:n_steps],
        scores=score,
        names=names,
    )
