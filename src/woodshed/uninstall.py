"""woodshed uninstall: remove what woodshed and its installers put on this computer, never the songs.

What goes, after one question: the separated tracks and the models in the cache (`stems/` and `models/` only,
never the cache folder's other files), woodshed's tools folder, and the shortcuts the installers made (the Mac
apps, the Linux menu entries, the Windows Start menu shortcuts and the Settings > Apps entry). Then woodshed
itself, which a running program cannot do: the shortcuts run `woodshed uninstall --keep-self` and then `uv tool
uninstall woodshed` once it has exited; typed in a terminal, the command prints that last step.

A link is removed, never what it points to. It refuses while woodshed runs, outside a uv tool install, in
Docker, and when the library and a folder it would remove contain each other.
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import io
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from woodshed.cache import cache_dir

PORT = 8000  # the app's default port, the one its shortcuts open
LIBRARY = Path("~/woodshed")  # the library the shortcuts open
UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\woodshed"
APP_ID = "io.github.laugiov.woodshed"  # the Mac apps' bundle identifiers start with it
WINDOWS_SCRIPT = "uninstall-woodshed.cmd"  # in the tools folder, what the Start menu and Settings run
QUESTION = "Remove woodshed from this computer? Your songs stay where they are. [y/N] "
LAST_STEP = ("uv tool uninstall woodshed", "uv cache prune")
RUNNING = "woodshed is running: close its window first (the library in the browser), then try again."
EXIT_OK, EXIT_STOPPED = 0, 1


def _system() -> str:
    return sys.platform


def _prefix() -> Path:
    return Path(sys.prefix)


def _script() -> str:
    """The path this woodshed was started by (the `woodshed` command in uv's bin folder)."""
    return str(Path(sys.argv[0]).absolute())


def _absolute_env(name: str) -> Path | None:
    value = os.environ.get(name, "")
    return Path(value) if value and Path(value).is_absolute() else None  # the XDG spec ignores a relative value


def _data_home() -> Path:
    return _absolute_env("XDG_DATA_HOME") or Path.home() / ".local" / "share"


def _local_appdata() -> Path:
    return _absolute_env("LOCALAPPDATA") or Path.home() / "AppData" / "Local"


def tools_dir(system: str | None = None) -> Path:
    """Where woodshed keeps the programs it adds: WOODSHED_TOOLS, else a per-system data folder."""
    if override := os.environ.get("WOODSHED_TOOLS"):
        return Path(override).expanduser()
    system = system or _system()
    if system == "win32":
        return _local_appdata() / "woodshed" / "tools"
    if system == "darwin":
        return Path.home() / "Library" / "Application Support" / "woodshed" / "tools"
    return _data_home() / "woodshed" / "tools"


@dataclass(frozen=True)
class Item:
    """One thing to remove. A folder goes with its contents, except the names in `keep` (then it stays)."""

    path: Path
    label: str
    marker: tuple[str, str] | None = None  # (file inside, text it holds): only a file of ours goes
    keep: tuple[str, ...] = ()

    def ours(self) -> bool:
        if self.marker is None or self.path.is_symlink():
            return True
        inside, text = self.marker
        try:
            data = (self.path / inside if inside else self.path).read_bytes()
        except OSError:
            return False
        return text.encode() in data or text.encode("utf-16-le") in data  # a .lnk holds UTF-16 paths


@dataclass
class Plan:
    items: list[Item] = field(default_factory=list)
    then_rmdir: list[Path] = field(default_factory=list)  # removed only when left empty
    registry_key: bool = False
    foreign: list[Path] = field(default_factory=list)  # a file named as ours, not made by woodshed: kept
    kept: list[str] = field(default_factory=list)
    refusal: str | None = None


def _shortcuts(system: str) -> list[Item]:
    if system == "darwin":
        apps = Path.home() / "Applications"
        return [
            Item(apps / "woodshed.app", "the woodshed app", ("Contents/Info.plist", APP_ID)),
            Item(apps / "Uninstall woodshed.app", "the Uninstall woodshed app", ("Contents/Info.plist", APP_ID)),
        ]
    if system == "win32":
        roaming = _absolute_env("APPDATA") or Path.home() / "AppData" / "Roaming"
        programs = roaming / "Microsoft" / "Windows" / "Start Menu" / "Programs"
        return [
            Item(programs / "woodshed.lnk", "the Start menu shortcut", ("", "woodshed")),
            Item(programs / "Uninstall woodshed.lnk", "the Start menu's Uninstall woodshed", ("", "woodshed")),
        ]
    apps = _data_home() / "applications"
    return [
        Item(apps / "woodshed.desktop", "the menu entry", ("", "woodshed")),
        Item(apps / "woodshed-uninstall.desktop", "the menu's Uninstall woodshed", ("", "woodshed")),
    ]


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
        Item(tools, "woodshed's tools", keep=(WINDOWS_SCRIPT,) if keep_self and system == "win32" else ()),
    ]
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
    if not os.environ.get("WOODSHED_TOOLS"):
        p.then_rmdir.append(tools.parent)
    p.registry_key = system == "win32" and not keep_self  # the shortcut's script removes it, after woodshed
    p.kept = [f"your songs and their practice pages: {library}"]
    if system == "win32":
        p.kept.append("ffmpeg, if the installer added it (to remove it: winget uninstall Gyan.FFmpeg)")
    p.kept.append("uv and the Python it downloaded, and the line it added to your PATH")

    home = Path.home().resolve()
    for target in [cache, *(i.path for i in p.items)]:
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
    if path.is_symlink():
        path.unlink()
        return f"{item.label}: {path} (a link: only the link, not what it points to)"
    if path.is_dir():
        if item.keep:
            for child in path.iterdir():
                if child.name in item.keep:
                    continue
                if child.is_dir() and not child.is_symlink():
                    shutil.rmtree(child)
                else:
                    child.unlink()
        else:
            shutil.rmtree(path)
    else:
        path.unlink()
    return f"{item.label}: {path}"


