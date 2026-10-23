"""woodshed uninstall in a fake home: what it removes, what it keeps (the songs above all), when it refuses.

Nothing here touches the real home: HOME, LOCALAPPDATA, APPDATA, XDG_*, WOODSHED_CACHE and WOODSHED_TOOLS
point into a temp folder, the uv tool environment is a fake one, the process list is given and the port
probed is a free one (or one a fake woodshed answers on)."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import socket
import sys
import threading
from collections.abc import Iterator
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from woodshed import cli, paths, uninstall

APP_ID = "io.github.laugiov.woodshed"


@dataclass
class Home:
    root: Path  # everything below is inside it
    home: Path
    library: Path
    cache: Path
    tools: Path
    local: Path  # LOCALAPPDATA
    roaming: Path  # APPDATA
    data: Path  # XDG_DATA_HOME
    deleted_keys: list[str]

    def files(self) -> set[Path]:
        """Every path under the fake root (links not followed)."""
        found: set[Path] = set()
        for folder, dirs, names in os.walk(self.root):
            found.update(Path(folder) / n for n in [*dirs, *names])
        return found


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture
def fake(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Home:
    home = tmp_path / "home"
    h = Home(
        root=tmp_path, home=home, library=home / "woodshed", cache=tmp_path / "cache", tools=tmp_path / "tools",
        local=home / "AppData" / "Local", roaming=home / "AppData" / "Roaming", data=home / ".local" / "share",
        deleted_keys=[],
    )  # fmt: skip
    for folder in (h.home, h.library, h.local, h.roaming, h.data):
        folder.mkdir(parents=True, exist_ok=True)
    (h.library / "Same Boat.mp3").write_bytes(b"song")
    (h.library / "Same Boat.woodshed").mkdir()
    (h.library / "Same Boat.woodshed" / "index.html").write_text("page", encoding="utf-8")
    env = {
        "HOME": h.home, "USERPROFILE": h.home, "LOCALAPPDATA": h.local, "APPDATA": h.roaming,
        "XDG_DATA_HOME": h.data, "XDG_CACHE_HOME": h.home / ".cache", "WOODSHED_CACHE": h.cache,
        "WOODSHED_TOOLS": h.tools,
    }  # fmt: skip
    for name, value in env.items():
        monkeypatch.setenv(name, str(value))
    monkeypatch.delenv("WOODSHED_CONTAINER", raising=False)
    # A uv tool environment, as `uv tool install` leaves it.
    prefix = tmp_path / "uv-tools" / "woodshed"
    prefix.mkdir(parents=True)
    (prefix / "uv-receipt.toml").write_text("[tool]\n", encoding="utf-8")
    monkeypatch.setattr(uninstall, "_prefix", lambda: prefix)
    monkeypatch.setattr(uninstall, "_processes", lambda: [])
    monkeypatch.setattr(uninstall, "PORT", free_port())
    monkeypatch.setattr(uninstall, "_delete_key", h.deleted_keys.append)
    # The pinned Rubber Band files, as fill_tools writes them (the real ones are a few MB of program).
    monkeypatch.setattr(paths, "RUBBER_BAND_SHA256", {name: TOOL_SHA for name in paths.RUBBER_BAND_SHA256})
    return h


TOOL = b"tool"
TOOL_SHA = hashlib.sha256(TOOL).hexdigest()
SCRIPT = b"#!/bin/sh\n# Made by the woodshed installer: removes woodshed from this computer\n"


def fill_cache(h: Home) -> None:
    (h.cache / "stems" / "htdemucs_6s-abc").mkdir(parents=True)
    (h.cache / "stems" / "htdemucs_6s-abc" / "vocals.flac").write_bytes(b"x" * 10)
    (h.cache / "models").mkdir()
    (h.cache / "models" / "htdemucs_6s.th").write_bytes(b"m")


def fill_tools(h: Home, *names: str, folder: Path | None = None) -> None:
    """Woodshed's own files: the Rubber Band ones as pinned, the uninstall scripts as the installers write them."""
    folder = folder or h.tools
    folder.mkdir(parents=True, exist_ok=True)
    for name in names or ("rubberband",):
        (folder / name).write_bytes(SCRIPT if name.startswith("uninstall-woodshed") else TOOL)


