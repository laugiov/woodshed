"""The repository hygiene guard must reject anything that cannot go into a public repository."""

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_repo.py"
spec = importlib.util.spec_from_file_location("check_repo", SCRIPT)
assert spec and spec.loader
check_repo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check_repo)


def write(root: Path, rel: str, data: bytes = b"x") -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def problems(root: Path) -> list[str]:
    return check_repo.check(root, check_repo.list_files(root))


def test_clean_tree_passes(tmp_path: Path) -> None:
    write(tmp_path, "src/pkg/__init__.py", b"VERSION = '1'\n")
    write(tmp_path, "README.md", b"# hello\n")
    assert problems(tmp_path) == []


@pytest.mark.parametrize("name", ["song.wav", "a/b/track.MP3", "clip.mp4", "x.flac", "voice.opus", "loop.m4a"])
def test_audio_and_video_files_are_rejected(tmp_path: Path, name: str) -> None:
    write(tmp_path, name)
    assert any("audio or video" in p for p in problems(tmp_path))


def test_large_files_are_rejected(tmp_path: Path) -> None:
    write(tmp_path, "data/big.bin", b"0" * (1024 * 1024 + 1))
    assert any("larger than 1 MB" in p for p in problems(tmp_path))


def test_private_folder_is_rejected(tmp_path: Path) -> None:
    write(tmp_path, "private/notes.md", b"secret\n")
    assert any("private/" in p for p in problems(tmp_path))


@pytest.mark.parametrize("text", ["/home/alice/music", "/Users/bob/Desktop", "C:\\Users\\carol\\x"])
def test_absolute_home_paths_are_rejected(tmp_path: Path, text: str) -> None:
    write(tmp_path, "notes.md", f"see {text}\n".encode())
    assert any("home path" in p for p in problems(tmp_path))


def test_vendored_assets_need_a_licence(tmp_path: Path) -> None:
    write(tmp_path, "src/woodshed/page/assets/vendor/lib.js", b"x")
    assert any("licence" in p for p in problems(tmp_path))
    write(tmp_path, "src/woodshed/page/assets/vendor/LICENSE.txt", b"MIT")
    assert not any("licence" in p for p in problems(tmp_path))


def test_ignored_files_are_not_listed(tmp_path: Path) -> None:
    write(tmp_path, ".gitignore", b"*.wav\nprivate/\n.venv/\n")
    write(tmp_path, "private/song.wav")
    write(tmp_path, ".venv/lib/x.py")
    write(tmp_path, "keep.py")
    assert sorted(check_repo.list_files(tmp_path)) == [".gitignore", "keep.py"]
