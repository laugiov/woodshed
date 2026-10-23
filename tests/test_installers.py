"""The install scripts: what install.sh does on each system, the macOS app it makes, and the double-click
installers as shipped. install.sh runs against stubs (uv, uname, sysctl, pgrep, curl): nothing is installed."""

import os
import plistlib
import re
import shutil
import subprocess
import sys
import zipfile
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
    "pgrep": 'printf \'%s\\t\' "$@" >> "$STUB_PGREP_LOG"; echo >> "$STUB_PGREP_LOG"; exit "${STUB_RUNNING:-1}"',
    "curl": "exit 1",  # nothing is downloaded
}


def write_script(path: Path, body: str) -> None:
    path.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
    path.chmod(0o755)


Calls = list[list[str]]


def run_install(tmp_path: Path, system: str, arch: str, arm64: str = "", **env: str) -> tuple[int, str, Calls]:
    """install.sh with WOODSHED_NO_MENU=1: its exit code, its output and the uv commands it ran."""
    # The bin folder's name holds characters that mean something in a regular expression (pgrep).
    stubs, bin_dir, home = tmp_path / "stubs", tmp_path / "b.in (x+y)", tmp_path / "home"
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
            "STUB_PGREP_LOG": str(tmp_path / "pgrep.log"),
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
    # pgrep looks for this install's woodshed only (not one in Docker), its folder name escaped.
    [args] = [line.split("\t")[:-1] for line in (tmp_path / "pgrep.log").read_text(encoding="utf-8").splitlines()]
    target = f"{tmp_path / 'b.in (x+y)'}/woodshed app"
    assert args == ["-f", re.sub(r"([\\.*^$+?(){|\[])", r"\\\1", target)]
    assert re.fullmatch(args[1], target) and not re.search(target, target)  # unescaped, it would miss


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


def run_mac_installer(
    tmp_path: Path, installer: Path, script_body: str, **env: str
) -> subprocess.CompletedProcess[str]:
    """Install woodshed.command with a stub install.sh in place of the real one."""
    script = tmp_path / "install.sh"
    write_script(script, script_body)
    return subprocess.run(
        ["bash", str(installer)],
        env={
            "PATH": os.environ.get("PATH", ""), "HOME": str(tmp_path), "WOODSHED_NO_OPEN": "1",
            "WOODSHED_INSTALL_SCRIPT": str(script), **env,
        },
        capture_output=True, text=True, check=False,
    )  # fmt: skip


needs_bash = pytest.mark.skipif(sys.platform == "win32" or not shutil.which("bash"), reason="needs bash")
PACKAGE = ROOT / "scripts" / "package-installers.sh"


@needs_bash
def test_the_mac_installer_installs_main_as_shipped(tmp_path: Path) -> None:
    proc = run_mac_installer(tmp_path, MAC_INSTALLER, 'echo "ref=$WOODSHED_REF"')
    assert proc.returncode == 0, proc.stderr
    assert "ref=main" in proc.stdout and "Done: woodshed is installed." in proc.stdout


@needs_bash
def test_the_mac_installer_stops_when_the_install_fails(tmp_path: Path) -> None:
    proc = run_mac_installer(tmp_path, MAC_INSTALLER, "exit 3")
    assert proc.returncode == 1
    assert "The installation stopped" in proc.stdout and "Done: woodshed is installed." not in proc.stdout


@needs_bash
@pytest.mark.skipif(not (shutil.which("zip") and shutil.which("zipinfo")), reason="needs zip")
def test_a_release_packages_installers_that_install_its_tag(tmp_path: Path) -> None:
    out = tmp_path / "dist"
    subprocess.run(["bash", str(PACKAGE), str(out), "v1.2.3"], check=True, capture_output=True)
    with zipfile.ZipFile(out / "woodshed-installer-macos.zip") as z:
        [info] = z.infolist()
        assert info.filename == "Install woodshed.command"
        assert (info.external_attr >> 16) & 0o777 == 0o755
        installer = tmp_path / info.filename
        installer.write_bytes(z.read(info))
    proc = run_mac_installer(tmp_path, installer, 'echo "ref=$WOODSHED_REF"')
    assert "ref=v1.2.3" in proc.stdout, proc.stderr
    windows = (out / "woodshed-installer-windows.cmd").read_bytes()
    assert b'if not defined WOODSHED_REF set "WOODSHED_REF=v1.2.3"\r\n' in windows
    assert windows.count(b"\n") == windows.count(b"\r\n")


