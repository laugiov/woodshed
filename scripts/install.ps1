# Install woodshed on Windows, with nothing installed beforehand. In PowerShell:
#
#   powershell -ExecutionPolicy ByPass -c "irm https://raw.githubusercontent.com/laugiov/woodshed/main/scripts/install.ps1 | iex"
#
# It installs uv (Astral's Python installer, for your user) if it is missing, then woodshed in its own
# environment, with its own Python 3.13 and the CPU build of PyTorch (no GPU needed). If ffmpeg (only
# needed for AAC (M4A) and video files) is missing, it is installed with winget when winget is there.
# The Rubber Band program (for the recording in your key) goes in woodshed's tools folder.
# A Start menu shortcut "woodshed" opens the library in the browser. No administrator rights needed.
# Double-click instead: scripts/installers/Install woodshed.cmd runs this script.
#
# Options, as environment variables:
#   WOODSHED_SOURCE     what to install (default: the version WOODSHED_REF names, on GitHub)
#   WOODSHED_REF        a branch or a version tag on GitHub (default: main)
#   WOODSHED_NO_FFMPEG  set to 1 to leave ffmpeg alone
#   WOODSHED_NO_MENU    set to 1 to skip the Start menu shortcut
# Uninstall: uv tool uninstall woodshed

$ErrorActionPreference = "Stop"
# TLS 1.2 for the downloads: older Windows PowerShell setups do not offer it by default.
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor 3072

# The singer's key (spec 017): the Rubber Band program in woodshed's tools folder, the official GPL build from
# breakfastquay.com (with libsndfile's sndfile.dll and the licence), checked against its pinned sha256. A
# separate program woodshed runs, never linked. Skipped when the files there are already these; a failed
# download says so in one line and never fails the install. True when the program is there.
function Get-Rubberband {
    [CmdletBinding()]
    param(
        [string]$Tools = "",
        [string]$Url = "https://breakfastquay.com/files/releases/rubberband-4.0.0-gpl-executable-windows.zip",
        [string]$Sha256 = "f2d47fc64dbb42f6cc62edf7933ac4fa89d8f0ef8b9cf97b6afc263a7fe05644",
        [string]$ExeSha256 = "d26d81e20f48ea33070e638f58bdeb6a61ce7f0946d8f2629f30441caa2905d1",
        [string]$DllSha256 = "4e3bd2de8e1485110eaebef8e1239471f73d608773831c323bf528e05645655e"
    )
    # .NET only for hashes, archives and files: Windows PowerShell 5.1 started from PowerShell 7 (its module
    # path inherited) cannot load the script-defined cmdlets for them.
    $ErrorActionPreference = "Stop"  # every failure caught below, also when loaded alone (CI)
    $ProgressPreference = "SilentlyContinue"  # Windows PowerShell's progress bar slows a download tenfold
    $tmp = $null
    try {
        if (-not $Tools) {
            $Tools = if ($env:WOODSHED_TOOLS) { $env:WOODSHED_TOOLS } else { [IO.Path]::Combine($env:LOCALAPPDATA, "woodshed", "tools") }
        }
        $same = {
            param($file, $sum)
            if (-not [IO.File]::Exists($file)) { return $false }
            $sha = [Security.Cryptography.SHA256]::Create()
            $stream = [IO.File]::OpenRead($file)
            try { $hex = [BitConverter]::ToString($sha.ComputeHash($stream)).Replace("-", "").ToLowerInvariant() }
            finally { $stream.Dispose(); $sha.Dispose() }
            return $hex -eq $sum.ToLowerInvariant()
        }
        $exe = [IO.Path]::Combine($Tools, "rubberband.exe")
        $dll = [IO.Path]::Combine($Tools, "sndfile.dll")
        if ((& $same $exe $ExeSha256) -and (& $same $dll $DllSha256)) { return $true }
        $tmp = [IO.Path]::Combine([IO.Path]::GetTempPath(), "woodshed-rubberband-" + [Guid]::NewGuid().ToString("N"))
        [void][IO.Directory]::CreateDirectory($tmp)
        $zip = [IO.Path]::Combine($tmp, "rubberband.zip")
        Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $zip -TimeoutSec 300
        if (-not (& $same $zip $Sha256)) { throw "not the archive its checksum names" }
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        $out = [IO.Path]::Combine($tmp, "x")
        [IO.Compression.ZipFile]::ExtractToDirectory($zip, $out)
        $dir = [IO.Directory]::GetDirectories($out)[0]
        $from = @{ exe = [IO.Path]::Combine($dir, "rubberband.exe"); dll = [IO.Path]::Combine($dir, "sndfile.dll") }
        if (-not ((& $same $from.exe $ExeSha256) -and (& $same $from.dll $DllSha256))) { throw "not the files the checksums name" }
        [void][IO.Directory]::CreateDirectory($Tools)
        [IO.File]::Copy([IO.Path]::Combine($dir, "COPYING.txt"), [IO.Path]::Combine($Tools, "COPYING.txt"), $true)
        [IO.File]::Copy($from.dll, $dll, $true)
        [IO.File]::Copy($from.exe, $exe, $true)
        Write-Host "The recording in your key: Rubber Band is ready."
        return $true
    } catch {
        Write-Host "The recording in your key is off: Rubber Band could not be downloaded. Run the installer again later to add it."
        return $false
    } finally {
        if ($tmp) { try { [IO.Directory]::Delete($tmp, $true) } catch { } }
    }
}
# Loaded with ". install.ps1" (CI), only the functions above: nothing is installed. ("irm | iex" has no
# script path: it always installs.)
if ($MyInvocation.InvocationName -eq '.' -and $PSCommandPath) { return }

