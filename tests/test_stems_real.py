"""The stems extra with the real libraries: Demucs, beat_this and their model downloads.

Run with `pytest -m stems` in an environment with the extra (CI job "stems", scripts/ci.sh).
The models download once into the woodshed cache; the offline tests use an empty cache.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from tests import synth
from woodshed import analysis, beats, stems
from woodshed.cache import cache_dir
from woodshed.errors import StemsError

MISSING = importlib.util.find_spec("demucs") is None or importlib.util.find_spec("beat_this") is None
# The stems CI job sets WOODSHED_REQUIRE_STEMS=1: there a missing extra is a failure, not a skip,
# so the job cannot go green without running anything.
REQUIRED = os.environ.get("WOODSHED_REQUIRE_STEMS") == "1"
pytestmark = [pytest.mark.stems, pytest.mark.skipif(MISSING and not REQUIRED, reason="needs the stems extra")]


@pytest.fixture(scope="module")
def pop(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return synth.write("pop", tmp_path_factory.mktemp("real")).wav


@pytest.fixture
def empty_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    folder = tmp_path / "empty-cache"
    monkeypatch.setenv("WOODSHED_CACHE", str(folder))
    return folder


def test_offline_separation_with_no_model_fails_clearly(pop: Path, empty_cache: Path) -> None:
    with pytest.raises(StemsError, match="--offline"):
        stems.separate(pop, offline=True)
    assert not (empty_cache / "models").exists() or not any((empty_cache / "models").rglob("*.th"))


def test_offline_beat_tracking_with_no_model_fails_clearly(pop: Path, empty_cache: Path) -> None:
    with pytest.raises(StemsError, match="--offline"):
        beats.track_beat_this(pop, offline=True)
    assert not any(empty_cache.rglob("*.ckpt"))


def test_real_beat_this_finds_the_beats_and_downbeats(pop: Path) -> None:
    found, downbeats = beats.track_beat_this(pop)
    truth = synth.render("pop")
    assert np.median(np.diff(found)) == pytest.approx(0.5, rel=0.03)
    hits = sum(np.min(np.abs(truth.downbeats - d)) < 0.07 for d in downbeats)
    assert hits >= 0.8 * len(truth.downbeats)


def test_real_separation_on_a_synthetic_song(pop: Path) -> None:
    result = stems.separate(pop)
    drums, rate = sf.read(result.paths["drums"], always_2d=True)
    truth = synth.render("pop").stems["drums"]
    assert abs(drums.shape[0] / rate - truth.size / synth.SR) < 0.05
    assert stems.separate(pop).from_cache


def test_the_full_analysis_with_stems(pop: Path) -> None:
    song = analysis.analyze(pop, use_stems=True)
    assert song.analysis.beats == "beat_this" and song.analysis.stems
    assert song.parts is not None and song.parts.groove is not None
    assert [g.label for g in song.structure.groups] == ["A"]


def test_offline_works_once_the_models_are_cached(tmp_path: Path) -> None:
    from demucs.api import Separator

    from woodshed.models import torch_models

    with torch_models(offline=False):  # make sure both models are in the cache
        Separator(model=stems.MODEL, device="cpu", progress=False)
    beats.track_beat_this(synth.write("pop", tmp_path / "warm").wav)

    waltz = synth.write("waltz", tmp_path).wav
    # Not separated yet, so Demucs must load its model (the entry is removed if a run left it).
    shutil.rmtree(cache_dir() / "stems" / f"{stems.MODEL}-{stems.fingerprint(waltz)}", ignore_errors=True)
    result = stems.separate(waltz, offline=True)
    assert not result.from_cache
    found, _ = beats.track_beat_this(waltz, offline=True)
    assert np.median(np.diff(found)) == pytest.approx(60 / 132, rel=0.03)
