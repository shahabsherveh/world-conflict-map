#!/usr/bin/env bash
# Audit the installed runtime against the advisory database.
#
# The venv (not the lock file) is audited on purpose: CI installs the venv from
# requirements.lock, so this checks exactly what the image ships, and it costs
# seconds instead of the ten minutes pip-audit needs to re-resolve and hash-verify
# every wheel in the lock.
#
# Needs the network: pip-audit reads PyPI's JSON API plus the OSV advisory
# database. An unreachable database fails the gate rather than passing quietly —
# a security gate that reports success when it could not look is worse than none.
set -euo pipefail
cd "$(dirname "$0")/.."
# shellcheck source=scripts/_venv.sh
source scripts/_venv.sh
python_bin=$(gcm_venv_python)

out=$("$python_bin" -m pip_audit --skip-editable --progress-spinner off 2>&1) || {
  printf '%s\n' "$out" >&2
  printf '[deps] pip-audit failed (a finding, or the advisory database is unreachable)\n' >&2
  exit 1
}

# "No vulnerabilities" is the only clean result; anything else means the tool
# changed its output shape and the grep below would pass vacuously.
if ! printf '%s\n' "$out" | grep -q 'No known vulnerabilities found'; then
  printf '%s\n' "$out" >&2
  printf '[deps] pip-audit did not report a clean result\n' >&2
  exit 1
fi

# pip-audit cannot map torch's `+cpu` build to a PyPI release, so it lists it as
# skipped instead of auditing it. Accept that one named skip and fail on any
# other: a silently unaudited dependency is how a gate stops meaning anything.
skipped=$(printf '%s\n' "$out" | grep -E '^[A-Za-z0-9_.-]+ +Dependency ' || true)
if [ -n "$skipped" ]; then
  unexpected=$(printf '%s\n' "$skipped" | grep -v '^torch ' || true)
  if [ -n "$unexpected" ]; then
    printf '%s\n' "$unexpected" >&2
    printf '[deps] dependencies were not audited (only torch may be skipped)\n' >&2
    exit 1
  fi
  printf '[deps] torch is pinned but not auditable (its +cpu build is not on PyPI)\n'
fi

printf '[deps] no known vulnerabilities in the installed runtime\n'
