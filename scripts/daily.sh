#!/usr/bin/env bash
# Daily fetch + extract pipeline. Run from cron.
set -euo pipefail

cd "$(dirname "$0")/.."
source .venv/bin/activate
python -m app.extract.run