$Ref = if ($env:WOODSHED_REF) { $env:WOODSHED_REF } else { "main" }
# A plain archive: git is not needed, and PyPI's PyTorch is the CPU build on Windows.
$Source = if ($env:WOODSHED_SOURCE) { $env:WOODSHED_SOURCE } else { "https://github.com/laugiov/woodshed/archive/$Ref.zip" }
# Windows on ARM: the x64 Python (Windows 11 emulates it), since not every part has an ARM build.
$Arm = $env:PROCESSOR_ARCHITECTURE -eq "ARM64" -or $env:PROCESSOR_ARCHITEW6432 -eq "ARM64"
$Python = if ($Arm) { "cpython-3.13-windows-x86_64-none" } else { "3.13" }

# Programs print their progress on stderr, which Windows PowerShell takes for errors when the output
# is redirected (as in CI): those must not stop the script, the exit code says.
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "Installing uv (https://docs.astral.sh/uv/) for your user..."
    & {
        $ErrorActionPreference = "Continue"
        powershell -ExecutionPolicy ByPass -c "[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor 3072; irm https://astral.sh/uv/install.ps1 | iex"
    }
    if ($LASTEXITCODE -ne 0) { throw "uv could not be installed: see https://docs.astral.sh/uv/" }
    $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
}

# Replacing woodshed while it runs would fail (Windows keeps running programs' files locked).
if (Get-Process woodshed -ErrorAction SilentlyContinue) {
    throw "woodshed is running: close woodshed first (its window), then run the installer again."
}

Write-Host "Installing woodshed (about 1.5 GB with PyTorch: a few minutes)..."
& {
    $ErrorActionPreference = "Continue"
    uv tool install --force --refresh-package woodshed --python $Python "woodshed[stems] @ $Source"
}
if ($LASTEXITCODE -ne 0) { throw "woodshed could not be installed (see the messages above)" }
& { $ErrorActionPreference = "Continue"; uv tool update-shell *> $null }
$Bin = (uv tool dir --bin).Trim()
$Exe = Join-Path $Bin "woodshed.exe"

if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue) -and $env:WOODSHED_NO_FFMPEG -ne "1") {
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Write-Host "Installing ffmpeg with winget (only needed for AAC (M4A) and video files; MP3 works without it)..."
        & {
            $ErrorActionPreference = "Continue"
            winget install --id Gyan.FFmpeg --exact --silent --accept-source-agreements --accept-package-agreements
        }
        if ($LASTEXITCODE -ne 0) { Write-Host "ffmpeg could not be installed with winget (woodshed works without it, MP3 included): get it from https://ffmpeg.org/download.html" }
        else { Write-Host "ffmpeg is installed: it is found in new terminals and after signing in again." }
    } else {
        Write-Host "MP3, WAV, FLAC and Ogg files work as they are. For AAC (M4A) and video files, add ffmpeg: https://ffmpeg.org/download.html"
    }
}

# Never a failed install: whatever Get-Rubberband meets, one line, and the install goes on.
try { $null = Get-Rubberband -ErrorAction Stop }
catch { Write-Host "The recording in your key is off: Rubber Band could not be added. Run the installer again later to add it." }

if ($env:WOODSHED_NO_MENU -ne "1") {
    $Programs = [Environment]::GetFolderPath("Programs")
    $Shell = New-Object -ComObject WScript.Shell
    $Link = $Shell.CreateShortcut((Join-Path $Programs "woodshed.lnk"))
    $Link.TargetPath = $Exe
    $Link.Arguments = "app"
    $Link.Description = "Your songs as practice rooms for the band"
    $Link.Save()
    Write-Host "Start menu shortcut added: woodshed."
}

Write-Host ""
Write-Host ("woodshed is installed: " + (& $Exe --version))
Write-Host ""
Write-Host "Start it from the Start menu (woodshed), or in a new terminal:  woodshed app"
Write-Host "One song:  woodshed song.mp3"
