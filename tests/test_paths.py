"""The one tools folder: where the installers put woodshed's programs, where the singer's key finds Rubber Band
and what the uninstall removes from (spec 017 and 018)."""

from pathlib import Path

import pytest

from woodshed import paths, pitch, uninstall


def test_pitch_and_the_uninstall_share_one_tools_folder() -> None:
    assert pitch.tools_dir is paths.tools_dir and uninstall.tools_dir is paths.tools_dir


def test_the_tools_folder_per_system(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    home = tmp_path / "home"
    for name, value in {"HOME": home, "USERPROFILE": home, "LOCALAPPDATA": tmp_path / "Local"}.items():
        monkeypatch.setenv(name, str(value))
    monkeypatch.delenv("WOODSHED_TOOLS", raising=False)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    assert paths.tools_dir("darwin") == home / "Library" / "Application Support" / "woodshed" / "tools"
    assert paths.tools_dir("win32") == tmp_path / "Local" / "woodshed" / "tools"
    assert paths.tools_dir("linux") == home / ".local" / "share" / "woodshed" / "tools"
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    assert paths.tools_dir("linux") == tmp_path / "data" / "woodshed" / "tools"


@pytest.mark.parametrize("name", ["XDG_DATA_HOME", "LOCALAPPDATA"])
def test_a_relative_folder_setting_is_ignored(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, name: str) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.delenv("WOODSHED_TOOLS", raising=False)
    monkeypatch.setenv(name, "relative/folder")  # it would depend on where woodshed was started
    if name == "XDG_DATA_HOME":
        assert paths.tools_dir("linux") == home / ".local" / "share" / "woodshed" / "tools"
    else:
        assert paths.tools_dir("win32") == home / "AppData" / "Local" / "woodshed" / "tools"


def test_woodshed_tools_wins_and_a_tilde_is_the_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("WOODSHED_TOOLS", "~/my tools")
    for system in ("darwin", "win32", "linux"):
        assert paths.tools_dir(system) == tmp_path / "my tools"
