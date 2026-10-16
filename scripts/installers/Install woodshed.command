#!/bin/bash
# Double-click in Finder to install woodshed on a Mac. It runs scripts/install.sh (from GitHub),
# which also makes the app ~/Applications/woodshed.app, then opens that app.
# Released as woodshed-installer-macos.zip, so that the file stays executable once downloaded.
#
# Options, as environment variables (for tests):
#   WOODSHED_SOURCE   a local checkout to install from, instead of GitHub
#   WOODSHED_NO_OPEN  set to 1 to not start woodshed at the end

set -eu

cat <<'EOF'
Installing woodshed
-------------------

This puts woodshed on this Mac, for you only:
  - its own copy of Python and of the music models' software (about 1.5 GB to download,
    a few minutes: leave this window open until it says "Done"),
  - the woodshed app, in the Applications folder of your home folder.
No password needed, nothing changes outside your home folder.

EOF

fail() {
    echo ""
    echo "The installation stopped: the messages above say why."
    echo "Check your internet connection and double-click the installer again,"
    echo "or ask for help: https://github.com/laugiov/woodshed/issues"
    exit 1
}

if [ -n "${WOODSHED_SOURCE:-}" ] && [ -f "$WOODSHED_SOURCE/scripts/install.sh" ]; then
    sh "$WOODSHED_SOURCE/scripts/install.sh" || fail
else
    script="$(mktemp)"
    curl -fsSL https://raw.githubusercontent.com/laugiov/woodshed/main/scripts/install.sh -o "$script" || fail
    sh "$script" || fail
    rm -f "$script"
fi

echo ""
echo "Done: woodshed is installed."
app="$HOME/Applications/woodshed.app"
if [ -d "$app" ] && [ "${WOODSHED_NO_OPEN:-0}" != "1" ]; then
    echo "woodshed starts now in a new window, and opens your library in the browser."
    open "$app"
fi
echo ""
echo "You can close this window."
echo "Next time, open woodshed from Applications, Launchpad or Spotlight (Cmd+Space, then type woodshed)."
