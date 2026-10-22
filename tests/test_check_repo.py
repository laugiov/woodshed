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
    found: list[str] = check_repo.check(root, check_repo.list_files(root))
    return found


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


@pytest.mark.parametrize(
    "text",
    [
        "/home/alice/music",
        "/Users/bob/Desktop",
        "C:\\Users\\carol\\x",
        "C:/Users/dan/x",
        "/root/x",
        "/var/home/eve/x",
        "file:///home/alice/x",
        "ssh://h/home/bob/y",
    ],
)
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


@pytest.mark.parametrize(
    "secret",
    [
        "AKIA" + "ABCDEFGHIJKLMNOP",
        "ghp_" + "a" * 36,
        "github_pat_" + "A" * 30,
        "xoxb-" + "1234567890-abc",
        "-----BEGIN OPENSSH " + "PRIVATE KEY-----",
    ],
)
def test_secrets_are_rejected(tmp_path: Path, secret: str) -> None:
    write(tmp_path, "config.toml", f"token = '{secret}'\n".encode())
    assert any("secret" in p for p in problems(tmp_path))


@pytest.mark.parametrize(
    "code",
    [
        'loadScript("https://cdn.example.org/lib.js")',
        "fetch('http://localhost:8000/x')",
        'src="//cdn.example.org/x.js"',
    ],
)
def test_page_code_must_not_reference_the_network(tmp_path: Path, code: str) -> None:
    write(tmp_path, "src/woodshed/page/assets/js/app.js", code.encode())
    assert any("network" in p for p in problems(tmp_path))


def test_page_code_may_use_relative_paths_and_comments(tmp_path: Path) -> None:
    write(tmp_path, "src/woodshed/page/assets/js/app.js", b'loadScript("assets/vendor/lib.js"); // offline\n')
    write(tmp_path, "src/woodshed/page/body.html", b"<p>a // b</p>\n")
    assert problems(tmp_path) == []


def test_vendored_files_are_pinned_by_hash(tmp_path: Path) -> None:
    lib = write(tmp_path, "src/woodshed/page/assets/vendor/lib.js", b"v1")
    write(tmp_path, "src/woodshed/page/assets/vendor/LICENSE.txt", b"MIT")
    assert any("missing from" in p for p in problems(tmp_path))
    assert check_repo.main(["check_repo", str(tmp_path), "--pin-vendored"]) == 0
    lib.write_bytes(b"v1 with audio hidden in base64")
    assert any("differs from its hash" in p for p in problems(tmp_path))
    lib.unlink()
    assert any("not present" in p for p in problems(tmp_path))


@pytest.mark.parametrize(
    "text", ["src/root/x.py", "https://example.org/root/page", "docs/task-" + "management-and-planning-for-the-teams"]
)
def test_root_and_home_inside_other_paths_are_fine(tmp_path: Path, text: str) -> None:
    write(tmp_path, "notes.md", f"see {text}\n".encode())
    assert problems(tmp_path) == []


@pytest.mark.parametrize(
    "secret",
    [
        "hf_" + "a" * 34,
        "npm_" + "b" * 36,
        "sk-proj-" + "c" * 40,
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0In0.abcdefghijklmnop",
    ],
)
def test_more_token_formats_are_rejected(tmp_path: Path, secret: str) -> None:
    write(tmp_path, "config.toml", f"token = '{secret}'\n".encode())
    assert any("secret" in p for p in problems(tmp_path))


def test_svg_namespaces_are_not_network_references(tmp_path: Path) -> None:
    write(tmp_path, "src/woodshed/page/assets/js/app.js", b'createElementNS("http://www.w3.org/2000/svg", "svg")\n')
    assert problems(tmp_path) == []


@pytest.mark.parametrize("code", ['fetch("HTTPS://cdn.example.org/x")', 'new WebSocket("wss://example.org/live")'])
def test_upper_case_and_websocket_urls_are_caught(tmp_path: Path, code: str) -> None:
    write(tmp_path, "src/woodshed/page/assets/js/app.js", code.encode())
    assert any("network" in p for p in problems(tmp_path))


