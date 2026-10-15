#!/bin/sh
# Run woodshed with Docker on Linux or macOS, with nothing installed beforehand but Docker:
#
#   curl -LsSf https://raw.githubusercontent.com/laugiov/woodshed/main/scripts/install-docker.sh | sh
#
# It downloads compose.yaml into ~/woodshed-docker, creates the folder for your songs
# (~/woodshed-docker/woodshed), starts woodshed, waits until it answers and opens it in your browser.
# Nothing is installed on the computer: everything runs in the container.
#
# Options, as environment variables:
#   WOODSHED_DIR      where to put compose.yaml and your songs (default: ~/woodshed-docker)
#   WOODSHED_REF      the branch or tag of compose.yaml to use (default: main)
#   WOODSHED_NO_OPEN  set to 1 to not open the browser
# Stop: docker compose down      (in that folder; your songs stay, and the downloaded models too)
# Remove everything, models included: docker compose down --volumes

set -eu

DIR="${WOODSHED_DIR:-$HOME/woodshed-docker}"
REF="${WOODSHED_REF:-main}"
URL="http://localhost:8000/"
say() { printf '%s\n' "$*"; }
die() { say "$*"; exit 1; }

command -v docker >/dev/null 2>&1 || die "Docker is not installed: see https://docs.docker.com/get-docker/ (Docker Desktop on macOS)."
docker info >/dev/null 2>&1 || die "Docker is installed but not running (or you cannot use it): start Docker Desktop, or on Linux see https://docs.docker.com/engine/install/linux-postinstall/"
docker compose version >/dev/null 2>&1 || die "'docker compose' is missing: update Docker Desktop, or install the Compose plugin (https://docs.docker.com/compose/install/)."

mkdir -p "$DIR/woodshed"
cd "$DIR"

if [ ! -f compose.yaml ]; then
    say "Downloading compose.yaml into $DIR..."
    src="https://raw.githubusercontent.com/laugiov/woodshed/$REF/compose.yaml"
    if command -v curl >/dev/null 2>&1; then
        curl -fsSL -o compose.yaml "$src" || die "Could not download $src"
    else
        wget -qO compose.yaml "$src" || die "Could not download $src"
    fi
fi

# The container writes your songs as you, so the folder stays yours (compose reads this file).
if [ ! -f .env ]; then
    printf 'WOODSHED_UID=%s\nWOODSHED_GID=%s\n' "$(id -u)" "$(id -g)" > .env
fi

say "Starting woodshed (the first start downloads the image, about 2 GB)..."
docker compose up -d --wait || {
    docker compose logs --tail 30 || true
    die "woodshed did not start: see the messages above."
}

say ""
say "woodshed is running: $URL"
say "Drop a song on the page. The first analysis downloads the models (about 160 MB, once)."
say "Stop it with: cd \"$DIR\" && docker compose down"

if [ "${WOODSHED_NO_OPEN:-}" != "1" ]; then
    if command -v xdg-open >/dev/null 2>&1; then
        xdg-open "$URL" >/dev/null 2>&1 || true
    elif command -v open >/dev/null 2>&1; then
        open "$URL" >/dev/null 2>&1 || true
    fi
fi
