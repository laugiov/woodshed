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
# On macOS it also fetches the Rubber Band program (for the recording in your key) into woodshed's tools folder.
#
# Intel Macs are not supported (one part has no ready-made build there): Docker works on them.
#
# Options, as environment variables:
#   WOODSHED_SOURCE   what to install (default: the version WOODSHED_REF names, on GitHub)
#   WOODSHED_REF      a branch or a version tag on GitHub (default: main)
#   WOODSHED_NO_MENU  set to 1 to skip the menu entries (Linux) or the apps (macOS)
#   WOODSHED_TOOLS    woodshed's tools folder (the Linux uninstall script goes there)
# Uninstall: open "Uninstall woodshed" (the menu, or Applications on a Mac); in a terminal,
# woodshed uninstall, then the command it prints.

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
    # The command's path in single quotes, whatever the folder names hold.
    exe="'$(printf '%s' "$1/woodshed" | sed "s/'/'\\\\''/g")'"
    cat > "$app/Contents/Resources/woodshed.command" <<EOF
#!/bin/sh
echo "woodshed opens your library in the browser."
echo "Keep this window open while you play; close it to stop woodshed."
echo ""
$exe app || echo "woodshed stopped: the message above says why."
EOF
    chmod 755 "$app/Contents/MacOS/woodshed" "$app/Contents/Resources/woodshed.command"
}

# woodshed's tools folder, where its own programs go (Rubber Band, the Linux uninstall script): as woodshed
# computes it (paths.tools_dir in woodshed).
# WOODSHED_TOOLS counts when absolute or under the home folder (~, ~/...); a relative value (it would depend on
# where the installer runs) and ~user are ignored, as woodshed does.
woodshed_tools_dir() {
    case "${WOODSHED_TOOLS:-}" in
        "~" | "~/"*) printf '%s\n' "$HOME${WOODSHED_TOOLS#"~"}"; return 0 ;;
        /*) printf '%s\n' "$WOODSHED_TOOLS"; return 0 ;;
    esac
    if [ "$(uname -s)" = "Darwin" ]; then
        printf '%s\n' "$HOME/Library/Application Support/woodshed/tools"
    else
        case "${XDG_DATA_HOME:-}" in
            /*) printf '%s\n' "$XDG_DATA_HOME/woodshed/tools" ;;
            *) printf '%s\n' "$HOME/.local/share/woodshed/tools" ;;
        esac
    fi
}

# The singer's key on a Mac (spec 017): Homebrew's ffmpeg has no Rubber Band filter, so the Rubber Band
# program goes in woodshed's tools folder: the official GPL build from breakfastquay.com, checked against its
# pinned sha256, kept next to its licence. A separate program woodshed runs, never linked. Skipped when the
# program there is already this one; a failed download says so in one line and never fails the install.
# $1 $2 $3 (tests): the archive's URL, its sha256, the program's sha256.
get_rubberband() {
    rb_url="${1:-https://breakfastquay.com/files/releases/rubberband-4.0.0-gpl-executable-macos.tar.bz2}"
    rb_sum="${2:-0dc91509a31a94c1144436cc20e6f1d165bdab39fe125f9be7d46139921b733f}"
    rb_bin_sum="${3:-bffe8a37f204958352e768fc4a751d3dbce18e3b42c2a3427a80498e7d8cee79}"
    rb_tools="$(woodshed_tools_dir)"
    if command -v shasum >/dev/null 2>&1; then rb_hash="shasum -a 256"; else rb_hash="sha256sum"; fi
    # Skipped only when it is this program and it runs: one the system blocks is fetched (and said) again.
    if [ -f "$rb_tools/rubberband" ] && [ "$($rb_hash "$rb_tools/rubberband" | cut -d' ' -f1)" = "$rb_bin_sum" ] \
        && "$rb_tools/rubberband" -V >/dev/null 2>&1; then
        return 0
    fi
    rb_foreign=""
    rb_tmp="$(mktemp -d)" || rb_tmp=""
    if [ -n "$rb_tmp" ] \
        && curl -fsSL --retry 2 --connect-timeout 20 --max-time 300 -o "$rb_tmp/rb.tar.bz2" "$rb_url" \
        && [ "$($rb_hash "$rb_tmp/rb.tar.bz2" | cut -d' ' -f1)" = "$rb_sum" ] \
        && tar -xjf "$rb_tmp/rb.tar.bz2" -C "$rb_tmp" 2>/dev/null \
        && rb_dir="$(dirname "$(ls "$rb_tmp"/*/rubberband)")" \
        && [ "$($rb_hash "$rb_dir/rubberband" | cut -d' ' -f1)" = "$rb_bin_sum" ] \
        && if [ -e "$rb_tools/COPYING" ] && ! cmp -s "$rb_dir/COPYING" "$rb_tools/COPYING"; then
            rb_foreign=1  # the folder holds someone else's licence: never overwritten
            false
        fi \
        && mkdir -p "$rb_tools" \
        && cp "$rb_dir/COPYING" "$rb_tools/COPYING" \
        && cp "$rb_dir/rubberband" "$rb_tools/.rubberband.part" \
        && chmod 755 "$rb_tools/.rubberband.part" \
        && mv -f "$rb_tools/.rubberband.part" "$rb_tools/rubberband"; then
        if "$rb_tools/rubberband" -V >/dev/null 2>&1; then
            printf '%s\n' "The recording in your key: Rubber Band is ready."
        else
            printf '%s\n' "The recording in your key is off: Rubber Band is installed but this computer blocks it. Allow it in your security settings, then restart woodshed."
        fi
    else
        rm -f "$rb_tools/.rubberband.part"
        if [ -n "${rb_foreign:-}" ]; then
            printf '%s\n' "The recording in your key is off: the tools folder ($rb_tools) holds a COPYING file that is not Rubber Band's, kept as it is. Point WOODSHED_TOOLS to a folder of woodshed's own."
        else
            printf '%s\n' "The recording in your key is off: Rubber Band could not be downloaded. Run the installer again later to add it."
        fi
    fi
    [ -z "$rb_tmp" ] || rm -rf "$rb_tmp"
    return 0
}

