#!/usr/bin/env bash
# Run every gate the CI pipeline runs, locally. Same commands in the same order,
# so a green run here means a green pipeline short of the docker image build
# (`scripts/ci-check.sh --docker` adds that).
set -euo pipefail
cd "$(dirname "$0")/.."

if [ -x .venv/bin/python ]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

step() { printf '\n==> %s\n' "$*"; }

# The gates must be deterministic: if the local ruff/ty differ from the pinned
# versions CI installs, a green local run can still fail the pipeline.
step "gate tool versions (requirements-ci.txt)"
python - <<'PY'
import importlib.metadata as md
import re
import sys
from pathlib import Path

bad = []
for line in Path("requirements-ci.txt").read_text().splitlines():
    match = re.match(r"^([A-Za-z0-9_.-]+)==([^\s#]+)", line.strip())
    if not match:
        continue
    name, want = match.groups()
    try:
        have = md.version(name)
    except md.PackageNotFoundError:
        have = "not installed"
    print(f"{name}: local {have}, CI {want}")
    if have != want:
        bad.append(name)
if bad:
    sys.exit(f"version mismatch for {', '.join(bad)} — reinstall from requirements-ci.txt")
PY

step "ruff check"
ruff check .

step "ruff format --check"
ruff format --check app tests scripts

# CI installs a pinned shellcheck binary; locally use whatever is on PATH, or the
# official image as a fallback (that image tracks :stable, CI is the pinned one).
step "shellcheck"
if command -v shellcheck >/dev/null 2>&1; then
  shellcheck -x scripts/*.sh docker/pipeline-entrypoint.sh
elif command -v docker >/dev/null 2>&1; then
  docker run --rm -v "$PWD:/repo" -w /repo koalaman/shellcheck:stable \
    -x scripts/*.sh docker/pipeline-entrypoint.sh
else
  echo "shellcheck not installed; skipping (CI runs v0.11.0)" >&2
fi

step "ty check"
ty check

step "pytest"
pytest -q

step "alembic: fresh upgrade + model drift"
workdir=$(mktemp -d)
trap 'rm -rf "$workdir"' EXIT
export GCM_DATABASE_URL="sqlite:///$workdir/ci.db"
alembic upgrade head
alembic check

step "tracked artifacts"
if git ls-files | grep -Eq '(^|/)\.env$|\.db$|(^|/)\.venv/'; then
  echo "tracked artifact that must stay out of git:" >&2
  git ls-files | grep -E '(^|/)\.env$|\.db$|(^|/)\.venv/' >&2
  exit 1
fi

if [ "${1:-}" = "--docker" ]; then
  step "docker build"
  docker build --tag gcm-web:ci .
  step "runtime imports in the image"
  docker run --rm gcm-web:ci python -c \
    "import alembic, fastapi, httpx, sqlalchemy, torch, transformers, yaml; print('ok')"
fi

printf '\nAll gates passed.\n'
