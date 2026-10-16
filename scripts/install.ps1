# Install woodshed on Windows, with nothing installed beforehand. In PowerShell:
#
#   powershell -ExecutionPolicy ByPass -c "irm https://raw.githubusercontent.com/laugiov/woodshed/main/scripts/install.ps1 | iex"
#
# It installs uv (Astral's Python installer, for your user) if it is missing, then woodshed in its own
# environment, with its own Python 3.13 and the CPU build of PyTorch (no GPU needed). If ffmpeg (only
# needed for AAC (M4A) and video files) is missing, it is installed with winget when winget is there.
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
        powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
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
