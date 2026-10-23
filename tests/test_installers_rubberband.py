"""The installers fetch the Rubber Band program on Mac and Windows (spec 017): its pinned checksum, the tools
folder, a skip when it is already there, and never a failed install. Served from a local HTTP server: nothing
is downloaded from the internet here (the CI's macOS and Windows jobs fetch the real one)."""

from __future__ import annotations

import functools
import hashlib
import http.server
import io
import os
import re
import shutil
import subprocess
import tarfile
import threading
import zipfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.test_installers import INSTALL_SH, posix_only, run_install, shell_function

ROOT = Path(__file__).resolve().parents[1]
INSTALL_PS1 = ROOT / "scripts" / "install.ps1"
MAC = "rubberband-4.0.0-gpl-executable-macos"
WINDOWS = "rubberband-4.0.0-gpl-executable-windows"
OFF = "The recording in your key is off"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        pass


@pytest.fixture
def served(tmp_path: Path) -> Iterator[tuple[Path, str]]:
    """A folder served over HTTP on this machine, and its URL."""
    folder = tmp_path / "www"
    folder.mkdir()
    handler = functools.partial(Quiet, directory=str(folder))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield folder, f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def mac_archive(folder: Path) -> tuple[str, str, bytes]:
    """An archive laid out as breakfastquay.com's macOS one: its name, its checksum, the program's bytes."""
    program = b"#!/bin/sh\necho 4.0.0 >&2\n"
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:bz2") as tar:
        for name, data in (("rubberband", program), ("COPYING", b"GPL"), ("rubberband-r3", b"other")):
            info = tarfile.TarInfo(f"{MAC}/{name}")
            info.size, info.mode = len(data), 0o755
            tar.addfile(info, io.BytesIO(data))
    (folder / f"{MAC}.tar.bz2").write_bytes(buffer.getvalue())
    return f"{MAC}.tar.bz2", sha256(buffer.getvalue()), program


def get_rubberband(tmp_path: Path, *args: str) -> tuple[int, str]:
    """install.sh's get_rubberband, run alone, into tmp_path/tools."""
    script = shell_function("get_rubberband") + 'get_rubberband "$@"\n'
    env = {**os.environ, "HOME": str(tmp_path / "home"), "WOODSHED_TOOLS": str(tmp_path / "tools")}
    proc = subprocess.run(["sh", "-c", script, "sh", *args], env=env, capture_output=True, text=True, check=False)
    return proc.returncode, proc.stdout + proc.stderr


@posix_only
def test_the_mac_download_is_checked_and_put_in_the_tools_folder(tmp_path: Path, served: tuple[Path, str]) -> None:
    folder, url = served
    name, checksum, program = mac_archive(folder)
    code, out = get_rubberband(tmp_path, f"{url}/{name}", checksum, sha256(program))
    assert code == 0, out
    tools = tmp_path / "tools"
    assert (tools / "rubberband").read_bytes() == program and os.access(tools / "rubberband", os.X_OK)
    assert (tools / "COPYING").read_bytes() == b"GPL"  # the licence next to the program
    assert sorted(p.name for p in tools.iterdir()) == ["COPYING", "rubberband"]  # nothing else, no leftover
    assert OFF not in out


@posix_only
def test_a_tampered_download_is_refused_and_the_install_goes_on(tmp_path: Path, served: tuple[Path, str]) -> None:
    folder, url = served
    name, checksum, program = mac_archive(folder)
    with open(folder / name, "ab") as archive:
        archive.write(b"\0")  # one byte more: not the archive the checksum names
    code, out = get_rubberband(tmp_path, f"{url}/{name}", checksum, sha256(program))
    assert code == 0  # never a failed install
    assert OFF in out and len([line for line in out.splitlines() if line.strip()]) == 1  # one line says so
    assert not (tmp_path / "tools" / "rubberband").exists()


@posix_only
def test_a_program_already_there_is_kept_and_a_wrong_one_replaced(tmp_path: Path, served: tuple[Path, str]) -> None:
    folder, url = served
    name, checksum, program = mac_archive(folder)
    assert get_rubberband(tmp_path, f"{url}/{name}", checksum, sha256(program))[0] == 0
    (folder / name).unlink()  # gone from the server: only a skip can succeed now
    code, out = get_rubberband(tmp_path, f"{url}/{name}", checksum, sha256(program))
    assert code == 0 and OFF not in out
    (tmp_path / "tools" / "rubberband").write_bytes(b"something else")
    mac_archive(folder)
    assert get_rubberband(tmp_path, f"{url}/{name}", checksum, sha256(program))[0] == 0
    assert (tmp_path / "tools" / "rubberband").read_bytes() == program


@posix_only
def test_the_pinned_release_is_the_official_one() -> None:
    script = shell_function("get_rubberband")
    assert f"https://breakfastquay.com/files/releases/{MAC}.tar.bz2" in script
    assert "0dc91509a31a94c1144436cc20e6f1d165bdab39fe125f9be7d46139921b733f" in script  # verified 2026-10-23
    ps1 = INSTALL_PS1.read_text(encoding="utf-8")
    assert f"https://breakfastquay.com/files/releases/{WINDOWS}.zip" in ps1
    assert "f2d47fc64dbb42f6cc62edf7933ac4fa89d8f0ef8b9cf97b6afc263a7fe05644" in ps1


@posix_only
def test_a_mac_install_fetches_it_and_a_failed_fetch_does_not_fail_the_install(tmp_path: Path) -> None:
    # curl is a stub that fails here: the install completes and says the key is off and how to add it.
    code, out, _ = run_install(tmp_path, "Darwin", "arm64", "1")
    assert code == 0, out
    assert OFF in out and "installer again" in out