def user_named(h: Home) -> set[Path]:
    """The folders WOODSHED_CACHE and WOODSHED_TOOLS name: the user's, they stay even once emptied."""
    return {h.cache, h.tools}


def mac_app(apps: Path, name: str, bundle_id: str = APP_ID) -> Path:
    app = apps / name
    (app / "Contents" / "MacOS").mkdir(parents=True)
    (app / "Contents" / "Info.plist").write_text(f"<string>{bundle_id}</string>", encoding="utf-8")
    (app / "Contents" / "MacOS" / "woodshed").write_text("#!/bin/sh", encoding="utf-8")
    return app


def below(*paths: Path) -> set[Path]:
    """The paths and everything inside them."""
    found = set(paths)
    for p in paths:
        if p.is_dir() and not p.is_symlink():
            found.update(p.rglob("*"))
    return found


def run(monkeypatch: pytest.MonkeyPatch, system: str, *argv: str, answer: str | None = None) -> int:
    monkeypatch.setattr(uninstall, "_system", lambda: system)
    if answer is not None:
        monkeypatch.setattr("builtins.input", lambda _prompt="": answer)
    return uninstall.main(list(argv))


# What it removes, per system


def test_linux_removes_the_cache_tracks_the_tools_and_the_menu_entries_only(
    fake: Home, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fill_cache(fake)
    fill_tools(fake, "rubberband", "uninstall-woodshed.sh")
    apps = fake.data / "applications"
    apps.mkdir()
    menu = [apps / "woodshed.desktop", apps / "woodshed-uninstall.desktop"]
    menu[0].write_text('[Desktop Entry]\nName=woodshed\nExec="/opt/uv/bin/woodshed" app\n', encoding="utf-8")
    menu[1].write_text(f'[Desktop Entry]\nExec=sh "{fake.tools}/uninstall-woodshed.sh"\n', encoding="utf-8")
    (apps / "other.desktop").write_text("[Desktop Entry]\nName=Other\n", encoding="utf-8")
    before, expected = fake.files(), below(fake.cache, *menu, fake.tools) - user_named(fake)

    assert run(monkeypatch, "linux", "--yes") == 0

    assert before - fake.files() == expected
    assert (fake.library / "Same Boat.woodshed" / "index.html").read_text(encoding="utf-8") == "page"
    out = capsys.readouterr().out
    assert str(fake.library) in out  # said kept, by path
    assert "uv tool uninstall woodshed" in out  # the last step, typed by the musician


def test_mac_removes_both_apps_and_leaves_a_foreign_app(fake: Home, monkeypatch: pytest.MonkeyPatch) -> None:
    fill_cache(fake)
    apps = fake.home / "Applications"
    ours = [mac_app(apps, "woodshed.app"), mac_app(apps, "Uninstall woodshed.app", APP_ID + ".uninstall")]
    foreign = mac_app(apps, "Other.app", "com.example.other")
    before, expected = fake.files(), below(fake.cache, *ours) - user_named(fake)

    assert run(monkeypatch, "darwin", "--yes") == 0

    assert before - fake.files() == expected
    assert foreign.exists()


def test_windows_removes_the_shortcuts_the_tools_and_the_settings_entry_last(
    fake: Home, monkeypatch: pytest.MonkeyPatch
) -> None:
    fill_cache(fake)
    fill_tools(fake, "rubberband.exe", "uninstall-woodshed.cmd")
    programs = fake.roaming / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    programs.mkdir(parents=True)
    links = [programs / "woodshed.lnk", programs / "Uninstall woodshed.lnk"]
    links[0].write_bytes(b"L\0\0\0" + "C:\\bin\\woodshed.exe".encode("utf-16-le"))
    links[1].write_bytes(b"L\0\0\0" + "C:\\tools\\uninstall-woodshed.cmd".encode("utf-16-le"))
    (programs / "Other.lnk").write_bytes(b"L\0\0\0other")
    before, expected = fake.files(), below(fake.cache, *links, fake.tools) - user_named(fake)

    assert run(monkeypatch, "win32", "--yes") == 0

    assert before - fake.files() == expected
    assert fake.deleted_keys == [uninstall.UNINSTALL_KEY]


def test_keep_self_leaves_woodshed_its_running_script_and_the_settings_entry(
    fake: Home, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # The Start menu's .cmd runs "woodshed uninstall --keep-self", then uv, then deletes itself and the key.
    fill_tools(fake, "rubberband.exe", "uninstall-woodshed.cmd")
    before = fake.files()

    assert run(monkeypatch, "win32", "--yes", "--keep-self") == 0

    assert before - fake.files() == {fake.tools / "rubberband.exe"}
    assert fake.deleted_keys == []
    assert "uv tool uninstall woodshed" not in capsys.readouterr().out  # the shortcut runs it


def test_without_tools_or_cache_nothing_is_said_removed(
    fake: Home, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    before = fake.files()
    assert run(monkeypatch, "linux", "--yes") == 0
    assert fake.files() == before
    assert "Removed" not in capsys.readouterr().out


def test_the_default_tools_folder_and_its_empty_parent_go(fake: Home, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WOODSHED_TOOLS")
    tools = fake.data / "woodshed" / "tools"
    assert uninstall.tools_dir("linux") == tools
    tools.mkdir(parents=True)
    (tools / "rubberband").write_text("tool", encoding="utf-8")
    assert run(monkeypatch, "linux", "--yes") == 0
    assert not (fake.data / "woodshed").exists()
    assert fake.data.is_dir()


def test_tools_folder_per_system(fake: Home, monkeypatch: pytest.MonkeyPatch) -> None:
    assert uninstall.tools_dir("linux") == fake.tools  # WOODSHED_TOOLS wins
    monkeypatch.delenv("WOODSHED_TOOLS")
    assert uninstall.tools_dir("win32") == fake.local / "woodshed" / "tools"
    assert uninstall.tools_dir("darwin") == fake.home / "Library" / "Application Support" / "woodshed" / "tools"
    monkeypatch.setenv("XDG_DATA_HOME", "relative/data")  # the XDG spec ignores a relative value
    assert uninstall.tools_dir("linux") == fake.home / ".local" / "share" / "woodshed" / "tools"


# What it never touches


def test_a_foreign_file_in_the_cache_folder_stays(fake: Home, monkeypatch: pytest.MonkeyPatch) -> None:
    fill_cache(fake)
    notes = fake.cache / "my notes.txt"
    notes.write_text("mine", encoding="utf-8")
    assert run(monkeypatch, "linux", "--yes") == 0
    assert notes.read_text(encoding="utf-8") == "mine"
    assert not (fake.cache / "stems").exists() and not (fake.cache / "models").exists()


def test_a_shortcut_named_like_ours_but_not_ours_stays(fake: Home, monkeypatch: pytest.MonkeyPatch) -> None:
    apps = fake.data / "applications"
    apps.mkdir()
    (apps / "woodshed.desktop").write_text("[Desktop Entry]\nName=woodshed notes\nExec=gedit notes\n", encoding="utf-8")
    (apps / "woodshed-uninstall.desktop").write_text("[Desktop Entry]\nExec=woodshed-cleaner\n", encoding="utf-8")
    programs = fake.roaming / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    programs.mkdir(parents=True)
    (programs / "woodshed.lnk").write_bytes("C:\\notes\\woodshed.txt".encode("utf-16-le"))
    before = fake.files()
    assert run(monkeypatch, "linux", "--yes") == 0
    assert run(monkeypatch, "win32", "--yes") == 0
    assert fake.files() == before


def test_a_foreign_file_in_the_tools_folder_stays(fake: Home, monkeypatch: pytest.MonkeyPatch) -> None:
    # WOODSHED_TOOLS set to a folder of the user's: only the files woodshed puts there go.
    documents = fake.home / "Documents"
    monkeypatch.setenv("WOODSHED_TOOLS", str(documents))
    (documents / "photos").mkdir(parents=True)
    (documents / "photos" / "band.jpg").write_bytes(b"jpg")
    (documents / "thesis.odt").write_bytes(b"odt")
    ours = [documents / n for n in ("rubberband", "COPYING", "uninstall-woodshed.sh")]
    fill_tools(fake, *(f.name for f in ours), folder=documents)
    before = fake.files()
    assert run(monkeypatch, "linux", "--yes") == 0
    assert before - fake.files() == set(ours)


def test_a_licence_file_alone_is_not_taken_for_rubber_bands(fake: Home, monkeypatch: pytest.MonkeyPatch) -> None:
    fill_tools(fake, "COPYING", "uninstall-woodshed.sh")  # a folder's own licence, no Rubber Band beside it
    assert run(monkeypatch, "linux", "--yes") == 0
    assert (fake.tools / "COPYING").exists() and not (fake.tools / "uninstall-woodshed.sh").exists()


def test_a_folder_named_like_a_tool_stays(fake: Home, monkeypatch: pytest.MonkeyPatch) -> None:
    (fake.tools / "rubberband").mkdir(parents=True)
    (fake.tools / "rubberband" / "song.wav").write_bytes(b"x")
    assert run(monkeypatch, "linux", "--yes") == 0
    assert (fake.tools / "rubberband" / "song.wav").exists()


def test_a_junction_is_removed_as_a_link(fake: Home, monkeypatch: pytest.MonkeyPatch) -> None:
    # A Windows junction (mklink /J) looks like a folder: what it points to must not be emptied.
    fill_cache(fake)
    stems = fake.cache / "stems"
    unlinked: list[Path] = []
    monkeypatch.setattr(uninstall, "_is_junction", lambda p: Path(p) == stems)
    monkeypatch.setattr(uninstall, "_remove_link", unlinked.append)
    assert run(monkeypatch, "win32", "--yes") == 0
    assert unlinked == [stems]
    assert (stems / "htdemucs_6s-abc" / "vocals.flac").exists()
    assert not (fake.cache / "models").exists()


def test_the_junction_test_reads_the_reparse_point_flag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class Stat:
        st_file_attributes = 0x400  # FILE_ATTRIBUTE_REPARSE_POINT
        st_mode = 0o040755

    monkeypatch.delattr(os.path, "isjunction", raising=False)  # Python before 3.12
    monkeypatch.setattr(os, "lstat", lambda _p: Stat())
    assert uninstall._is_junction(tmp_path) is True
    Stat.st_file_attributes = 0
    assert uninstall._is_junction(tmp_path) is False


def test_a_locked_file_stops_before_woodshed_itself(
    fake: Home, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fill_cache(fake)
    real = shutil.rmtree

    def locked(path: Path) -> None:
        if path.name == "stems":
            raise PermissionError(13, "The process cannot access the file", str(path))
        real(path)

    monkeypatch.setattr(shutil, "rmtree", locked)
    assert run(monkeypatch, "win32", "--yes") == 1
    assert (fake.cache / "stems").exists() and not (fake.cache / "models").exists()  # the others still go
    out = capsys.readouterr().out
    assert "Not removed" in out and "stems" in out and "cannot access" in out
    assert "uv tool uninstall" not in out
    assert fake.deleted_keys == []  # Settings > Apps keeps the entry, to try again


def test_a_linked_stems_folder_loses_the_link_only(
    fake: Home, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    elsewhere = fake.root / "big disk" / "stems"
    elsewhere.mkdir(parents=True)
    (elsewhere / "a.flac").write_bytes(b"x")
    fake.cache.mkdir()
    try:
        (fake.cache / "stems").symlink_to(elsewhere, target_is_directory=True)
    except OSError:  # Windows without the right to make links
        pytest.skip("links cannot be made here")
    tools_target = fake.root / "my tools"
    tools_target.mkdir()
    (tools_target / "rubberband").write_text("tool", encoding="utf-8")
    (tools_target / "mine.txt").write_text("mine", encoding="utf-8")
    fake.tools.symlink_to(tools_target, target_is_directory=True)

    assert run(monkeypatch, "linux", "--yes") == 0

    assert not os.path.lexists(fake.cache / "stems") and (elsewhere / "a.flac").exists()
    # The tools folder as a link: woodshed's files in it go, the link and the rest stay.
    assert fake.tools.is_symlink() and (tools_target / "mine.txt").exists()
    assert not (tools_target / "rubberband").exists()
    assert "link" in capsys.readouterr().out


@pytest.mark.parametrize("where", ["library in the cache", "cache in the library", "tools are the library"])
def test_refuses_when_the_library_and_a_removed_folder_overlap(
    fake: Home, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], where: str
) -> None:
    fill_cache(fake)
    if where == "library in the cache":
        monkeypatch.setenv("WOODSHED_CACHE", str(fake.home))  # ~/woodshed is inside
        (fake.home / "stems").mkdir()
    elif where == "cache in the library":
        monkeypatch.setenv("WOODSHED_CACHE", str(fake.library / "cache"))
        (fake.library / "cache" / "stems").mkdir(parents=True)
    else:
        monkeypatch.setenv("WOODSHED_TOOLS", str(fake.library))
    before = fake.files()
    assert run(monkeypatch, "linux", "--yes") == 1
    assert fake.files() == before
    assert "songs" in capsys.readouterr().err


def test_refuses_a_tools_folder_that_is_the_home(fake: Home, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WOODSHED_TOOLS", str(fake.home))
    monkeypatch.setattr(uninstall, "LIBRARY", fake.root / "elsewhere")
    before = fake.files()
    assert run(monkeypatch, "linux", "--yes") == 1
    assert fake.files() == before


# When it refuses


class FakeWoodshed(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        body = json.dumps({"token": "t"}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:
        pass


class QuietServer(ThreadingHTTPServer):
    """As woodshed's own server: a client gone mid-request is no error. The probe tries HTTPS first and hangs
    up on this plain server's 400, which then meets a closed connection now and then."""

    def handle_error(self, request: Any, client_address: Any) -> None:
        if isinstance(sys.exc_info()[1], ConnectionError):
            return
        super().handle_error(request, client_address)


@pytest.fixture
def woodshed_answering(fake: Home, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    server = QuietServer(("127.0.0.1", 0), FakeWoodshed)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(uninstall, "PORT", server.server_address[1])
    yield
    server.shutdown()
    server.server_close()


@pytest.mark.usefixtures("woodshed_answering")
def test_refuses_while_the_app_answers_on_its_port(
    fake: Home, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fill_cache(fake)
    before = fake.files()
    assert run(monkeypatch, "linux", "--yes") == 1
    assert fake.files() == before
    err = capsys.readouterr().err
    assert uninstall.RUNNING in err and not re.search(r"process \d", err)
    assert "close its Terminal window (Mac) or its black window (Windows), not only the browser tab" in err


def test_refuses_while_another_woodshed_process_runs(
    fake: Home, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fill_cache(fake)
    script = "/opt/uv/bin/woodshed"
    monkeypatch.setattr(uninstall, "_script", lambda: script)
    monkeypatch.setattr(uninstall, "_processes", lambda: [(4242, 1, f"/usr/bin/python3 {script} app")])
    before = fake.files()
    assert run(monkeypatch, "linux", "--yes") == 1
    assert fake.files() == before
    assert uninstall.RUNNING in capsys.readouterr().err


def test_an_unreadable_process_list_falls_back_to_the_port(
    fake: Home, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fill_cache(fake)
    monkeypatch.setattr(uninstall, "_processes", lambda: [])
    assert run(monkeypatch, "linux", "--yes") == 0
    assert capsys.readouterr().out.count("only checked woodshed's port") == 1


def test_itself_and_its_ancestors_do_not_count_as_running(fake: Home, monkeypatch: pytest.MonkeyPatch) -> None:
    fill_cache(fake)
    script = "/opt/uv/bin/woodshed"
    me, parent = os.getpid(), os.getppid()
    tree = [(me, parent, f"python3 {script} uninstall --keep-self"), (parent, 1, f"sh {script} uninstall")]
    others = [(4243, 1, f"python3 {script}-other app"), (4244, 1, "sh /x/uninstall.command")]
    monkeypatch.setattr(uninstall, "_script", lambda: script)
    monkeypatch.setattr(uninstall, "_processes", lambda: tree + others)
    assert run(monkeypatch, "linux", "--yes") == 0
    assert not (fake.cache / "stems").exists()


# The Start menu's uninstall on Windows, as GitHub's runner showed it: woodshed.exe (uv's launcher) starts the
# tool environment's python.exe, itself a launcher of uv's Python, so woodshed.exe is a grandparent of this one.
WINDOWS_TREE = [
    (100, 4, "pwsh.exe"),
    (200, 100, "cmd.exe"),  # uninstall-woodshed.cmd
    (300, 200, "woodshed.exe"),
    (400, 300, "python.exe"),  # the environment's launcher
    (500, 400, "python.exe"),  # this woodshed uninstall
]


def test_windows_does_not_count_its_own_launchers() -> None:
    assert uninstall.others_running(WINDOWS_TREE, "x", "win32", me=500) is False


def test_windows_counts_another_woodshed_program() -> None:
    app = [(600, 4, "explorer.exe"), (700, 600, "WOODSHED.EXE"), (800, 700, "python.exe")]
    assert uninstall.others_running(WINDOWS_TREE + app, "x", "win32", me=500) is True


def test_the_whole_chain_of_this_process_counts_as_itself() -> None:
    # The real parent and grandparent of this test run, then a woodshed above them: still this one's.
    me, parent = os.getpid(), os.getppid()
    tree = [(me, parent, "python.exe"), (parent, 77, "python.exe"), (77, 66, "woodshed.exe"), (66, 1, "cmd.exe")]
    assert uninstall.others_running(tree, "x", "win32") is False


def test_a_parent_loop_ends(fake: Home) -> None:
    # Windows reuses process ids: a dead parent's id can point back down the chain.
    loop = [(300, 500, "woodshed.exe"), (400, 300, "python.exe"), (500, 400, "python.exe")]
    assert uninstall.others_running(loop, "x", "win32", me=500) is False


def test_refuses_a_running_windows_woodshed(
    fake: Home, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(uninstall, "_processes", lambda: [*WINDOWS_TREE, (700, 4, "woodshed.exe")])
    monkeypatch.setattr(os, "getpid", lambda: 500)
    fill_cache(fake)
    assert run(monkeypatch, "win32", "--yes") == 1
    assert uninstall.RUNNING in capsys.readouterr().err


def test_refuses_in_docker(fake: Home, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    fill_cache(fake)
    monkeypatch.setenv("WOODSHED_CONTAINER", "1")
    before = fake.files()
    assert run(monkeypatch, "linux", "--yes") == 1
    assert fake.files() == before
    assert "docker" in capsys.readouterr().err.lower()


def test_refuses_outside_a_uv_tool_install(
    fake: Home, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fill_cache(fake)
    monkeypatch.setattr(uninstall, "_prefix", lambda: fake.root / "venv")  # pipx, a checkout's venv...
    before = fake.files()
    assert run(monkeypatch, "linux", "--yes") == 1
    assert fake.files() == before
    err = capsys.readouterr().err
    assert "uv tool" in err and str(fake.cache) in err  # the manual steps


# The question


@pytest.mark.parametrize("answer", ["n", "", "no", "maybe"])
def test_anything_but_yes_changes_nothing(
    fake: Home, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], answer: str
) -> None:
    fill_cache(fake)
    fill_tools(fake)
    before = fake.files()
    assert run(monkeypatch, "linux", answer=answer) == 1
    assert fake.files() == before
    out = capsys.readouterr().out
    assert "Nothing was removed" in out


def test_the_question_names_the_songs_and_yes_removes(
    fake: Home, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fill_cache(fake)
    asked: list[str] = []

    def answer(prompt: str = "") -> str:
        asked.append(prompt)
        return "y"

    monkeypatch.setattr(uninstall, "_system", lambda: "linux")
    monkeypatch.setattr("builtins.input", answer)
    assert uninstall.main([]) == 0
    assert asked == [uninstall.QUESTION]
    assert "Remove woodshed from this computer? Your songs stay where they are." in uninstall.QUESTION
    assert "Type y then Enter to remove it" in uninstall.QUESTION and uninstall.QUESTION.endswith("[y/N] ")
    assert not (fake.cache / "stems").exists()


@pytest.mark.parametrize("keep_self", [False, True])
def test_the_list_says_plainly_what_goes_and_what_stays(
    fake: Home, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], keep_self: bool
) -> None:
    fill_cache(fake)
    assert run(monkeypatch, "linux", "--yes", *(["--keep-self"] if keep_self else [])) == 0
    out = capsys.readouterr().out
    if keep_self:
        assert "woodshed itself (removed right after, in this window)" in out
    # uv's cache: what is cleaned, and what it means for other programs.
    assert "woodshed's big packages in uv's cache (torch, numpy...)" in out
    assert "other Python programs may download them again" in out
    assert "uv, a helper other programs may use" in out
    assert f"{fake.library} (a library kept somewhere else is not looked at, and stays too)" in out


def test_end_of_input_is_a_no(fake: Home, monkeypatch: pytest.MonkeyPatch) -> None:
    fill_cache(fake)

    def closed(_prompt: str = "") -> str:
        raise EOFError

    monkeypatch.setattr(uninstall, "_system", lambda: "linux")
    monkeypatch.setattr("builtins.input", closed)
    assert uninstall.main([]) == 1
    assert (fake.cache / "stems").exists()


# The command line


def test_the_cli_runs_it(fake: Home, monkeypatch: pytest.MonkeyPatch) -> None:
    fill_cache(fake)
    monkeypatch.setattr(uninstall, "_system", lambda: "linux")
    assert "uninstall" in cli.COMMANDS
    assert cli.main(["uninstall", "--yes"]) == 0
    assert not (fake.cache / "stems").exists()


def test_the_real_process_list_holds_this_process_and_its_parent() -> None:
    # ps on macOS and Linux, a Toolhelp snapshot on Windows (the CI's Windows jobs run this).
    procs = uninstall._processes()
    assert (os.getpid(), os.getppid()) in {(pid, ppid) for pid, ppid, _ in procs}
    assert len(uninstall._lineage(procs, os.getpid())) >= 2


def test_a_menu_entry_with_windows_line_endings_is_still_ours(fake: Home, monkeypatch: pytest.MonkeyPatch) -> None:
    apps = fake.data / "applications"
    apps.mkdir()
    entry = apps / "woodshed.desktop"
    entry.write_bytes(b'[Desktop Entry]\r\nName=woodshed\r\nExec="/opt/uv/bin/woodshed" app\r\n')
    assert run(monkeypatch, "linux", "--yes") == 0
    assert not entry.exists()


def test_rubber_band_and_its_licence_are_said_to_go(
    fake: Home, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fill_tools(fake, "rubberband", "COPYING", "uninstall-woodshed.sh")
    assert run(monkeypatch, "linux", "--yes") == 0
    out = capsys.readouterr().out
    assert "Rubber Band (the recording in your key) and its licence" in out
    assert fake.tools.is_dir() and not any(fake.tools.iterdir())  # the folder WOODSHED_TOOLS names stays


# Attacks from the adversarial review: a plausible setting must never cost the user a file.


def test_a_tools_link_to_the_home_is_refused(fake: Home, monkeypatch: pytest.MonkeyPatch) -> None:
    # WOODSHED_TOOLS=~/lnk, lnk -> ~: before, ~/rubberband and ~/COPYING were deleted.
    monkeypatch.setattr(uninstall, "LIBRARY", fake.root / "songs elsewhere")
    fill_tools(fake, "rubberband", "COPYING", folder=fake.home)
    link = fake.home / "lnk"
    try:
        link.symlink_to(fake.home, target_is_directory=True)
    except OSError:
        pytest.skip("links cannot be made here")
    monkeypatch.setenv("WOODSHED_TOOLS", str(link))
    before = fake.files()
    assert run(monkeypatch, "linux", "--yes") == 1
    assert fake.files() == before


def test_a_relative_tools_setting_is_ignored(fake: Home, monkeypatch: pytest.MonkeyPatch) -> None:
    # WOODSHED_TOOLS=music, run from the home: before, ~/music/rubberband was deleted.
    music = fake.home / "music"
    fill_tools(fake, "rubberband", "COPYING", folder=music)
    monkeypatch.chdir(fake.home)
    monkeypatch.setenv("WOODSHED_TOOLS", "music")
    assert paths.tools_dir("linux") == fake.data / "woodshed" / "tools"
    before = fake.files()
    assert run(monkeypatch, "linux", "--yes") == 0
    assert fake.files() == before


@pytest.mark.parametrize("value", ["~root/tools", "~nobody", "relative/tools"])
def test_a_tools_setting_that_is_not_a_folder_of_its_own_is_ignored(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, value: str
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))  # Path.home() on Windows
    monkeypatch.setenv("WOODSHED_TOOLS", value)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    assert paths.tools_dir("linux") == tmp_path / ".local" / "share" / "woodshed" / "tools"


def test_files_named_like_rubber_band_but_not_it_are_kept(
    fake: Home, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Before, any file named rubberband, sndfile.dll or COPYING went, whatever it held.
    documents = fake.home / "Documents"
    monkeypatch.setenv("WOODSHED_TOOLS", str(documents))
    documents.mkdir()
    for name in ("rubberband", "sndfile.dll", "COPYING", "uninstall-woodshed.sh"):
        (documents / name).write_bytes(b"the user's own " + name.encode())
    before = fake.files()
    assert run(monkeypatch, "linux", "--yes") == 0
    assert fake.files() == before
    out = capsys.readouterr().out
    assert str(documents / "rubberband") in out and "not made by woodshed" in out


def test_the_licence_goes_only_beside_the_pinned_program(fake: Home, monkeypatch: pytest.MonkeyPatch) -> None:
    fill_tools(fake, "COPYING")
    (fake.tools / "rubberband").write_bytes(b"another build")
    assert run(monkeypatch, "linux", "--yes") == 0
    assert (fake.tools / "COPYING").exists() and (fake.tools / "rubberband").exists()


def test_folders_the_user_named_stay_when_emptied(fake: Home, monkeypatch: pytest.MonkeyPatch) -> None:
    # WOODSHED_CACHE and WOODSHED_TOOLS name the user's folders: before, rmdir took them once empty.
    fill_cache(fake)
    fill_tools(fake, "rubberband", "COPYING")
    assert run(monkeypatch, "linux", "--yes") == 0
    assert fake.cache.is_dir() and not any(fake.cache.iterdir())
    assert fake.tools.is_dir() and not any(fake.tools.iterdir())


def test_without_settings_woodshed_s_own_empty_folders_go(fake: Home, monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("WOODSHED_CACHE", "WOODSHED_TOOLS"):
        monkeypatch.delenv(name)
    monkeypatch.setattr(uninstall, "cache_dir", lambda: fake.home / ".cache" / "woodshed")
    (fake.home / ".cache" / "woodshed" / "stems").mkdir(parents=True)
    fill_tools(fake, "rubberband", folder=fake.data / "woodshed" / "tools")
    assert run(monkeypatch, "linux", "--yes") == 0
    assert not (fake.home / ".cache" / "woodshed").exists() and (fake.home / ".cache").is_dir()
    assert not (fake.data / "woodshed").exists() and fake.data.is_dir()


def test_windows_cache_ignores_a_relative_localappdata(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # Before, a missing or relative LOCALAPPDATA fell to ~/.cache/woodshed, and the uninstall's
    # "LOCALAPPDATA\\woodshed" rmdir became ~/.cache.
    import sys

    from woodshed.cache import cache_dir

    monkeypatch.delenv("WOODSHED_CACHE", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setattr(sys, "platform", "win32")
    for value in ("relative", ""):
        monkeypatch.setenv("LOCALAPPDATA", value)
        assert cache_dir() == tmp_path / "AppData" / "Local" / "woodshed" / "Cache"
