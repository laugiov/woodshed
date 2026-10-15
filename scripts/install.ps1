# Install woodshed on Windows, with nothing installed beforehand. In PowerShell:
#
#   powershell -ExecutionPolicy ByPass -c "irm https://raw.githubusercontent.com/laugiov/woodshed/main/scripts/install.ps1 | iex"
#
# It installs uv (Astral's Python installer, for your user) if it is missing, then woodshed in its own
# environment, with its own Python 3.13 and the CPU build of PyTorch (no GPU needed). If ffmpeg (to
# read MP3 and video files) is missing, it is installed with winget when winget is there. A Start
# menu shortcut "woodshed" opens the library in the browser. No administrator rights needed.
#
# Options, as environment variables:
#   WOODSHED_SOURCE     what to install (default: the latest version on GitHub)
#   WOODSHED_NO_FFMPEG  set to 1 to leave ffmpeg alone
#   WOODSHED_NO_MENU    set to 1 to skip the Start menu shortcut
# Uninstall: uv tool uninstall woodshed

$ErrorActionPreference = "Stop"

$Source = if ($env:WOODSHED_SOURCE) { $env:WOODSHED_SOURCE } else { "git+https://github.com/laugiov/woodshed" }

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "Installing uv (https://docs.astral.sh/uv/) for your user..."
    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    if ($LASTEXITCODE -ne 0) { throw "uv could not be installed: see https://docs.astral.sh/uv/" }
    $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
}

Write-Host "Installing woodshed (about 1.5 GB with PyTorch: a few minutes)..."
uv tool install --force --python 3.13 "woodshed[stems] @ $Source"
if ($LASTEXITCODE -ne 0) { throw "woodshed could not be installed (see the messages above)" }
uv tool update-shell | Out-Null
$Bin = (uv tool dir --bin).Trim()
$Exe = Join-Path $Bin "woodshed.exe"

if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue) -and $env:WOODSHED_NO_FFMPEG -ne "1") {
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Write-Host "Installing ffmpeg with winget (it reads MP3, AAC and video files)..."
        winget install --id Gyan.FFmpeg --exact --silent --accept-source-agreements --accept-package-agreements
        if ($LASTEXITCODE -ne 0) { Write-Host "ffmpeg could not be installed with winget: get it from https://ffmpeg.org/download.html" }
        else { Write-Host "ffmpeg is installed: it is found in new terminals and after signing in again." }
    } else {
        Write-Host "ffmpeg reads MP3, AAC and video files (WAV and FLAC work without it): get it from https://ffmpeg.org/download.html"
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
