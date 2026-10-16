@echo off
rem Double-click to install woodshed on Windows. It downloads scripts/install.ps1 from GitHub and runs
rem it (it also adds woodshed to the Start menu), then starts woodshed. WOODSHED_REF is also how a
rem release installs its own version: scripts/package-installers.sh sets its default below to the tag.
rem
rem Options, as environment variables (for tests):
rem   WOODSHED_REF             the branch, version tag or commit to install (default: below)
rem   WOODSHED_INSTALL_SCRIPT  a local install.ps1 to run, instead of the one on GitHub
rem   WOODSHED_SOURCE          what install.ps1 installs (see there)
rem   WOODSHED_NO_OPEN         set to 1 to not start woodshed at the end
rem   WOODSHED_NO_PAUSE        set to 1 to not wait for a key at the end
setlocal
if not defined WOODSHED_REF set "WOODSHED_REF=main"
title Installing woodshed
echo Installing woodshed
echo -------------------
echo.
echo This puts woodshed on this computer, for you only:
echo   - its own copy of Python and of the music models' software (about 1.5 GB to download,
echo     a few minutes: leave this window open until it says "Done"),
echo   - woodshed in the Start menu.
echo No administrator rights needed.
echo.

set "WOODSHED_DOWNLOADED="
if defined WOODSHED_INSTALL_SCRIPT goto :run
set "WOODSHED_INSTALL_SCRIPT=%TEMP%\woodshed-install.ps1"
set "WOODSHED_DOWNLOADED=1"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference = 'Stop'; [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor 3072; irm ('https://raw.githubusercontent.com/laugiov/woodshed/' + $env:WOODSHED_REF + '/scripts/install.ps1') -OutFile $env:WOODSHED_INSTALL_SCRIPT"
if errorlevel 1 goto :failed
:run
powershell -NoProfile -ExecutionPolicy Bypass -File "%WOODSHED_INSTALL_SCRIPT%"
if errorlevel 1 goto :failed
if defined WOODSHED_DOWNLOADED del "%WOODSHED_INSTALL_SCRIPT%"

echo.
echo Done: woodshed is installed.
if "%WOODSHED_NO_OPEN%"=="1" goto :next
echo woodshed starts now in a new window, and opens your library in the browser.
powershell -NoProfile -Command "$l = Join-Path ([Environment]::GetFolderPath('Programs')) 'woodshed.lnk'; if (Test-Path $l) { Start-Process $l }"
:next
echo.
echo You can close this window.
echo Next time, start woodshed from the Start menu: type woodshed.
call :pause
exit /b 0

:failed
if defined WOODSHED_DOWNLOADED del "%WOODSHED_INSTALL_SCRIPT%" 2>nul
echo.
echo The installation stopped: the messages above say why.
echo Once that is sorted, double-click the installer again,
echo or ask for help: https://github.com/laugiov/woodshed/issues
call :pause
exit /b 1

:pause
if not "%WOODSHED_NO_PAUSE%"=="1" pause
exit /b 0
