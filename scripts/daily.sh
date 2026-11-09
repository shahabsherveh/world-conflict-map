#!/usr/bin/env bash
# Daily fetch + extract pipeline. Run from cron.
set -euo pipefail

cd "$(dirname "$0")/.."
# shellcheck source=scripts/_venv.sh
source scripts/_venv.sh
# Absolute interpreter, not `source .venv/bin/activate`: activation only edits
# PATH, and under cron PATH is whatever cron decided.
python_bin=$(gcm_venv_python)
"$python_bin" -m app.extract.run
