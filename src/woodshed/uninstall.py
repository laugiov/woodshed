"""woodshed uninstall: remove what woodshed and its installers put on this computer, never the songs.

What goes, after one question: the separated tracks and the models in the cache (`stems/` and `models/` only,
never the cache folder's other files), the files woodshed puts in its tools folder (by name, never the folder's
other files: WOODSHED_TOOLS may name a folder of the user's), and the shortcuts the installers made (the Mac
apps, the Linux menu entries, the Windows Start menu shortcuts and the Settings > Apps entry). Then woodshed
itself, which a running program cannot do: the shortcuts run `woodshed uninstall --keep-self` and then `uv tool
uninstall woodshed` once it has exited; typed in a terminal, the command prints that last step.

A link (or a Windows junction) is removed, never what it points to. A file that stays locked stops it before
woodshed itself goes, so the shortcut can be run again. It refuses while woodshed runs, outside a uv tool install, in
Docker, and when the library and a folder it would remove contain each other.
"""

from __future__ import annotations

import argparse
import contextlib
import os
import re
import shutil
import stat
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from woodshed.cache import cache_dir
from woodshed.paths import absolute_env, data_home
from woodshed.paths import tools_dir as tools_dir  # shared with pitch and the installers

PORT = 8000  # the app's default port, the one its shortcuts open
LIBRARY = Path("~/woodshed")  # the library the shortcuts open
UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\woodshed"
APP_ID = "io.github.laugiov.woodshed"  # the Mac apps' bundle identifiers start with it
WINDOWS_SCRIPT = "uninstall-woodshed.cmd"  # in the tools folder, what the Start menu and Settings run
QUESTION = (
    "Remove woodshed from this computer? Your songs stay where they are.\n"
    "Type y then Enter to remove it (Enter alone keeps everything): [y/N] "
)
# What woodshed puts in its tools folder: only these names are removed from it. Rubber Band's licence files only
# beside its program (a folder of the user's may have a COPYING of its own).
TOOL_FILES = ("uninstall-woodshed.sh", WINDOWS_SCRIPT, "rubberband", "rubberband.exe", "sndfile.dll")
TOOL_LICENCES = ("COPYING", "COPYING.txt")
# uv keeps every download: `uv cache prune` frees nothing once woodshed is gone (seen on all three systems), so
# woodshed's own entry and its heavy packages leave the cache (downloaded again if another program needs them).
# Never `uv cache clean` alone: that empties the cache of every other uv program too.
CACHED = ("woodshed", "torch", "torchaudio", "demucs", "llvmlite", "numba", "scipy", "scikit-learn", "sympy", "numpy")
LAST_STEP = ("uv tool uninstall woodshed", "uv cache clean " + " ".join(CACHED))
RUNNING = (
    "woodshed is still running: close its Terminal window (Mac) or its black window (Windows), not only the"
    " browser tab, then try again."
)
NO_PROCESS_LIST = "(woodshed could not list this computer's programs: it only checked woodshed's port)"
EXIT_OK, EXIT_STOPPED = 0, 1


def _system() -> str:
    return sys.platform


def _prefix() -> Path:
    return Path(sys.prefix)


def _script() -> str:
    """The path this woodshed was started by (the `woodshed` command in uv's bin folder)."""
    return str(Path(sys.argv[0]).absolute())


def _is_junction(path: Path) -> bool:
    """A Windows junction (mklink /J): a link to a folder that is not a symlink."""
    isjunction = getattr(os.path, "isjunction", None)  # Python 3.12+
    if isjunction is not None:
        return bool(isjunction(path))
    try:
        info = os.lstat(path)
    except OSError:
        return False
    return bool(getattr(info, "st_file_attributes", 0) & 0x400) and stat.S_ISDIR(info.st_mode)  # REPARSE_POINT


def _is_link(path: Path) -> bool:
    return path.is_symlink() or _is_junction(path)


def _remove_link(path: Path) -> None:
    """The link only: what it points to stays."""
    try:
        os.unlink(path)
    except (IsADirectoryError, PermissionError):
        os.rmdir(path)  # a junction or a folder link on Windows: rmdir removes the link, not the folder


def _tool_files(folder: Path) -> list[Path]:
    """The files woodshed put in its tools folder, the only ones taken from it."""
    if not folder.is_dir():
        return []
    names = [n for n in TOOL_FILES if os.path.lexists(folder / n)]
    if any(n.startswith("rubberband") for n in names):
        names += [n for n in TOOL_LICENCES if os.path.lexists(folder / n)]
    return [folder / n for n in names if _is_link(folder / n) or not (folder / n).is_dir()]


def _has(pattern: bytes) -> Callable[[bytes], bool]:
    return lambda data: re.search(pattern, data) is not None


