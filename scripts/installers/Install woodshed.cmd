@echo off
rem Double-click to install woodshed on Windows. It runs scripts/install.ps1 (from GitHub), which
rem also adds woodshed to the Start menu, then starts woodshed.
rem
rem Options, as environment variables (for tests):
rem   WOODSHED_SOURCE    a local checkout to install from, instead of GitHub
rem   WOODSHED_NO_OPEN   set to 1 to not start woodshed at the end
rem   WOODSHED_NO_PAUSE  set to 1 to not wait for a key at the end
setlocal
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

set "WOODSHED_SCRIPT="
if defined WOODSHED_SOURCE if exist "%WOODSHED_SOURCE%\scripts\install.ps1" set "WOODSHED_SCRIPT=%WOODSHED_SOURCE%\scripts\install.ps1"
if defined WOODSHED_SCRIPT goto :local
powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://raw.githubusercontent.com/laugiov/woodshed/main/scripts/install.ps1 | iex"
goto :installed
:local
powershell -NoProfile -ExecutionPolicy Bypass -File "%WOODSHED_SCRIPT%"
:installed
if errorlevel 1 goto :failed

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
echo.
echo The installation stopped: the messages above say why.
echo Check your internet connection and double-click the installer again,
echo or ask for help: https://github.com/laugiov/woodshed/issues
call :pause
exit /b 1

:pause
if not "%WOODSHED_NO_PAUSE%"=="1" pause
exit /b 0
