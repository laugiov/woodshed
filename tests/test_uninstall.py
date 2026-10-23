"""woodshed uninstall in a fake home: what it removes, what it keeps (the songs above all), when it refuses.

Nothing here touches the real home: HOME, LOCALAPPDATA, APPDATA, XDG_*, WOODSHED_CACHE and WOODSHED_TOOLS
point into a temp folder, the uv tool environment is a fake one, the process list is given and the port
probed is a free one (or one a fake woodshed answers on)."""

from __future__ import annotations

import json
import os
import socket
import threading
from collections.abc import Iterator
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from woodshed import cli, uninstall

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
    return h


def fill_cache(h: Home) -> None:
    (h.cache / "stems" / "htdemucs_6s-abc").mkdir(parents=True)
    (h.cache / "stems" / "htdemucs_6s-abc" / "vocals.flac").write_bytes(b"x" * 10)
    (h.cache / "models").mkdir()
    (h.cache / "models" / "htdemucs_6s.th").write_bytes(b"m")


def fill_tools(h: Home, *names: str) -> None:
    h.tools.mkdir(parents=True, exist_ok=True)
    for name in names or ("rubberband",):
        (h.tools / name).write_text("tool", encoding="utf-8")


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
    for entry in menu:
        entry.write_text("[Desktop Entry]\nName=woodshed\nExec=woodshed app\n", encoding="utf-8")
    (apps / "other.desktop").write_text("[Desktop Entry]\nName=Other\n", encoding="utf-8")
    before, expected = fake.files(), below(fake.cache, *menu, fake.tools)

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
    before, expected = fake.files(), below(fake.cache, *ours)

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
    for link in links:
        link.write_bytes(b"L\0\0\0" + "C:\\bin\\woodshed.exe".encode("utf-16-le"))
    (programs / "Other.lnk").write_bytes(b"L\0\0\0other")
    before, expected = fake.files(), below(fake.cache, *links, fake.tools)

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
    fake.tools.symlink_to(tools_target, target_is_directory=True)

    assert run(monkeypatch, "linux", "--yes") == 0

    assert not os.path.lexists(fake.cache / "stems") and not os.path.lexists(fake.tools)
    assert (elsewhere / "a.flac").exists() and (tools_target / "rubberband").exists()
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


@pytest.fixture
def woodshed_answering(fake: Home, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeWoodshed)
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
    assert "woodshed is running: close its window first" in capsys.readouterr().err


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
    assert "close its window first" in capsys.readouterr().err


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


def test_refuses_with_the_process_named(
    fake: Home, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(uninstall, "_processes", lambda: [*WINDOWS_TREE, (700, 4, "woodshed.exe")])
    monkeypatch.setattr(os, "getpid", lambda: 500)
    fill_cache(fake)
    assert run(monkeypatch, "win32", "--yes") == 1
    assert "process 700" in capsys.readouterr().err


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
    assert asked == ["Remove woodshed from this computer? Your songs stay where they are. [y/N] "]
    assert not (fake.cache / "stems").exists()


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