def _holds(text: str) -> Callable[[bytes], bool]:
    """A .lnk file holds its target's path, often in UTF-16."""
    return lambda data: text.encode() in data.lower() or text.encode("utf-16-le") in data.lower()


@dataclass(frozen=True)
class Item:
    """One thing to remove. `tools`: a folder of which only woodshed's files go (then the folder if empty)."""

    path: Path
    label: str
    ours_if: tuple[str, Callable[[bytes], bool]] | None = None  # (file inside, test): only a file of ours goes
    tools: bool = False
    keep: tuple[str, ...] = ()

    def ours(self) -> bool:
        if self.ours_if is None or _is_link(self.path):
            return True
        inside, test = self.ours_if
        try:
            data = (self.path / inside if inside else self.path).read_bytes()
        except OSError:
            return False
        return test(data)


@dataclass
class Plan:
    items: list[Item] = field(default_factory=list)
    then_rmdir: list[Path] = field(default_factory=list)  # removed only when left empty
    registry_key: bool = False
    foreign: list[Path] = field(default_factory=list)  # a file named as ours, not made by woodshed: kept
    failed: list[str] = field(default_factory=list)  # what could not be removed, and why
    kept: list[str] = field(default_factory=list)
    refusal: str | None = None


def _shortcuts(system: str) -> list[Item]:
    if system == "darwin":
        apps = Path.home() / "Applications"
        plist = "Contents/Info.plist"
        return [
            Item(
                apps / "woodshed.app", "the woodshed app",
                (plist, _has(rb"<string>io\.github\.laugiov\.woodshed</string>")),
            ),
            Item(
                apps / "Uninstall woodshed.app", "the Uninstall woodshed app",
                (plist, _has(rb"<string>io\.github\.laugiov\.woodshed\.uninstall</string>")),
            ),
        ]  # fmt: skip
    if system == "win32":
        roaming = absolute_env("APPDATA") or Path.home() / "AppData" / "Roaming"
        programs = roaming / "Microsoft" / "Windows" / "Start Menu" / "Programs"
        return [
            Item(programs / "woodshed.lnk", "the Start menu shortcut", ("", _holds("woodshed.exe"))),
            Item(
                programs / "Uninstall woodshed.lnk", "the Start menu's Uninstall woodshed",
                ("", _holds(WINDOWS_SCRIPT)),
            ),
        ]  # fmt: skip
    apps = data_home() / "applications"
    return [
        Item(apps / "woodshed.desktop", "the menu entry", ("", _has(rb'(?m)^Exec=.*woodshed"? app[ \t\r]*$'))),
        Item(
            apps / "woodshed-uninstall.desktop", "the menu's Uninstall woodshed",
            ("", _has(rb"(?m)^Exec=.*uninstall-woodshed\.sh")),
        ),
    ]  # fmt: skip


def _overlap(a: Path, b: Path) -> bool:
    return a == b or a in b.parents or b in a.parents


def _where(path: Path) -> Path:
    """The path itself, resolved up to its last part (a link stays the link)."""
    return path.parent.resolve() / path.name


def plan(system: str, keep_self: bool = False) -> Plan:
    """What `woodshed uninstall` would remove and keep. Removes nothing."""
    cache = cache_dir()
    tools = tools_dir(system)
    library = LIBRARY.expanduser().resolve()
    p = Plan()
    candidates = [
        *_shortcuts(system),
        Item(cache / "stems", "the separated tracks"),
        Item(cache / "models", "the downloaded models"),
    ]
    keep = (WINDOWS_SCRIPT,) if keep_self and system == "win32" else ()  # the .cmd running this one
    if going := [f.name for f in _tool_files(tools) if f.name not in keep]:
        what = []
        if any(n.startswith("rubberband") for n in going):
            what.append("Rubber Band (the recording in your key) and its licence")
        if any(n.startswith("uninstall-woodshed") for n in going):
            what.append("the uninstall script")
        label = " and ".join(what) + ", in woodshed's tools folder" if what else "woodshed's tools"
        candidates.append(Item(tools, label, tools=True, keep=keep))
    for item in candidates:
        if not os.path.lexists(item.path):
            continue
        if item.ours():
            p.items.append(item)
        else:
            p.foreign.append(item.path)
    p.then_rmdir.append(cache)
    if not os.environ.get("WOODSHED_CACHE") and system == "win32":
        p.then_rmdir.append(cache.parent)  # LOCALAPPDATA\woodshed, once Cache and tools are gone
    p.then_rmdir.append(tools)  # only if left empty (a folder of the user's keeps its files)
    if not os.environ.get("WOODSHED_TOOLS"):
        p.then_rmdir.append(tools.parent)
    p.registry_key = system == "win32" and not keep_self  # the shortcut's script removes it, after woodshed
    p.kept = [
        f"your songs and their practice pages: {library} (a library kept somewhere else is not looked at, and"
        " stays too)"
    ]
    if system == "win32":
        p.kept.append("ffmpeg, if the installer added it (to remove it: winget uninstall Gyan.FFmpeg)")
    p.kept.append(
        "uv, a helper other programs may use, with the Python it downloaded and the line it added to your PATH"
    )

    home = Path.home().resolve()
    for target in [cache, tools, *(i.path for i in p.items)]:
        where = _where(target)
        if _overlap(where, library):
            p.refusal = (
                f"{where} and your songs ({library}) are inside one another: nothing was removed, to keep"
                " the songs safe. Move one of them, or remove woodshed's files by hand."
            )
        elif where == home or where in home.parents or where == Path(where.anchor):
            p.refusal = f"{where} is not woodshed's own folder: nothing was removed."
        if p.refusal:
            break
    return p