# Uninstall woodshed (spec 018), from here to linux_uninstall_entry.
# A word in single quotes for sh, whatever it holds.
sh_quote() {
    printf "'%s'" "$(printf '%s' "$1" | sed "s/'/'\\\\''/g")"
}

# A path as one argument of a menu entry's Exec line (Desktop Entry spec): quoted, with ", `, $ and \
# escaped, then every backslash doubled again for the file's string rules; % doubled.
desktop_quote() {
    printf '"%s"' "$(printf '%s' "$1" | sed -e 's/\\/\\\\\\\\/g' -e 's/["`$]/\\\\&/g' -e 's/%/%%/g')"
}

# The script the Uninstall shortcuts run: woodshed removes its cache, tools and shortcuts (asking first),
# then uv removes woodshed once it has exited. $1: the folder of the woodshed command, $2: uv.
uninstall_script() {
    cat <<EOF
#!/bin/sh
# Made by the woodshed installer: removes woodshed from this computer, asking first. Your songs stay.
pause() { [ "\${WOODSHED_NO_PAUSE:-0}" = "1" ] || { printf 'Press Enter to close this window. '; read -r _ || true; }; }
echo "Uninstall woodshed"
echo "------------------"
echo ""
if ! $(sh_quote "$1/woodshed") uninstall --keep-self "\$@"; then
    echo ""
    echo "Nothing more was removed."
    pause
    exit 1
fi
echo ""
echo "Removing woodshed itself..."
if ! $(sh_quote "$2") tool uninstall woodshed; then
    echo "woodshed itself could not be removed: the message above says why."
    pause
    exit 1
fi
# woodshed's downloads in uv's cache (uninstall.CACHED in woodshed): only those packages, never the whole cache.
echo ""
echo "Cleaning woodshed's big packages (torch, numpy...) from uv's cache: other Python programs may download them again if they need them."
$(sh_quote "$2") cache clean woodshed torch torchaudio demucs llvmlite numba scipy scikit-learn sympy numpy || true
echo ""
echo "woodshed is removed. Your songs stay where they are."
pause
EOF
}

# The macOS app "Uninstall woodshed", next to woodshed in ~/Applications: made here, not downloaded, so
# macOS does not quarantine it. $1: the folder of the woodshed command, $2: uv.
mac_uninstall_app() {
    app="$HOME/Applications/Uninstall woodshed.app"
    rm -rf "$app"
    mkdir -p "$app/Contents/MacOS" "$app/Contents/Resources"
    cat > "$app/Contents/Info.plist" <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>CFBundleDisplayName</key>
	<string>Uninstall woodshed</string>
	<key>CFBundleExecutable</key>
	<string>uninstall</string>
	<key>CFBundleIdentifier</key>
	<string>io.github.laugiov.woodshed.uninstall</string>
	<key>CFBundleInfoDictionaryVersion</key>
	<string>6.0</string>
	<key>CFBundleName</key>
	<string>Uninstall woodshed</string>
	<key>CFBundlePackageType</key>
	<string>APPL</string>
	<key>CFBundleVersion</key>
	<string>1</string>
</dict>
</plist>
EOF
    cat > "$app/Contents/MacOS/uninstall" <<'EOF'
#!/bin/sh
exec open -a Terminal "$(dirname "$0")/../Resources/uninstall.command"
EOF
    uninstall_script "$1" "$2" > "$app/Contents/Resources/uninstall.command"
    chmod 755 "$app/Contents/MacOS/uninstall" "$app/Contents/Resources/uninstall.command"
}

# The Linux menu entry "Uninstall woodshed": a terminal window runs the script above, kept in woodshed's
# tools folder (woodshed uninstall removes that folder). $1: the folder of the woodshed command, $2: uv,
# $3: the applications folder.
linux_uninstall_entry() {
    tools="$(woodshed_tools_dir)"
    mkdir -p "$tools"
    uninstall_script "$1" "$2" > "$tools/uninstall-woodshed.sh"
    chmod 755 "$tools/uninstall-woodshed.sh"
    cat > "$3/woodshed-uninstall.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Uninstall woodshed
Comment=Remove woodshed from this computer (your songs stay)
Exec=sh $(desktop_quote "$tools/uninstall-woodshed.sh")
Terminal=true
Categories=AudioVideo;Audio;Music;
EOF
}

REF="${WOODSHED_REF:-main}"
PYTHON=3.13
if [ "$(uname -s)" = "Darwin" ]; then
    # Intel Macs: sphn (a part of Demucs) has no ready-made build there. Asked of the hardware, since
    # a Terminal running under Rosetta says x86_64 on Apple silicon too.
    if [ "$(sysctl -in hw.optional.arm64 2>/dev/null)" != "1" ]; then
        say "This Mac has an Intel processor: the installer needs a Mac with Apple silicon (M1 or newer),"
        say "because one part of woodshed has no ready-made build for Intel Macs."
        say "On this Mac, use woodshed with Docker instead:"
        say "  https://github.com/laugiov/woodshed/blob/main/docs/guide/install.md#with-docker-windows-macos-or-linux"
        exit 1
    fi
    PYTHON=cpython-3.13-macos-aarch64-none  # the Apple silicon build, even from a Rosetta Terminal
fi

# On macOS a plain archive: git is not needed (on a new Mac it asks for Apple's developer tools
# first), and PyPI's PyTorch is the CPU build there. On Linux git, so that the project's CPU index
# for PyTorch applies (an archive would bring the 5 GB GPU build).
if [ -n "${WOODSHED_SOURCE:-}" ]; then
    SOURCE="$WOODSHED_SOURCE"
elif [ "$(uname -s)" = "Darwin" ]; then
    SOURCE="https://github.com/laugiov/woodshed/archive/$REF.tar.gz"
else
    SOURCE="git+https://github.com/laugiov/woodshed@$REF"
fi

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

# Replacing woodshed while it runs would break the running one. pgrep takes a regular expression:
# the folder's name is escaped.
BIN="$(uv tool dir --bin 2>/dev/null || true)"
running="$(printf '%s' "$BIN/woodshed app" | sed 's/[\.*^$+?(){|[]/\\&/g')"
if [ -n "$BIN" ] && command -v pgrep >/dev/null 2>&1 && pgrep -f "$running" >/dev/null 2>&1; then
    say "woodshed is running: close woodshed first (its window), then run the installer again."
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
Exec=$(desktop_quote "$BIN/woodshed") app
Terminal=true
Categories=AudioVideo;Audio;Music;
EOF
    say "Menu entry added: woodshed."
fi
if [ "$(uname -s)" = "Darwin" ] && [ "${WOODSHED_NO_MENU:-0}" != "1" ]; then
    mac_app "$BIN"
    say "App added: woodshed, in your Applications folder (Launchpad and Spotlight find it too)."
fi
if [ "$(uname -s)" = "Darwin" ]; then
    get_rubberband || true
fi
# "Uninstall woodshed" next to woodshed: it runs woodshed uninstall, then uv removes woodshed.
if [ "${WOODSHED_NO_MENU:-0}" != "1" ]; then
    if [ "$(uname -s)" = "Darwin" ]; then
        mac_uninstall_app "$BIN" "$(command -v uv)"
        say "App added: Uninstall woodshed, next to it (to remove woodshed one day; your songs stay)."
    elif [ "$(uname -s)" = "Linux" ]; then
        linux_uninstall_entry "$BIN" "$(command -v uv)" "${XDG_DATA_HOME:-$HOME/.local/share}/applications"
        say "Menu entry added: Uninstall woodshed (to remove woodshed one day; your songs stay)."
    fi
fi

say ""
say "woodshed is installed: $("$BIN/woodshed" --version)"
if ! command -v ffmpeg >/dev/null 2>&1; then
    say ""
    if [ "$(uname -s)" = "Darwin" ]; then
        say "MP3, WAV, FLAC and Ogg files work as they are. For AAC (M4A) and video files, add ffmpeg:"
    else
        say "MP3, WAV, FLAC and Ogg files work as they are. For AAC (M4A) and video files, and the recording in your key, add ffmpeg:"
    fi
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