def test_each_font_family_needs_its_own_licence(tmp_path: Path) -> None:
    fonts = "src/woodshed/page/assets/fonts"
    write(tmp_path, f"{fonts}/Barlow-500-latin.woff2", b"font")
    write(tmp_path, f"{fonts}/OFL-barlow.txt", b"OFL")
    write(tmp_path, f"{fonts}/Inter-400-latin.woff2", b"font")
    write(tmp_path, f"{fonts}/Lora.woff2", b"font")  # no dash in the name
    found = problems(tmp_path)
    assert any("Inter-400-latin.woff2: no licence" in p for p in found)
    assert any("Lora.woff2: no licence file OFL-lora.txt" in p for p in found)
    assert not any("Barlow-500-latin.woff2: no licence" in p for p in found)


def test_the_git_listing_is_used_in_a_repository(tmp_path: Path) -> None:
    import shutil
    import subprocess

    if shutil.which("git") is None:
        pytest.skip("needs git")
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    write(tmp_path, ".gitignore", b"ignored.txt\n")
    write(tmp_path, "ignored.txt")
    write(tmp_path, "kept.py")
    write(tmp_path, "build/out.txt")  # git lists it; the fallback skips any build folder
    assert sorted(check_repo.list_files(tmp_path)) == [".gitignore", "build/out.txt", "kept.py"]


def test_the_demo_song_is_allowed_with_its_licence_and_pinned(tmp_path: Path) -> None:
    # A free-licence demo song may ship in demo/, like a vendored file: with its licence, pinned by hash.
    song = write(tmp_path, "demo/song.mp3", b"\xff\xfb" + b"0" * (2 * 1024 * 1024))
    found = problems(tmp_path)
    assert not any("audio or video" in p or "larger than 1 MB" in p for p in found)
    assert any("licence" in p for p in found)
    write(tmp_path, "demo/LICENSE.md", b"CC BY 4.0, by the artist\n")
    assert any("missing from" in p for p in problems(tmp_path))
    assert check_repo.main(["check_repo", str(tmp_path), "--pin-vendored"]) == 0
    assert problems(tmp_path) == []
    song.write_bytes(b"another recording")
    assert any("differs from its hash" in p for p in problems(tmp_path))


@pytest.mark.parametrize("name", ["songs/demo/song.mp3", "demos/song.mp3", "src/demo/song.wav"])
def test_audio_outside_the_demo_folder_is_still_rejected(tmp_path: Path, name: str) -> None:
    write(tmp_path, name)
    assert any("audio or video" in p for p in problems(tmp_path))


def test_the_musicxml_doctype_is_an_identifier_not_a_fetch(tmp_path: Path) -> None:
    dtd = '"http://www.musicxml.org/dtds/partwise.dtd"'
    write(tmp_path, "src/woodshed/page/assets/js/core/x.js", f"const doctype = {dtd};\n".encode())
    assert problems(tmp_path) == []
    near = ["other", "dtds/partwise.dtd.evil.com/x", "dtds/partwise.dtd?x=1", "dtds/partwise.dtd/../x"]
    for i, url in enumerate(near):
        code = f'fetch("http://www.musicxml.org/{url}")\n'
        write(tmp_path, f"src/woodshed/page/assets/js/core/y{i}.js", code.encode())
    assert sum("network" in p for p in problems(tmp_path)) == 4


def test_only_the_two_awake_videos_are_allowed_with_their_licence_and_pinned(tmp_path: Path) -> None:
    for name in ("awake.mp4", "awake.webm"):
        write(tmp_path, f"src/woodshed/page/assets/awake/{name}", b"\x00\x00\x00\x18ftypisom")
    found = problems(tmp_path)
    assert not any("audio or video" in p for p in found) and any("licence" in p for p in found)
    write(tmp_path, "src/woodshed/page/assets/awake/LICENSE.md", b"Black frames made by a script here\n")
    assert check_repo.main(["check_repo", str(tmp_path), "--pin-vendored"]) == 0
    assert problems(tmp_path) == []
    for other in ("src/woodshed/page/assets/awake/song.mp4", "src/woodshed/page/assets/awake/awake.flac"):
        write(tmp_path, other)
        assert any("audio or video" in p for p in problems(tmp_path)), other
        (tmp_path / other).unlink()
