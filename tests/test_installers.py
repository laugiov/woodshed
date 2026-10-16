"""The install scripts: what install.sh does on each system, the macOS app it makes, and the double-click
installers as shipped. install.sh runs against stubs (uv, uname, sysctl, pgrep, curl): nothing is installed."""

import os
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
INSTALL_SH = ROOT / "scripts" / "install.sh"
MAC_INSTALLER = ROOT / "scripts" / "installers" / "Install woodshed.command"
WINDOWS_INSTALLER = ROOT / "scripts" / "installers" / "Install woodshed.cmd"

posix_only = pytest.mark.skipif(sys.platform == "win32" or not shutil.which("sh"), reason="needs a POSIX shell")

STUBS = {
    "uname": 'case "$1" in -s) echo "$STUB_OS" ;; -m) echo "$STUB_ARCH" ;; esac',
    "sysctl": 'echo "$STUB_ARM64"',
    "uv": 'printf \'%s\\t\' "$@" >> "$STUB_LOG"; echo >> "$STUB_LOG"\n'
    '[ "$1 $2 $3" = "tool dir --bin" ] && echo "$STUB_BIN"\nexit 0',
    "pgrep": 'exit "${STUB_RUNNING:-1}"',
    "curl": "exit 1",  # nothing is downloaded
}


def write_script(path: Path, body: str) -> None:
    path.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
    path.chmod(0o755)


Calls = list[list[str]]


def run_install(tmp_path: Path, system: str, arch: str, arm64: str = "", **env: str) -> tuple[int, str, Calls]:
    """install.sh with WOODSHED_NO_MENU=1: its exit code, its output and the uv commands it ran."""
    stubs, bin_dir, home = tmp_path / "stubs", tmp_path / "bin", tmp_path / "home"
    for folder in (stubs, bin_dir, home):
        folder.mkdir(exist_ok=True)
    for name, body in STUBS.items():
        write_script(stubs / name, body)
    write_script(bin_dir / "woodshed", 'echo "woodshed 0.0.0"')
    log = tmp_path / "uv.log"
    log.write_text("", encoding="utf-8")
    proc = subprocess.run(
        ["sh", str(INSTALL_SH)],
        env={
            "PATH": f"{stubs}{os.pathsep}{os.environ.get('PATH', '')}", "HOME": str(home), "WOODSHED_NO_MENU": "1",
            "STUB_OS": system, "STUB_ARCH": arch, "STUB_ARM64": arm64, "STUB_BIN": str(bin_dir), "STUB_LOG": str(log),
            **env,
        },
        capture_output=True, text=True, check=False,
    )  # fmt: skip
    calls = [line.split("\t")[:-1] for line in log.read_text(encoding="utf-8").splitlines()]
    return proc.returncode, proc.stdout + proc.stderr, calls


def install_call(calls: Calls) -> list[str]:
    [call] = [c for c in calls if c[:2] == ["tool", "install"]]
    return call


@posix_only
@pytest.mark.parametrize("arm64", ["0", ""])  # older Intel Macs do not know the key at all
def test_an_intel_mac_is_sent_to_docker(tmp_path: Path, arm64: str) -> None:
    code, out, calls = run_install(tmp_path, "Darwin", "x86_64", arm64)
    assert code == 1
    assert "Intel" in out and "Docker" in out and "#with-docker-windows-macos-or-linux" in out
    assert not [c for c in calls if c[:2] == ["tool", "install"]]


@posix_only
@pytest.mark.parametrize("uname_arch", ["arm64", "x86_64"])  # x86_64: a Terminal under Rosetta
def test_apple_silicon_installs_the_arm_python_from_an_archive_of_the_ref(tmp_path: Path, uname_arch: str) -> None:
    code, out, calls = run_install(tmp_path, "Darwin", uname_arch, "1", WOODSHED_REF="v9.9.9")
    assert code == 0, out
    call = install_call(calls)
    assert call[call.index("--python") + 1] == "cpython-3.13-macos-aarch64-none"
    assert call[-1] == "woodshed[stems] @ https://github.com/laugiov/woodshed/archive/v9.9.9.tar.gz"