@needs_bash
@pytest.mark.parametrize("tag", ["v1|x", "v1;rm", "1.0", "v1/../x"])
def test_a_release_refuses_a_strange_tag(tmp_path: Path, tag: str) -> None:
    proc = subprocess.run(["bash", str(PACKAGE), str(tmp_path / "dist"), tag], capture_output=True, text=True)
    assert proc.returncode != 0 and "bad tag" in proc.stderr


# Uninstall woodshed (spec 018): the shortcuts the installers make run "woodshed uninstall --keep-self",
# then uv removes woodshed once it has exited.

PS1 = ROOT / "scripts" / "install.ps1"


def uninstall_stubs(tmp_path: Path, woodshed_exit: int = 0) -> tuple[Path, Path, Path]:
    """A woodshed and a uv that log their arguments, in folders whose names hold a space and a quote."""
    bin_dir, uv_dir, log = tmp_path / "Jane O'Doe bin", tmp_path / "uv dir", tmp_path / "calls.log"
    bin_dir.mkdir()
    uv_dir.mkdir()
    write_script(bin_dir / "woodshed", f"echo \"woodshed $*\" >> '{log}'\nexit {woodshed_exit}")
    write_script(uv_dir / "uv", f"echo \"uv $*\" >> '{log}'")
    return bin_dir, uv_dir / "uv", log


def calls_of(log: Path) -> list[str]:
    return log.read_text(encoding="utf-8").splitlines() if log.exists() else []


def run_uninstall_script(script: Path, tmp_path: Path) -> subprocess.CompletedProcess[str]:
    env = {"PATH": os.environ.get("PATH", ""), "HOME": str(tmp_path), "WOODSHED_NO_PAUSE": "1"}
    return subprocess.run(["sh", str(script), "--yes"], env=env, capture_output=True, text=True, check=False)


@posix_only
@pytest.mark.parametrize("woodshed_exit", [0, 1])
def test_the_mac_uninstall_app_runs_woodshed_then_uv(tmp_path: Path, woodshed_exit: int) -> None:
    home = tmp_path / "home"
    home.mkdir()
    bin_dir, uv, log = uninstall_stubs(tmp_path, woodshed_exit)
    make = shell_function("sh_quote") + shell_function("uninstall_script") + shell_function("mac_uninstall_app")
    env = {"HOME": str(home), "PATH": os.environ.get("PATH", "")}
    for _ in range(2):  # installing again replaces the app
        subprocess.run(
            ["sh", "-c", make + 'mac_uninstall_app "$1" "$2"', "sh", str(bin_dir), str(uv)], env=env, check=True
        )

    contents = home / "Applications" / "Uninstall woodshed.app" / "Contents"
    info = plistlib.loads((contents / "Info.plist").read_bytes())
    from woodshed import uninstall

    assert info["CFBundleIdentifier"].startswith(uninstall.APP_ID)  # what woodshed uninstall recognises
    assert info["CFBundleName"] == "Uninstall woodshed" and info["CFBundlePackageType"] == "APPL"
    launcher, command = contents / "MacOS" / info["CFBundleExecutable"], contents / "Resources" / "uninstall.command"
    assert launcher.stat().st_mode & 0o111 and command.stat().st_mode & 0o111
    assert 'open -a Terminal "$(dirname "$0")/../Resources/uninstall.command"' in launcher.read_text(encoding="utf-8")

    proc = run_uninstall_script(command, tmp_path)
    if woodshed_exit == 0:
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert calls_of(log) == ["woodshed uninstall --keep-self --yes", *(f"uv {c[3:]}" for c in uninstall.LAST_STEP)]
    else:  # declined or refused: woodshed stays
        assert proc.returncode == 1
        assert calls_of(log) == ["woodshed uninstall --keep-self --yes"]
        assert "Nothing more was removed" in proc.stdout


