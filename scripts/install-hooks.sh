#!/usr/bin/env bash
# Activate the repo's versioned git hooks. Git reads hooks from .git/hooks by
# default, but that directory is never committed, so a hook dropped there is
# lost on the next clone and invisible to review. This points git at the tracked
# scripts/git-hooks/ directory instead. Idempotent; run once per clone (re-runs
# just reassert the same setting).
set -euo pipefail
repo_root="$(cd "$(dirname "$0")/.." && pwd)"

# shellcheck source=scripts/_venv.sh
source "$repo_root/scripts/_venv.sh"

# Arming a hook that cannot pass is worse than no hook: every commit then fails
# with a message that arrives at the worst possible moment. Check the same
# prerequisites ci-check.sh needs here, while the fix is a copy-paste away. The
# venv is gitignored, so a fresh clone is exactly the cold case this guards.
if ! gcm_venv_python >/dev/null; then
  exit 1
fi

missing=()
for tool in ruff ty pymarkdown pytest alembic pip-audit; do
  gcm_venv_tool "$tool" >/dev/null || missing+=("$tool")
done
if [ "${#missing[@]}" -gt 0 ]; then
  printf '[hooks] %s missing from %s\n' "${missing[*]}" "$GCM_VENV" >&2
  printf '[hooks] fix: %s/bin/pip install -r %s/requirements.lock -r %s/requirements-ci.txt\n' \
    "$GCM_VENV" "$repo_root" "$repo_root" >&2
  exit 1
fi

git -C "$repo_root" config core.hooksPath "$repo_root/scripts/git-hooks"
printf 'git core.hooksPath -> %s\n' "$repo_root/scripts/git-hooks"
printf 'pre-commit runs scripts/ci-check.sh (~10 s); git commit --no-verify skips it\n'