def _size(path: Path) -> str:
    if path.is_symlink() or not path.is_dir():
        return ""
    total = sum(f.stat().st_size for f in path.rglob("*") if f.is_file() and not f.is_symlink())
    return f" ({total / 1e6:.1f} MB)" if total >= 50_000 else ""


def _delete_key(key: str) -> None:
    """Remove the Settings > Apps entry (HKCU: no administrator rights)."""
    if sys.platform == "win32":
        import winreg

        with contextlib.suppress(FileNotFoundError):
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key)


def _remove(item: Item) -> str:
    path = item.path
    if item.tools:
        files = [f for f in _tool_files(path) if f.name not in item.keep]
        for f in files:
            _remove_link(f) if _is_link(f) else f.unlink()
        return f"{item.label}: {path} ({', '.join(f.name for f in files)})"
    if _is_link(path):
        _remove_link(path)
        return f"{item.label}: {path} (a link: only the link, not what it points to)"
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()
    return f"{item.label}: {path}"


def remove(p: Plan) -> list[str]:
    """Carry the plan out: the shortcuts first, then the files, the empty folders, the Settings entry last. What
    cannot be removed (a file another program holds open) is noted in `p.failed`, and the rest still goes."""
    done = []
    for item in p.items:
        try:
            done.append(_remove(item))
        except OSError as exc:
            p.failed.append(f"{item.label}: {item.path}: {exc.strerror or exc}")
    for folder in p.then_rmdir:
        if not _is_link(folder):  # rmdir would remove a junction itself
            with contextlib.suppress(OSError):
                folder.rmdir()  # only when empty
    if p.registry_key and not p.failed:  # kept to try again from Settings > Apps
        _delete_key(UNINSTALL_KEY)
    return done


Process = tuple[int, int, str]  # pid, parent pid, command line (on Windows the program's file name)


def _windows_processes() -> list[Process]:
    """Every process, with its parent, from a Toolhelp snapshot (no program to run, no wmic)."""
    found: list[Process] = []
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        class Entry(ctypes.Structure):  # PROCESSENTRY32W
            _fields_ = [
                ("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD),
                ("cntThreads", wintypes.DWORD), ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_wchar * 260),
            ]  # fmt: skip

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        for step in (kernel.Process32FirstW, kernel.Process32NextW):
            step.argtypes = [wintypes.HANDLE, ctypes.POINTER(Entry)]
            step.restype = wintypes.BOOL
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        snapshot = kernel.CreateToolhelp32Snapshot(0x2, 0)  # TH32CS_SNAPPROCESS
        if snapshot in (None, wintypes.HANDLE(-1).value):
            return found
        try:
            entry = Entry()
            entry.dwSize = ctypes.sizeof(Entry)
            more = kernel.Process32FirstW(snapshot, ctypes.byref(entry))
            while more:
                found.append((entry.th32ProcessID, entry.th32ParentProcessID, entry.szExeFile))
                more = kernel.Process32NextW(snapshot, ctypes.byref(entry))
        finally:
            kernel.CloseHandle(snapshot)
    return found