@posix_only
@pytest.mark.parametrize("tools_env", ["WOODSHED_TOOLS", "XDG_DATA_HOME", ""])
def test_linux_gets_an_uninstall_menu_entry_and_its_script(tmp_path: Path, tools_env: str) -> None:
    from woodshed import uninstall

    home = tmp_path / "home"
    env = {"WOODSHED_NO_MENU": "0"}
    if tools_env == "WOODSHED_TOOLS":
        env["WOODSHED_TOOLS"] = str(tmp_path / "my tools")
        tools = tmp_path / "my tools"
    elif tools_env == "XDG_DATA_HOME":
        env["XDG_DATA_HOME"] = str(tmp_path / "data")
        tools = tmp_path / "data" / "woodshed" / "tools"
    else:
        tools = home / ".local" / "share" / "woodshed" / "tools"
    code, out, _ = run_install(tmp_path, "Linux", "x86_64", **env)
    assert code == 0, out
    apps = Path(env.get("XDG_DATA_HOME", home / ".local" / "share")) / "applications"
    entry = (apps / "woodshed-uninstall.desktop").read_text(encoding="utf-8")
    script = tools / "uninstall-woodshed.sh"
    assert "Name=Uninstall woodshed\n" in entry and "Terminal=true\n" in entry
    assert f'Exec=sh "{script}"\n' in entry
    # The same folder woodshed uninstall removes, so the script goes with it.
    os_env = {k: v for k, v in env.items() if k != "WOODSHED_NO_MENU"}
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("HOME", str(home))
        mp.delenv("WOODSHED_TOOLS", raising=False)
        mp.delenv("XDG_DATA_HOME", raising=False)
        for k, v in os_env.items():
            mp.setenv(k, v)
        assert uninstall.tools_dir("linux") == tools
    text = script.read_text(encoding="utf-8")
    assert f"'{tmp_path / 'b.in (x+y)'}/woodshed' uninstall --keep-self" in text
    assert f"'{tmp_path / 'stubs' / 'uv'}' tool uninstall woodshed" in text


@posix_only
def test_the_uninstall_script_survives_odd_folder_names(tmp_path: Path) -> None:
    bin_dir, uv, log = uninstall_stubs(tmp_path)
    script = tmp_path / "u.sh"
    make = shell_function("sh_quote") + shell_function("uninstall_script") + 'uninstall_script "$1" "$2" > "$3"'
    subprocess.run(["sh", "-c", make, "sh", str(bin_dir), str(uv), str(script)], check=True)
    proc = run_uninstall_script(script, tmp_path)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert calls_of(log)[0] == "woodshed uninstall --keep-self --yes"


def test_the_shortcuts_clean_the_same_packages_from_uv_cache_as_woodshed_says() -> None:
    from woodshed import uninstall

    clean = uninstall.LAST_STEP[1].removeprefix("uv ")
    assert clean.startswith("cache clean woodshed ") and "torch" in clean
    assert f") {clean} || true\n" in INSTALL_SH.read_text(encoding="utf-8")
    assert f"' {clean}')," in PS1.read_text(encoding="utf-8")


def test_the_windows_installer_registers_the_uninstall_woodshed_knows() -> None:
    from woodshed import uninstall

    text = PS1.read_text(encoding="utf-8")
    assert uninstall.UNINSTALL_KEY in text and uninstall.WINDOWS_SCRIPT in text
    assert '"Uninstall woodshed.lnk"' in text
    for value in (
        "DisplayName",
        "DisplayVersion",
        "DisplayIcon",
        "UninstallString",
        "EstimatedSize",
        "NoModify",
        "NoRepair",
        '"woodshed project"',
        "uninstall --keep-self",
        "tool uninstall woodshed",
        "reg delete",
    ):
        assert value in text, value
    # The tools folder as woodshed computes it on Windows.
    assert 'Join-Path $env:LOCALAPPDATA "woodshed\\tools"' in text and "$env:WOODSHED_TOOLS" in text


