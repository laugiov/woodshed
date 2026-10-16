#!/bin/sh
# Install woodshed on Linux or macOS, with nothing installed beforehand:
#
#   curl -LsSf https://raw.githubusercontent.com/laugiov/woodshed/main/scripts/install.sh | sh
#
# It installs uv (Astral's Python installer, in your home folder) if it is missing, then woodshed
# in its own environment, with its own Python and the CPU build of PyTorch (no GPU needed).
# Nothing is installed system-wide and nothing needs sudo; uv adds its folder to your PATH.
# On Linux it adds a menu entry, on macOS an app (~/Applications/woodshed.app). ffmpeg is only
# needed for AAC (M4A) and video files: the script says how to add it, it does not install it.
#
# Options, as environment variables:
#   WOODSHED_SOURCE   what to install (default: the latest version on GitHub)
#   WOODSHED_NO_MENU  set to 1 to skip the menu entry (Linux) or the app (macOS)
# Uninstall: uv tool uninstall woodshed (and remove the menu entry or the app)

set -eu

say() { printf '%s\n' "$*"; }

# The macOS app: a double-click opens a Terminal window that runs "woodshed app" (the library opens
# in the browser; closing the window stops it). Made here, not downloaded, so macOS does not
# quarantine it. $1: the folder of the woodshed command.
mac_app() {
    app="$HOME/Applications/woodshed.app"
    rm -rf "$app"
    mkdir -p "$app/Contents/MacOS" "$app/Contents/Resources"
    cat > "$app/Contents/Info.plist" <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>CFBundleDisplayName</key>
	<string>woodshed</string>
	<key>CFBundleExecutable</key>
	<string>woodshed</string>
	<key>CFBundleIdentifier</key>
	<string>io.github.laugiov.woodshed</string>
	<key>CFBundleInfoDictionaryVersion</key>
	<string>6.0</string>
	<key>CFBundleName</key>
	<string>woodshed</string>
	<key>CFBundlePackageType</key>
	<string>APPL</string>
	<key>CFBundleVersion</key>
	<string>1</string>
</dict>
</plist>
EOF
    cat > "$app/Contents/MacOS/woodshed" <<'EOF'
#!/bin/sh
exec open -a Terminal "$(dirname "$0")/../Resources/woodshed.command"
EOF
    cat > "$app/Contents/Resources/woodshed.command" <<EOF
#!/bin/sh
echo "woodshed opens your library in the browser."
echo "Keep this window open while you play; close it to stop woodshed."
echo ""
"$1/woodshed" app || echo "woodshed stopped: the message above says why."
EOF
    chmod 755 "$app/Contents/MacOS/woodshed" "$app/Contents/Resources/woodshed.command"
}

# On macOS a plain archive of the latest version: git is not needed (on a new Mac it asks for
# Apple's developer tools first), and PyPI's PyTorch is the CPU build there. On Linux git, so that
# the project's CPU index for PyTorch applies (an archive would bring the 5 GB GPU build).
if [ -n "${WOODSHED_SOURCE:-}" ]; then
    SOURCE="$WOODSHED_SOURCE"
elif [ "$(uname -s)" = "Darwin" ]; then
    SOURCE="https://github.com/laugiov/woodshed/archive/refs/heads/main.tar.gz"
else
    SOURCE="git+https://github.com/laugiov/woodshed"
fi
# Demucs pins an old PyTorch on Intel Macs, with no build for Python 3.13.
PYTHON=3.13
if [ "$(uname -s)" = "Darwin" ] && [ "$(uname -m)" = "x86_64" ]; then PYTHON=3.12; fi

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

# On ARM Linux (Raspberry Pi...) one dependency of Demucs, sphn, has no ready-made build: it is compiled.
if [ "$(uname -s)" = "Linux" ] && [ "$(uname -m)" = "aarch64" ] && ! command -v cargo >/dev/null 2>&1; then
    say "On ARM Linux one part of woodshed is compiled: install a C compiler and Rust first, then run this again:"
    say "  sudo apt install build-essential     (or your system's equivalent)"
    say "  curl --proto '=https' -sSf https://sh.rustup.rs | sh"
    exit 1
fi

say "Installing woodshed (about 1.5 GB with PyTorch: a few minutes)..."
uv tool install --force --refresh-package woodshed --python "$PYTHON" "woodshed[stems] @ $SOURCE"
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
if [ "$(uname -s)" = "Darwin" ] && [ "${WOODSHED_NO_MENU:-0}" != "1" ]; then
    mac_app "$BIN"
    say "App added: woodshed, in your Applications folder (Launchpad and Spotlight find it too)."
fi

say ""
say "woodshed is installed: $("$BIN/woodshed" --version)"
if ! command -v ffmpeg >/dev/null 2>&1; then
    say ""
    say "MP3, WAV, FLAC and Ogg files work as they are. For AAC (M4A) and video files, add ffmpeg:"
    if [ "$(uname -s)" = "Darwin" ]; then
        say "  brew install ffmpeg     (with Homebrew: https://brew.sh)"
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
if [ "$(uname -s)" = "Darwin" ] && [ -d "$HOME/Applications/woodshed.app" ]; then
    say "Start it from Applications (woodshed), or in a new terminal:  woodshed app"
else
    say "Start it with:  woodshed app        (open a new terminal first if the command is not found)"
fi
say "Or one song:    woodshed song.mp3"
