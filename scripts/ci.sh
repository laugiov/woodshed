#!/usr/bin/env bash
# Local CI: runs the same checks as .github/workflows/ci.yml.
# Usage: scripts/ci.sh [--quick]   (--quick tests the newest Python only, for iterating)
set -euo pipefail
cd "$(dirname "$0")/.."

PYTHONS=(3.10 3.11 3.12 3.13 3.14)
if [ "${1:-}" = "--quick" ]; then PYTHONS=(3.14); fi
step() { printf '\n== %s\n' "$*"; }

step "repository hygiene"
python3 scripts/check_repo.py

step "lock file"
uv lock --check

step "lint and format"
uv run --frozen ruff check .
uv run --frozen ruff format --check .

step "types"
uv run --frozen mypy src tests scripts

for py in "${PYTHONS[@]}"; do
  step "tests, Python $py"
  UV_PROJECT_ENVIRONMENT=".venvs/py${py/./}" uv run --frozen --python "$py" --group dev \
    pytest -m "not page" --cov --cov-report=term-missing:skip-covered -q
done

step "practice page in real browsers (Chromium, Firefox)"
uv run --frozen --group dev playwright install chromium firefox
WOODSHED_REQUIRE_PAGE=1 uv run --frozen --group dev pytest -q -m page --browser chromium --browser firefox

step "package"
rm -rf dist
uv build -q
uv run --frozen --group dev twine check --strict dist/*
python3 scripts/check_wheel.py dist/*.whl
smoke="$(mktemp -d)"
uv venv -q --python 3.14 "$smoke/venv"
VIRTUAL_ENV="$smoke/venv" uv pip install -q dist/*.whl
"$smoke/venv/bin/woodshed" --version
rm -rf "$smoke"

# As the CI job "stems": the real libraries, CPU torch (about 1.4 GB per environment, once).
for py in 3.11 3.13; do
  step "stems extra (real Demucs and beat_this), Python $py"
  WOODSHED_REQUIRE_STEMS=1 UV_PROJECT_ENVIRONMENT=".venvs/stems${py/./}" \
    uv run --frozen --python "$py" --extra stems --group dev pytest -q -m stems
done

step "workflows"
docker run --rm -v "$PWD:/repo:ro" -w /repo rhysd/actionlint:1.7.12@sha256:b1934ee5f1c509618f2508e6eb47ee0d3520686341fec936f3b79331f9315667 -color .github/workflows/ci.yml

printf '\nAll checks passed.\n'
