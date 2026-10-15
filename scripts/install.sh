#!/bin/sh
# Install woodshed on Linux or macOS, with nothing installed beforehand:
#
#   curl -LsSf https://raw.githubusercontent.com/laugiov/woodshed/main/scripts/install.sh | sh
#
# It installs uv (Astral's Python installer, in your home folder) if it is missing, then woodshed
# in its own environment, with its own Python 3.13 and the CPU build of PyTorch (no GPU needed).
# Nothing is installed system-wide and nothing needs sudo; uv adds its folder to your PATH.
# ffmpeg (to read MP3 and video files) is checked: the script says how to add it, it does not
# install system packages itself.
#
# Options, as environment variables:
#   WOODSHED_SOURCE   what to install (default: the latest version on GitHub)
#   WOODSHED_NO_MENU  set to 1 to skip the menu entry (Linux)
# Uninstall: uv tool uninstall woodshed

set -eu

SOURCE="${WOODSHED_SOURCE:-git+https://github.com/laugiov/woodshed}"
say() { printf '%s\n' "$*"; }

if ! command -v uv >/dev/null 2>&1; then
    say "Installing uv (https://docs.astral.sh/uv/) in your home folder..."
    if command -v curl >/dev/null 2>&1; then
        curl -LsSf https://astral.sh/uv/install.sh | sh
    else
        wget -qO- https://astral.sh/uv/install.sh | sh
    fi
    PATH="$HOME/.local/bin:$PATH"
    export PATH
    command -v uv >/dev/null 2>&1 || { say "uv could not be installed: see https://docs.astral.sh/uv/"; exit 1; }
fi

say "Installing woodshed (about 1.5 GB with PyTorch: a few minutes)..."
uv tool install --force --python 3.13 "woodshed[stems] @ $SOURCE"
uv tool update-shell >/dev/null 2>&1 || true
BIN="$(uv tool dir --bin)"

# A menu entry on Linux desktops: "woodshed" opens the library in the browser.
if [ "$(uname -s)" = "Linux" ] && [ "${WOODSHED_NO_MENU:-0}" != "1" ]; then
    apps="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
    mkdir -p "$apps"
    cat > "$apps/woodshed.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=woodshed
Comment=Your songs as practice rooms for the band
Exec="$BIN/woodshed" app
Terminal=true
Categories=AudioVideo;Audio;Music;
EOF
    say "Menu entry added: woodshed."
fi

say ""
say "woodshed is installed: $("$BIN/woodshed" --version)"
if ! command -v ffmpeg >/dev/null 2>&1; then
    say ""
    say "One more thing: ffmpeg reads MP3, AAC and video files (WAV and FLAC work without it)."
    if [ "$(uname -s)" = "Darwin" ]; then
        say "  brew install ffmpeg"
    elif command -v apt-get >/dev/null 2>&1; then
        say "  sudo apt install ffmpeg"
    elif command -v dnf >/dev/null 2>&1; then
        say "  sudo dnf install ffmpeg"
    elif command -v pacman >/dev/null 2>&1; then
        say "  sudo pacman -S ffmpeg"
    else
        say "  install it with your system's package manager"
    fi
fi
say ""
say "Start it with:  woodshed app        (open a new terminal first if the command is not found)"
say "Or one song:    woodshed song.mp3"