def remove(p: Plan) -> list[str]:
    """Carry the plan out: the shortcuts first, then the files, the empty folders, the Settings entry last."""
    done = [_remove(item) for item in p.items]
    for folder in p.then_rmdir:
        with contextlib.suppress(OSError):
            folder.rmdir()  # only when empty
    if p.registry_key:
        _delete_key(UNINSTALL_KEY)
    return done


def _processes() -> list[tuple[int, str]]:
    """(pid, command line) of this user's processes; on Windows the woodshed.exe ones, by image name."""
    try:
        if sys.platform == "win32":
            out = subprocess.run(
                ["tasklist", "/FO", "CSV", "/NH", "/FI", "IMAGENAME eq woodshed.exe"],
                capture_output=True, text=True, timeout=20, check=False,
            ).stdout  # fmt: skip
            return [(int(row[1]), row[0]) for row in csv.reader(io.StringIO(out)) if len(row) > 1 and row[1].isdigit()]
        out = subprocess.run(
            ["ps", "-Ao", "pid=,args="], capture_output=True, text=True, timeout=20, check=False
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    found = []
    for line in out.splitlines():
        pid, _, args = line.strip().partition(" ")
        if pid.isdigit():
            found.append((int(pid), args.strip()))
    return found


def others_running(processes: Sequence[tuple[int, str]], script: str, system: str) -> bool:
    """Another woodshed than this one and its parent (the launcher, or the shell of the shortcut)."""
    me = {os.getpid(), os.getppid()}
    if system == "win32":
        return any(pid not in me and args.lower() == "woodshed.exe" for pid, args in processes)
    names = {script, os.path.realpath(script)}
    pattern = re.compile("|".join(re.escape(n) + r"(\s|$)" for n in names))
    return any(pid not in me and pattern.search(args) for pid, args in processes)


def _running(system: str) -> bool:
    from woodshed.app import running_url

    return running_url(PORT) is not None or others_running(_processes(), _script(), system)


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
    if _running(system):
        return _refuse(RUNNING)

    print("This removes:")
    for item in p.items:
        print(f"  - {item.label}: {item.path}{_size(item.path)}")
    if p.registry_key:
        print("  - woodshed's entry in Settings > Apps")
    print("  - woodshed itself" + (", once this window's next step runs" if args.keep_self else ""))
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
    if not args.keep_self:
        print("")
        print("Last step: woodshed cannot remove itself while it runs. Type these two commands:")
        for command in LAST_STEP:
            print(f"  {command}")
    return EXIT_OK
