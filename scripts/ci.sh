#!/usr/bin/env bash
# Local checks before a commit.
#   scripts/ci.sh          the everyday run, a few minutes: hygiene, lint, types, the tests on one
#                          Python and the page in Chromium, spread over every CPU core.
#   scripts/ci.sh --full   everything GitHub runs, before a push: every Python from 3.10 to 3.14,
#                          Firefox too, the real stems extra, the package and the workflow lint.
set -euo pipefail
cd "$(dirname "$0")/.."
FULL=0
if [ "${1:-}" = "--full" ]; then FULL=1; fi
step() { printf '\n== %s\n' "$*"; }
started=$SECONDS

step "repository hygiene"
python3 scripts/check_repo.py
uv lock --check

step "lint, format and types"
uv run --frozen ruff check .
uv run --frozen ruff format --check .
uv run --frozen mypy src tests scripts

if [ "$FULL" = 1 ]; then PYTHONS=(3.10 3.11 3.12 3.13 3.14); else PYTHONS=(3.14); fi
for py in "${PYTHONS[@]}"; do
  step "tests, Python $py"
  UV_PROJECT_ENVIRONMENT=".venvs/py${py/./}" uv run --frozen --python "$py" --group dev \
    pytest -m "not page" -n auto --cov --cov-report=term-missing:skip-covered -q
done

if [ "$FULL" = 1 ]; then BROWSERS=(--browser chromium --browser firefox); else BROWSERS=(--browser chromium); fi
step "practice page in real browsers (${BROWSERS[*]})"
uv run --frozen --group dev playwright install chromium firefox
WOODSHED_REQUIRE_PAGE=1 uv run --frozen --group dev pytest -q -m page -n auto "${BROWSERS[@]}"

if [ "$FULL" = 1 ]; then
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
fi

printf '\nAll checks passed in %d s.\n' $((SECONDS - started))
