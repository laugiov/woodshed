"""Command-line entry point basics."""

import subprocess
import sys

import pytest

import woodshed
from woodshed import cli


def test_version_flag_prints_the_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == f"woodshed {woodshed.__version__}"


def test_no_arguments_is_a_usage_error(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main([])
    assert exc.value.code == 2
    assert "usage" in capsys.readouterr().err.lower()


def test_module_entry_point_runs() -> None:
    out = subprocess.run([sys.executable, "-m", "woodshed", "--version"], capture_output=True, text=True, check=True)
    assert out.stdout.startswith("woodshed ")


def test_a_song_argument_is_refused_until_analysis_exists(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main(["song.mp3"])
    assert exc.value.code == 2
    assert "not implemented" in capsys.readouterr().err


def test_module_entry_point_in_process(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    import runpy

    monkeypatch.setattr(sys, "argv", ["woodshed", "--version"])
    with pytest.raises(SystemExit) as exc:
        runpy.run_module("woodshed", run_name="__main__")
    assert exc.value.code == 0
    assert capsys.readouterr().out.startswith("woodshed ")


def test_analyze_is_exported_without_loading_librosa_for_version() -> None:
    import subprocess
    import sys

    code = (
        "import sys, woodshed; assert 'librosa' not in sys.modules; woodshed.analyze; assert 'librosa' in sys.modules"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


def test_reading_a_song_does_not_load_the_audio_libraries() -> None:
    import subprocess
    import sys

    code = (
        "import sys; import woodshed.song, woodshed.model, woodshed.theory; "
        "loaded = {'librosa', 'numba', 'soundfile', 'scipy'} & set(sys.modules); assert not loaded, loaded"
    )
    subprocess.run([sys.executable, "-c", code], check=True)
