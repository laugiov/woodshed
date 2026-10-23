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
#   WOODSHED_NO_MENU    set to 1 to skip the Start menu shortcuts
#   WOODSHED_TOOLS      woodshed's tools folder (the uninstall script goes there)
# Uninstall: "Uninstall woodshed" in the Start menu, or woodshed in Settings > Apps.

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
        # It runs (`-V`): Smart App Control or an antivirus may refuse the unsigned files. A .NET process, since
        # Windows PowerShell stops on a native program's stderr under "Stop".
        $runs = {
            param($file)
            try {
                $info = [Diagnostics.ProcessStartInfo]::new()
                $info.FileName = $file
                $info.Arguments = "-V"
                $info.UseShellExecute = $false
                $info.CreateNoWindow = $true
                $info.RedirectStandardInput = $true
                $info.RedirectStandardOutput = $true
                $info.RedirectStandardError = $true
                $child = [Diagnostics.Process]::Start($info)
                $child.StandardInput.Close()
                $null = $child.StandardError.ReadToEnd()
                $null = $child.StandardOutput.ReadToEnd()
                if (-not $child.WaitForExit(20000)) { $child.Kill(); return $false }
                return $child.ExitCode -eq 0
            } catch { return $false }
        }
        $exe = [IO.Path]::Combine($Tools, "rubberband.exe")
        $dll = [IO.Path]::Combine($Tools, "sndfile.dll")
        # Skipped only when it is this program and it runs: one the system blocks is fetched (and said) again.
        if ((& $same $exe $ExeSha256) -and (& $same $dll $DllSha256) -and (& $runs $exe)) { return $true }
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
        if (-not (& $runs $exe)) {
            Write-Host "The recording in your key is off: Rubber Band is installed but this computer blocks it. Allow it in Windows Security (or your antivirus), then restart woodshed."
            return $false
        }
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

# Uninstall woodshed (spec 018), self-contained: a small .cmd in woodshed's tools folder (as woodshed computes
# it, uninstall.tools_dir) runs "woodshed uninstall --keep-self" (it asks first, then removes the cache, the
# tools and the shortcuts), then uv removes woodshed once it has exited, then the Settings entry goes and the
# .cmd deletes itself. The Start menu's "Uninstall woodshed" and Settings > Apps run it. No administrator rights.
function Add-WoodshedUninstall([string]$Exe, [bool]$Menu) {
    $Key = "Software\Microsoft\Windows\CurrentVersion\Uninstall\woodshed"
    $Uv = (Get-Command uv).Source
    $Own = -not $env:WOODSHED_TOOLS
    $Tools = if ($Own) { Join-Path $env:LOCALAPPDATA "woodshed\tools" } else { $env:WOODSHED_TOOLS }
    New-Item -ItemType Directory -Force -Path $Tools | Out-Null
    $Script = Join-Path $Tools "uninstall-woodshed.cmd"
    # In the .cmd, the user's folders by name (%LOCALAPPDATA%...): its text stays ASCII whatever the user's name.
    $InCmd = {
        param([string]$Path)
        $Path = $Path -replace "%", "%%"
        foreach ($Var in "LOCALAPPDATA", "USERPROFILE") {
            $Value = [Environment]::GetEnvironmentVariable($Var)
            if ($Value -and $Path.StartsWith($Value, [StringComparison]::OrdinalIgnoreCase)) {
                return '"%' + $Var + '%' + $Path.Substring($Value.Length) + '"'
            }
        }
        '"' + $Path + '"'
    }
    # The last line deletes the .cmd itself ((goto) first, so cmd does not read on), then its folder if empty,
    # and woodshed's own data folder if empty (only the default one: a chosen folder's parent is not ours).
    $Last = '(goto) 2>nul & del "%~f0" & rd "%~dp0." 2>nul'
    if ($Own) { $Last += ' & rd "%~dp0.." 2>nul' }
    $Lines = @(
        '@echo off',
        'rem Made by the woodshed installer: removes woodshed from this computer, asking first. Your songs stay.',
        'setlocal',
        'title Uninstall woodshed',
        'cd /d "%USERPROFILE%"',
        'echo Uninstall woodshed',
        'echo ------------------',
        'echo.',
        ((& $InCmd $Exe) + ' uninstall --keep-self %*'),
        'if errorlevel 1 goto :stopped',
        'echo.',
        'echo Removing woodshed itself...',
        ((& $InCmd $Uv) + ' tool uninstall woodshed'),
        'if errorlevel 1 goto :failed',
        ((& $InCmd $Uv) + ' cache prune >nul 2>&1'),
        ('reg delete "HKCU\' + $Key + '" /f >nul 2>&1'),
        'echo.',
        'echo woodshed is removed. Your songs stay where they are.',
        'if not "%WOODSHED_NO_PAUSE%"=="1" pause',
        $Last,
        ':stopped',
        'echo.',
        'echo Nothing more was removed.',
        'goto :end',
        ':failed',
        'echo woodshed itself could not be removed: the message above says why.',
        ':end',
        'if not "%WOODSHED_NO_PAUSE%"=="1" pause',
        'exit /b 1'
    )
    # cmd.exe reads labels right only with Windows line endings.
    [IO.File]::WriteAllText($Script, (($Lines -join "`r`n") + "`r`n"), [Text.Encoding]::ASCII)

    if ($Menu) {
        $Programs = [Environment]::GetFolderPath("Programs")
        $Link = (New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $Programs "Uninstall woodshed.lnk"))
        $Link.TargetPath = $Script
        $Link.WorkingDirectory = $env:USERPROFILE  # not the tools folder, which the .cmd removes
        $Link.Description = "Remove woodshed from this computer (your songs stay)"
        $Link.Save()
    }

    # Settings > Apps: the key goes last, in the .cmd, once woodshed is removed.
    $Version = ((& $Exe --version) -replace "^woodshed\s+", "").Trim()
    $ToolEnv = Join-Path (uv tool dir).Trim() "woodshed"
    $Size = 0
    if (Test-Path $ToolEnv) { $Size = [int](((Get-ChildItem -Recurse -File -Force $ToolEnv | Measure-Object Length -Sum).Sum) / 1KB) }
    $Path = "HKCU:\$Key"
    New-Item -Path $Path -Force | Out-Null
    $Strings = @{
        DisplayName = "woodshed"; DisplayVersion = $Version; Publisher = "woodshed project"
        UninstallString = ('"' + $Script + '"'); DisplayIcon = $Exe
        URLInfoAbout = "https://github.com/laugiov/woodshed"
    }
    foreach ($Name in $Strings.Keys) { New-ItemProperty -Path $Path -Name $Name -Value $Strings[$Name] -PropertyType String -Force | Out-Null }
    $Numbers = @{ NoModify = 1; NoRepair = 1; EstimatedSize = $Size }
    foreach ($Name in $Numbers.Keys) { New-ItemProperty -Path $Path -Name $Name -Value $Numbers[$Name] -PropertyType DWord -Force | Out-Null }
}
Add-WoodshedUninstall $Exe ($env:WOODSHED_NO_MENU -ne "1")
Write-Host "Uninstall woodshed added: in the Start menu and in Settings > Apps (to remove it one day; your songs stay)."

Write-Host ""
Write-Host ("woodshed is installed: " + (& $Exe --version))
Write-Host ""
Write-Host "Start it from the Start menu (woodshed), or in a new terminal:  woodshed app"
Write-Host "One song:  woodshed song.mp3"
