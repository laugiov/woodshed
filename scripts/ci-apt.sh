#!/usr/bin/env bash
# CI only: install Ubuntu packages without hanging a job on a slow mirror.
# Each try is cut short; after a failed try the runner's Azure mirror is dropped for Ubuntu's own.
# Recommended packages are left out: ffmpeg alone is a third of the download.
set -uo pipefail
apt=(sudo apt-get -o Acquire::Retries=3 -o Acquire::http::Timeout=30 -o Acquire::https::Timeout=30)
for try in 1 2 3; do
  if timeout 300 "${apt[@]}" update -q && timeout 300 "${apt[@]}" install -y -q --no-install-recommends "$@"; then
    exit 0
  fi
  echo "apt: try $try failed, next one on archive.ubuntu.com" >&2
  [ -f /etc/apt/apt-mirrors.txt ] && sudo sed -i '/azure/d' /etc/apt/apt-mirrors.txt
  sleep 5
done
exit 1