@posix_only
def test_linux_installs_with_git_from_main_by_default(tmp_path: Path) -> None:
    code, out, calls = run_install(tmp_path, "Linux", "x86_64")
    assert code == 0, out
    call = install_call(calls)
    assert call[call.index("--python") + 1] == "3.13"
    assert call[-1] == "woodshed[stems] @ git+https://github.com/laugiov/woodshed@main"


@posix_only
def test_a_running_woodshed_stops_the_install(tmp_path: Path) -> None:
    code, out, calls = run_install(tmp_path, "Linux", "x86_64", STUB_RUNNING="0")
    assert code == 1
    assert "close woodshed first" in out
    assert not [c for c in calls if c[:2] == ["tool", "install"]]


def shell_function(name: str) -> str:
    """One function of install.sh, to run it alone."""
    lines = INSTALL_SH.read_text(encoding="utf-8").splitlines()
    start = lines.index(f"{name}() {{")
    return "\n".join(lines[start : lines.index("}", start) + 1]) + "\n"


@posix_only
def test_the_mac_app_runs_woodshed_app_in_a_terminal_window(tmp_path: Path) -> None:
    home = tmp_path / "Jane O'Doe"  # a space and a quote in the path
    bin_dir = home / ".local" / "bin"
    bin_dir.mkdir(parents=True)
    got = tmp_path / "args"
    write_script(bin_dir / "woodshed", f"printf '%s\\n' \"$@\" > '{got}'")
    env = {"HOME": str(home), "PATH": os.environ.get("PATH", "")}
    make_app = shell_function("mac_app") + 'mac_app "$1"'
    for _ in range(2):  # installing again replaces the app
        subprocess.run(["sh", "-c", make_app, "sh", str(bin_dir)], env=env, check=True)

    contents = home / "Applications" / "woodshed.app" / "Contents"
    info = plistlib.loads((contents / "Info.plist").read_bytes())
    assert info["CFBundleExecutable"] == "woodshed"
    assert info["CFBundlePackageType"] == "APPL"
    launcher, command = contents / "MacOS" / "woodshed", contents / "Resources" / "woodshed.command"
    for script in (launcher, command):
        assert script.stat().st_mode & 0o111, f"{script.name} is not executable"
    assert 'open -a Terminal "$(dirname "$0")/../Resources/woodshed.command"' in launcher.read_text(encoding="utf-8")
    assert sorted(p.name for p in (home / "Applications").iterdir()) == ["woodshed.app"]
    # What Terminal runs: the installed woodshed, with "app".
    subprocess.run(["sh", str(command)], env=env, check=True, capture_output=True)
    assert got.read_text(encoding="utf-8") == "app\n"


def test_the_windows_installer_has_windows_line_endings() -> None:
    data = WINDOWS_INSTALLER.read_bytes()
    data.decode("ascii")  # the console's code page varies
    assert data.count(b"\n") == data.count(b"\r\n"), "cmd.exe misreads labels in files with Unix line endings"


def test_the_installers_name_the_ref_the_release_rewrites() -> None:
    # .github/workflows/installers.yml replaces "main" in these lines with the release's tag.
    assert 'WOODSHED_REF="${WOODSHED_REF:-main}"' in MAC_INSTALLER.read_text(encoding="utf-8")
    assert 'if not defined WOODSHED_REF set "WOODSHED_REF=main"' in WINDOWS_INSTALLER.read_text(encoding="ascii")


def test_the_mac_installer_is_executable_in_git() -> None:
    try:
        out = subprocess.run(
            ["git", "ls-files", "-s", "--", MAC_INSTALLER.relative_to(ROOT).as_posix()],
            cwd=ROOT, capture_output=True, text=True, check=True,
        )  # fmt: skip
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("not a git checkout")
    if not out.stdout:
        pytest.skip("not tracked yet")
    assert out.stdout.startswith("100755 "), "Finder runs the .command file only if it is executable"
