#!/usr/bin/env bash
# Daily fetch + extract pipeline. Run from cron.
set -euo pipefail

cd "$(dirname "$0")/.."
# shellcheck source=scripts/_venv.sh
source scripts/_venv.sh
# shellcheck source=scripts/_data-dir.sh
source scripts/_data-dir.sh
# Absolute interpreter, not `source .venv/bin/activate`: activation only edits
# PATH, and under cron PATH is whatever cron decided.
python_bin=$(gcm_venv_python)
# _data-dir.sh exports HF_HOME=$GCM_HF_HOME (the same directory the container
# mounts at /data/hf-cache), so the host run and the container share one model
# cache instead of downloading it twice.
"$python_bin" -m app.extract.run
