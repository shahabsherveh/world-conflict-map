#!/usr/bin/env bash
# Where the local virtualenv lives, resolved once so no script has to assume it
# is being run from a particular directory.
#
# Override with GCM_VENV for a venv kept elsewhere. Every script that needs
# Python sources this rather than hardcoding `.venv`, because "cd to the repo
# root, then source .venv/bin/activate" breaks the moment the venv is somewhere
# else — which is exactly how the cron job and the CI mirror drifted.
gcm_repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
: "${GCM_VENV:=$gcm_repo_root/.venv}"
export GCM_VENV

# Print the interpreter of an existing venv, or fail with the fix. Resolved
# rather than activated: activation only rearranges PATH, which the caller may
# then override; an absolute interpreter is unambiguous.
gcm_venv_python() {
  if [ ! -x "$GCM_VENV/bin/python" ]; then
    printf '[venv] no interpreter at %s\n' "$GCM_VENV" >&2
    printf '[venv] create it: python3 -m venv %s && %s/bin/pip install -r %s/requirements.txt\n' \
      "$GCM_VENV" "$GCM_VENV" "$gcm_repo_root" >&2
    return 1
  fi
  printf '%s\n' "$GCM_VENV/bin/python"
}

# Same, for a console script (ruff, pytest, …) installed into that venv.
gcm_venv_tool() {
  local tool="$1"
  if [ ! -x "$GCM_VENV/bin/$tool" ]; then
    printf '[venv] %s not installed in %s — install requirements.txt and requirements-ci.txt\n' \
      "$tool" "$GCM_VENV" >&2
    return 1
  fi
  printf '%s\n' "$GCM_VENV/bin/$tool"
}
