#!/bin/bash
# Double-click in Finder to install woodshed on a Mac. It runs scripts/install.sh (from GitHub),
# which also makes the app ~/Applications/woodshed.app, then opens that app.
# Released as woodshed-installer-macos.zip, so that the file stays executable once downloaded; the
# release sets WOODSHED_REF below to its own version tag.
#
# Options, as environment variables (for tests):
#   WOODSHED_REF             the branch or version tag to install (default: below)
#   WOODSHED_INSTALL_SCRIPT  a local install.sh to run, instead of the one on GitHub
#   WOODSHED_SOURCE          what install.sh installs (see there)
#   WOODSHED_NO_OPEN         set to 1 to not start woodshed at the end

set -eu

WOODSHED_REF="${WOODSHED_REF:-main}"
export WOODSHED_REF

cat <<'EOF'
Installing woodshed
-------------------

This puts woodshed on this Mac, for you only:
  - its own copy of Python and of the music models' software (about 1.5 GB to download,
    a few minutes: leave this window open until it says "Done"),
  - the woodshed app, in the Applications folder of your home folder.
Nothing changes outside your home folder.

EOF

fail() {
    echo ""
    echo "The installation stopped: the messages above say why."
    echo "Once that is sorted, double-click the installer again,"
    echo "or ask for help: https://github.com/laugiov/woodshed/issues"
    exit 1
}

if [ -n "${WOODSHED_INSTALL_SCRIPT:-}" ]; then
    sh "$WOODSHED_INSTALL_SCRIPT" || fail
else
    script="$(mktemp)"
    trap 'rm -f "$script"' EXIT
    curl --proto '=https' --tlsv1.2 -fsSL -o "$script" \
        "https://raw.githubusercontent.com/laugiov/woodshed/$WOODSHED_REF/scripts/install.sh" || fail
    sh "$script" || fail
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