def _processes() -> list[Process]:
    """This computer's processes with their parents."""
    if sys.platform == "win32":
        try:
            return _windows_processes()
        except OSError:
            return []
    try:
        out = subprocess.run(
            ["ps", "-Ao", "pid=,ppid=,args="], capture_output=True, text=True, timeout=20, check=False
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    found = []
    for line in out.splitlines():
        pid, ppid, args = ([*line.split(None, 2), "", ""])[:3]
        if pid.isdigit() and ppid.isdigit():
            found.append((int(pid), int(ppid), args.strip()))
    return found


def _lineage(processes: Sequence[Process], me: int) -> set[int]:
    """This process and all its ancestors: the launchers between the shortcut and this Python (on Windows
    woodshed.exe, then the environment's python.exe, then uv's), and the shortcut's own shell."""
    parent = {pid: ppid for pid, ppid, _ in processes}
    chain = {me}
    pid = parent.get(me)
    while pid is not None and pid not in chain:  # a reused id can loop back
        chain.add(pid)
        pid = parent.get(pid)
    if me == os.getpid():
        chain.add(os.getppid())  # even when the list misses this process
    return chain


def other_woodshed(processes: Sequence[Process], script: str, system: str, me: int | None = None) -> int | None:
    """The process id of a woodshed other than this one and its ancestors, if one runs."""
    mine = _lineage(processes, os.getpid() if me is None else me)
    if system == "win32":
        return next((pid for pid, _, name in processes if pid not in mine and name.lower() == "woodshed.exe"), None)
    names = {script, os.path.realpath(script)}
    pattern = re.compile("|".join(re.escape(n) + r"(\s|$)" for n in names))
    return next((pid for pid, _, args in processes if pid not in mine and pattern.search(args)), None)


def others_running(processes: Sequence[Process], script: str, system: str, me: int | None = None) -> bool:
    return other_woodshed(processes, script, system, me) is not None


def _running(system: str) -> str | None:
    """Why woodshed counts as running, if it does."""
    from woodshed.app import running_url

    if running_url(PORT) is not None:
        return RUNNING
    processes = _processes()
    if not processes:
        print(NO_PROCESS_LIST)
        return None
    return RUNNING if other_woodshed(processes, _script(), system) is not None else None


def _installed_by_uv() -> bool:
    prefix = _prefix()
    return (prefix / "uv-receipt.toml").is_file()


def parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="woodshed uninstall",
        description="Remove woodshed from this computer: its cache, its tools and its shortcuts, then woodshed"
        " itself. Your songs and their pages stay.",
    )
    parser.add_argument("--yes", action="store_true", help="do not ask first")
    parser.add_argument(
        "--keep-self", action="store_true",
        help="leave woodshed itself (and on Windows its Settings entry): the Uninstall shortcut removes it next",
    )  # fmt: skip
    return parser


def _refuse(message: str) -> int:
    print(f"woodshed uninstall: {message}", file=sys.stderr)
    return EXIT_STOPPED


def main(argv: Sequence[str]) -> int:
    args = parser().parse_args(argv)
    system = _system()
    if os.environ.get("WOODSHED_CONTAINER") == "1":
        return _refuse(
            "woodshed runs in Docker here: remove the container and its image with Docker (docker compose down"
            " --volumes, then docker image rm ghcr.io/laugiov/woodshed). Your library folder stays."
        )
    if not _installed_by_uv():
        return _refuse(
            "this woodshed was not installed by woodshed's installer (a uv tool), so it does not remove itself:"
            " uninstall it the way it was installed (pipx uninstall woodshed, or pip uninstall woodshed), then"
            f" delete its cache folder if you like: {cache_dir()}"
        )
    p = plan(system, args.keep_self)
    if p.refusal:
        return _refuse(p.refusal)
    if running := _running(system):
        return _refuse(running)

    print("This removes:")
    for item in p.items:
        print(f"  - {item.label}: {item.path}{_size(item.path)}")
    if p.registry_key:
        print("  - woodshed's entry in Settings > Apps")
    if args.keep_self:
        print("  - woodshed itself (removed right after, in this window)")
    else:
        print("  - woodshed itself (with the two commands printed at the end)")
    print(
        "  - woodshed's big packages in uv's cache (torch, numpy...): other Python programs may download them"
        " again if they need them"
    )
    print("It keeps:")
    for line in p.kept:
        print(f"  - {line}")
    for path in p.foreign:
        print(f"  - {path} (not made by woodshed)")
    print("", flush=True)
    if not args.yes:
        try:
            answer = input(QUESTION)
        except EOFError:
            answer = ""
        if answer.strip().lower() not in ("y", "yes"):
            print("Nothing was removed.")
            return EXIT_STOPPED

    done = remove(p)
    if done:
        print("Removed:")
        for line in done:
            print(f"  - {line}")
    if p.failed:
        print("Not removed (another program may be using it):")
        for line in p.failed:
            print(f"  - {line}")
        print("woodshed itself stays, so you can try again: close the programs using these files, then run")
        print("Uninstall woodshed again.")
        return EXIT_STOPPED
    if not args.keep_self:
        print("")
        print("Last step: woodshed cannot remove itself while it runs. Type these two commands:")
        for command in LAST_STEP:
            print(f"  {command}")
    return EXIT_OK
