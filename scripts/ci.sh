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

step "lint and format"
uv run --frozen ruff check .
uv run --frozen ruff format --check .

step "types"
uv run --frozen mypy src

for py in "${PYTHONS[@]}"; do
  step "tests, Python $py"
  UV_PROJECT_ENVIRONMENT=".venvs/py${py/./}" uv run --frozen --python "$py" --group dev \
    pytest --cov --cov-report=term-missing:skip-covered -q
done

step "package"
rm -rf dist
uv build -q
uvx -q twine check --strict dist/*
smoke="$(mktemp -d)"
uv venv -q --python 3.14 "$smoke/venv"
VIRTUAL_ENV="$smoke/venv" uv pip install -q dist/*.whl
"$smoke/venv/bin/woodshed" --version
rm -rf "$smoke"

step "workflows"
docker run --rm -v "$PWD:/repo:ro" -w /repo rhysd/actionlint:1.7.12 -color .github/workflows/ci.yml

printf '\nAll checks passed.\n'