@posix_only
def test_uv_shows_its_cache_cleaning_in_the_uninstall_window(tmp_path: Path) -> None:
    # The cache lock can make uv wait for another uv: its own messages say so, nothing is hidden.
    bin_dir, uv, _ = uninstall_stubs(tmp_path)
    script = tmp_path / "u.sh"
    make = shell_function("sh_quote") + shell_function("uninstall_script") + 'uninstall_script "$1" "$2" > "$3"'
    subprocess.run(["sh", "-c", make, "sh", str(bin_dir), str(uv), str(script)], check=True)
    [line] = [ln for ln in script.read_text(encoding="utf-8").splitlines() if "cache clean" in ln]
    assert ">/dev/null" not in line
    out = run_uninstall_script(script, tmp_path).stdout
    assert "other Python programs may download them again" in out
    ps1 = [ln for ln in PS1.read_text(encoding="utf-8").splitlines() if "cache clean" in ln]
    assert ps1 and not [ln for ln in ps1 if ">nul" in ln]


def desktop_exec_args(value: str) -> list[str]:
    """An Exec value as a desktop environment reads it (Desktop Entry spec 1.5)."""
    unescaped = re.sub(r"\\(.)", lambda m: {"s": " ", "n": "\n", "t": "\t", "r": "\r"}.get(m[1], m[1]), value)
    args, i = [], 0
    while i < len(unescaped):
        if unescaped[i] == " ":
            i += 1
            continue
        if unescaped[i] == '"':
            i, arg = i + 1, ""
            while unescaped[i] != '"':
                if unescaped[i] == "\\":
                    assert unescaped[i + 1] in '"`$\\', f"a stray backslash in {value!r}"
                    i += 1
                else:
                    assert unescaped[i] not in "`$", f"{unescaped[i]} must be escaped in {value!r}"
                arg += unescaped[i]
                i += 1
            args.append(arg)
            i += 1
        else:
            end = unescaped.find(" ", i)
            end = len(unescaped) if end < 0 else end
            args.append(unescaped[i:end])
            i = end
    return [a.replace("%%", "%") for a in args]


@posix_only
@pytest.mark.parametrize("folder", ["/opt/jane/.local/bin", '/opt/a "b" $HOME `x` \\y 100%/bin'])
def test_the_menu_entries_quote_the_path_as_the_desktop_spec_says(folder: str) -> None:
    quote = shell_function("desktop_quote") + 'desktop_quote "$1"'
    quoted = subprocess.run(["sh", "-c", quote, "sh", f"{folder}/woodshed"], capture_output=True, text=True, check=True)
    assert desktop_exec_args(quoted.stdout + " app") == [f"{folder}/woodshed", "app"]


@posix_only
def test_install_sh_quotes_both_menu_entries(tmp_path: Path) -> None:
    code, out, _ = run_install(tmp_path, "Linux", "x86_64", WOODSHED_NO_MENU="0", WOODSHED_TOOLS=str(tmp_path / "t$x"))
    assert code == 0, out
    apps = tmp_path / "home" / ".local" / "share" / "applications"
    for name, args in (
        ("woodshed.desktop", [f"{tmp_path / 'b.in (x+y)'}/woodshed", "app"]),
        ("woodshed-uninstall.desktop", ["sh", f"{tmp_path / 't$x'}/uninstall-woodshed.sh"]),
    ):
        [line] = [ln for ln in (apps / name).read_text(encoding="utf-8").splitlines() if ln.startswith("Exec=")]
        assert desktop_exec_args(line.removeprefix("Exec=")) == args


def test_the_cmd_lines_in_install_ps1_are_whole_powershell_strings() -> None:
    # In PowerShell a ' inside '...' is written ''; one alone ends the string (and breaks the installer).
    text = PS1.read_text(encoding="utf-8")
    block = text[text.index("$Lines = @(") : text.index("\n    )\n", text.index("$Lines = @("))]
    quoted = [ln.strip() for ln in block.splitlines()[1:] if ln.strip().startswith("'")]
    assert len(quoted) > 20
    for line in quoted:
        assert re.fullmatch(r"'(?:[^']|'')*',?", line), line
