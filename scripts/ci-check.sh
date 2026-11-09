#!/usr/bin/env bash
# Run every gate the CI pipeline runs, locally. Same commands in the same order,
# so a green run here means a green pipeline short of the docker image build
# (`scripts/ci-check.sh --docker` adds that).
set -euo pipefail
cd "$(dirname "$0")/.."

# shellcheck source=scripts/_venv.sh
source scripts/_venv.sh
python_bin=$(gcm_venv_python)

step() { printf '\n==> %s\n' "$*"; }

# The gates must be deterministic: if the local ruff/ty differ from the pinned
# versions CI installs, a green local run can still fail the pipeline.
step "gate tool versions (requirements-ci.txt)"
"$python_bin" - <<'PY'
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
"$(gcm_venv_tool ruff)" check .

step "ruff format --check"
"$(gcm_venv_tool ruff)" format --check app tests scripts

# CI installs a pinned shellcheck binary; locally use whatever is on PATH, or the
# official image as a fallback (that image tracks :stable, CI is the pinned one).
# Never skip silently: a gate that says "skipping" still looks green in a scrolled
# terminal, which is how a missing tool once masqueraded as a passing step.
step "shellcheck"
shellcheck_cmd=""
if command -v shellcheck >/dev/null 2>&1; then
  shellcheck_cmd="shellcheck"
elif command -v docker >/dev/null 2>&1; then
  shellcheck_cmd="docker run --rm -v $PWD:/repo -w /repo koalaman/shellcheck:stable"
else
  printf 'shellcheck and docker are both unavailable; install one to run this gate\n' >&2
  exit 1
fi
# .shellcheckrc provides external-sources; no -x needed.
$shellcheck_cmd scripts/*.sh docker/pipeline-entrypoint.sh

step "markdown lint"
pymarkdown scan -r README.md AGENTS.md docs tests/ui/README.md tasks

step "ty check"
"$(gcm_venv_tool ty)" check

step "pytest"
"$(gcm_venv_tool pytest)" -q

step "alembic: fresh upgrade + model drift"
workdir=$(mktemp -d)
trap 'rm -rf "$workdir"' EXIT
export GCM_DATABASE_URL="sqlite:///$workdir/ci.db"
# alembic lives in the project venv; a bare call depends on the caller's PATH.
"$(gcm_venv_tool alembic)" upgrade head
"$(gcm_venv_tool alembic)" check

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
