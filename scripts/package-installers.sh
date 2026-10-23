#!/bin/bash
# Packages the double-click installers for a GitHub release (.github/workflows/installers.yml):
#
#   scripts/package-installers.sh OUT_DIR [TAG]
#
# OUT_DIR gets woodshed-installer-macos.zip (the .command file, zipped so that it stays executable)
# and woodshed-installer-windows.cmd. With a version tag, both install that version instead of main:
# the default of WOODSHED_REF in each file becomes the tag.

set -euo pipefail

mkdir -p "$1"
out="$(cd "$1" && pwd)"
tag="${2:-}"
src="$(cd "$(dirname "$0")/installers" && pwd)"
mac="Install woodshed.command"
win="Install woodshed.cmd"
build="$(mktemp -d)"
trap 'rm -rf "$build"' EXIT

if [ -n "$tag" ]; then
    [[ "$tag" =~ ^v[0-9A-Za-z._-]+$ ]] || { echo "::error::bad tag: $tag" >&2; exit 1; }
    sed "s|WOODSHED_REF:-main}|WOODSHED_REF:-$tag}|" "$src/$mac" > "$build/$mac"
    sed "s|WOODSHED_REF=main\"|WOODSHED_REF=$tag\"|" "$src/$win" > "$build/$win"
    grep -qF "WOODSHED_REF:-$tag}" "$build/$mac"
    grep -qF "WOODSHED_REF=$tag\"" "$build/$win"
else
    cp "$src/$mac" "$src/$win" "$build/"
fi
chmod 755 "$build/$mac"

rm -f "$out/woodshed-installer-macos.zip"
(cd "$build" && zip -qX "$out/woodshed-installer-macos.zip" "$mac")
cp "$build/$win" "$out/woodshed-installer-windows.cmd"

# Finder runs the file only if it is executable; cmd.exe wants Windows line endings. grep reads all of
# zipinfo's output (no -q): an early exit would kill zipinfo with SIGPIPE, and pipefail would fail the run.
zipinfo "$out/woodshed-installer-macos.zip" | grep "^-rwxr-xr-x.*$mac\$" > /dev/null
test "$(grep -c $'\r$' "$out/woodshed-installer-windows.cmd")" = "$(wc -l < "$out/woodshed-installer-windows.cmd" | tr -d ' ')"
