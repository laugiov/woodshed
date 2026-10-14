"""Regenerate the engine golden file for the installed librosa version.

    uv run python -m tests.golden.regenerate

Each (librosa, numpy) pair gets its own entry: chroma and beat tracking change slightly between
releases, so exact labels are only comparable within one environment. Run it with each Python
of the lock (`UV_PROJECT_ENVIRONMENT=.venvs/py310 uv run --python 3.10 ...`). Review the diff before
committing: an unexpected change in the labels is a behaviour change of the engine.
The "reference" entry is never regenerated: these are the labels of the original implementation
(librosa 1.0.0), which every environment must match in accuracy.
"""

from __future__ import annotations

import json
import tempfile
from importlib.metadata import version
from pathlib import Path
from typing import Any

from tests import synth
from woodshed.engine import detect

GOLDEN = Path(__file__).parent / "engine.json"


def environment() -> str:
    """The versions the labels depend on: librosa, and numpy underneath it."""
    return f"librosa {version('librosa')}, numpy {version('numpy')}"


def entry() -> dict[str, Any]:
    songs: dict[str, Any] = {}
    with tempfile.TemporaryDirectory() as tmp:
        for name, spec in synth.SONGS.items():
            wav = synth.write(name, Path(tmp)).wav
            res = detect(wav, sevenths=False, beats_per_bar=spec.beats_per_bar)
            res7 = detect(wav, sevenths=True, beats_per_bar=spec.beats_per_bar)
            songs[name] = {
                "labels": res.labels,
                "starts": [round(float(t), 4) for t in res.beat_times],
                "key": res.key_name,
                "offset": res.offset,
                "labels7": res7.labels,
                "doubtful": [bool(x) for x in res.doubtful],
            }
    return songs


def dump(data: dict[str, Any]) -> str:
    """Sorted JSON with one line per song and field, so a diff shows which song changed."""

    def block(value: Any, depth: int) -> str:
        if depth == 3 or not isinstance(value, dict):  # a song's fields: one line each
            return json.dumps(value)
        pad = "  " * (depth + 1)
        items = [f"{pad}{json.dumps(k)}: {block(v, depth + 1)}" for k, v in sorted(value.items())]
        return "{\n" + ",\n".join(items) + "\n" + "  " * depth + "}"

    return block(data, 0) + "\n"


def main() -> None:
    data = json.loads(GOLDEN.read_text()) if GOLDEN.exists() else {"environments": {}}
    data["environments"][environment()] = entry()
    GOLDEN.write_text(dump(data))
    print(f"wrote the {environment()} entry to {GOLDEN}")


if __name__ == "__main__":
    main()