@posix_only
def test_linux_does_not_fetch_it_and_names_the_package_that_has_the_filter(tmp_path: Path) -> None:
    code, out, _ = run_install(tmp_path, "Linux", "x86_64")
    assert code == 0, out
    assert "Rubber Band" not in out and OFF not in out
    # Without ffmpeg, the advice names what it brings: the M4A files and the recording in your key.
    text = INSTALL_SH.read_text(encoding="utf-8")
    assert re.search(r"recording in your key.*\n(.*\n){0,6}.*sudo apt install ffmpeg", text)


# PowerShell (the Windows CI job; skipped where there is no PowerShell).

POWERSHELL = shutil.which("pwsh") or shutil.which("powershell")


def windows_zip(folder: Path) -> tuple[str, str, bytes, bytes]:
    exe, dll = b"MZ fake rubberband", b"MZ fake sndfile"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        for name, data in (("rubberband.exe", exe), ("sndfile.dll", dll), ("COPYING.txt", b"GPL"), ("README.txt", b"")):
            z.writestr(f"{WINDOWS}/{name}", data)
    (folder / f"{WINDOWS}.zip").write_bytes(buffer.getvalue())
    return f"{WINDOWS}.zip", sha256(buffer.getvalue()), exe, dll


def get_rubberband_ps(tmp_path: Path, url: str, checksum: str, exe: bytes, dll: bytes) -> tuple[str, str]:
    assert POWERSHELL is not None
    call = (
        f". '{INSTALL_PS1}'; "
        f"$ok = Get-Rubberband -Tools '{tmp_path / 'tools'}' -Url '{url}' -Sha256 '{checksum}' "
        f"-ExeSha256 '{sha256(exe)}' -DllSha256 '{sha256(dll)}'; Write-Output \"result=$ok\""
    )
    proc = subprocess.run(
        [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", call],
        capture_output=True, text=True, check=False, timeout=120,
    )  # fmt: skip
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return proc.stdout, proc.stderr


@pytest.mark.skipif(POWERSHELL is None, reason="needs PowerShell")
def test_the_windows_download_is_checked_and_put_in_the_tools_folder(tmp_path: Path, served: tuple[Path, str]) -> None:
    folder, url = served
    name, checksum, exe, dll = windows_zip(folder)
    out, _ = get_rubberband_ps(tmp_path, f"{url}/{name}", checksum, exe, dll)
    assert "result=True" in out, out
    tools = tmp_path / "tools"
    assert (tools / "rubberband.exe").read_bytes() == exe and (tools / "sndfile.dll").read_bytes() == dll
    assert (tools / "COPYING.txt").read_bytes() == b"GPL"
    (folder / name).unlink()  # already there: a skip, no download
    out, _ = get_rubberband_ps(tmp_path, f"{url}/{name}", checksum, exe, dll)
    assert "result=True" in out and OFF not in out, out


@pytest.mark.skipif(POWERSHELL is None, reason="needs PowerShell")
def test_a_tampered_windows_download_is_refused(tmp_path: Path, served: tuple[Path, str]) -> None:
    folder, url = served
    name, checksum, exe, dll = windows_zip(folder)
    with open(folder / name, "ab") as archive:
        archive.write(b"\0")
    out, _ = get_rubberband_ps(tmp_path, f"{url}/{name}", checksum, exe, dll)
    assert "result=False" in out and OFF in out, out
    assert not (tmp_path / "tools" / "rubberband.exe").exists()


@pytest.mark.skipif(POWERSHELL is None, reason="needs PowerShell")
def test_whatever_goes_wrong_the_windows_function_says_one_line_and_returns(tmp_path: Path) -> None:
    assert POWERSHELL is not None
    bad = f"{tmp_path}{os.sep}a|b"  # a folder name Windows refuses: the first file call throws
    call = f". '{INSTALL_PS1}'; $ok = Get-Rubberband -Tools '{bad}' -Url 'http://127.0.0.1:9/x'; "
    call += 'Write-Output "result=$ok"'
    proc = subprocess.run(
        [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", call],
        capture_output=True, text=True, check=False, timeout=120,
    )  # fmt: skip
    assert proc.returncode == 0 and "result=False" in proc.stdout and OFF in proc.stdout, proc.stdout + proc.stderr


def test_the_windows_install_never_stops_on_rubber_band() -> None:
    # Windows PowerShell 5.1 started from PowerShell 7 finds no script-defined cmdlet (Get-FileHash stopped an
    # install that way): .NET only, and the call itself in a try whose catch says one line.
    text = INSTALL_PS1.read_text(encoding="utf-8")
    for cmdlet in ("Get-FileHash", "Expand-Archive", "ForEach-Object", "Select-Object", "Get-ChildItem"):
        assert cmdlet not in text, cmdlet
    body = text[text.index("function Get-Rubberband") :]
    assert "[CmdletBinding()]" in body[:100]  # -ErrorAction at the call needs it
    calls = [line.strip() for line in text.splitlines() if "Get-Rubberband" in line and "function" not in line]
    call = [line for line in calls if not line.startswith("#")]
    assert call == ["try { $null = Get-Rubberband -ErrorAction Stop }"], calls
    after = text[text.index(call[0]) :].splitlines()[1].strip()
    assert after.startswith("catch { Write-Host") and OFF in after


def test_the_windows_script_can_be_loaded_for_its_functions_alone() -> None:
    # CI dot-sources install.ps1 to run Get-Rubberband: loaded that way it must stop before installing anything.
    text = INSTALL_PS1.read_text(encoding="utf-8")
    guard = text.index("$MyInvocation.InvocationName -eq '.'")
    assert text.index("function Get-Rubberband") < guard < text.index("uv tool install")
