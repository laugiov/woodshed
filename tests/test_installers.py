"""The install scripts: the macOS app that install.sh makes, and the double-click installers as shipped."""

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


def shell_function(name: str) -> str:
    """One function of install.sh, to run it alone (the script itself installs woodshed)."""
    lines = INSTALL_SH.read_text(encoding="utf-8").splitlines()
    start = lines.index(f"{name}() {{")
    return "\n".join(lines[start : lines.index("}", start) + 1]) + "\n"


@pytest.mark.skipif(sys.platform == "win32" or not shutil.which("sh"), reason="needs a POSIX shell")
def test_the_mac_app_runs_woodshed_app_in_a_terminal_window(tmp_path: Path) -> None:
    home = tmp_path / "Jane Doe"  # a space in the path, as on many Macs
    home.mkdir()
    bin_dir = home / ".local" / "bin"
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
        subprocess.run(["sh", "-n", str(script)], check=True)
    assert 'open -a Terminal "$(dirname "$0")/../Resources/woodshed.command"' in launcher.read_text(encoding="utf-8")
    assert f'"{bin_dir}/woodshed" app' in command.read_text(encoding="utf-8")
    assert sorted(p.name for p in (home / "Applications").iterdir()) == ["woodshed.app"]


def test_the_windows_installer_has_windows_line_endings() -> None:
    data = WINDOWS_INSTALLER.read_bytes()
    data.decode("ascii")  # the console's code page varies
    assert data.count(b"\n") == data.count(b"\r\n"), "cmd.exe misreads labels in files with Unix line endings"


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
