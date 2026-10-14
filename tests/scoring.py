"""Frame-level chord scoring for tests, without extra dependencies."""

from __future__ import annotations

from collections.abc import Sequence

NOTES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
FLATS = {"Db": "C#", "Eb": "D#", "Gb": "F#", "Ab": "G#", "Bb": "A#"}


def triad(label: str | None) -> str:
    """Reduce a label to root plus major or minor ('N' for no chord)."""
    if not label or label in ("N", "X"):
        return "N"
    root = label[:2] if len(label) > 1 and label[1] in "#b" else label[:1]
    quality = label[len(root) :]
    minor = quality.startswith("m") and not quality.startswith("maj")
    return FLATS.get(root, root) + ("m" if minor else "")


def _at(spans: Sequence[tuple[float, float, str]], t: float) -> str | None:
    for a, b, c in spans:
        if a <= t < b:
            return c
    return None


def majmin_accuracy(
    starts: Sequence[float], labels: Sequence[str], truth: Sequence[tuple[float, float, str]], step: float = 0.02
) -> float:
    """Share of time, outside reference silence, where the estimate has the right triad."""
    period = (starts[-1] - starts[0]) / max(1, len(starts) - 1)
    est = [(a, b, c) for a, b, c in zip(starts, [*starts[1:], starts[-1] + period], labels, strict=True)]
    ok = total = 0
    t = 0.0
    end = truth[-1][1]
    while t < end:
        ref = triad(_at(truth, t))
        if ref != "N":
            total += 1
            ok += triad(_at(est, t)) == ref
        t += step
    return ok / max(total, 1)
