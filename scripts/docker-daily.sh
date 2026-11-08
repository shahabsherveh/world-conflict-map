#!/usr/bin/env bash
# Daily fetch + extract pipeline, containerized.
# Host cron:  0 6 * * * /absolute/path/to/scripts/docker-daily.sh
set -euo pipefail

cd "$(dirname "$0")/.."
# Same GCM_DATA_DIR as deploy.sh — otherwise cron writes to ./data/db while the
# served app reads /var/lib/global-conflict-map/db (and `git clean` eats the DB).
# shellcheck source=scripts/_data-dir.sh
source scripts/_data-dir.sh
gcm_ensure_data_dir

# "$@" matters: without it `docker-daily.sh --days 7` silently ran the default
# 1-day lookback, so a "backfill" cron was not one.
docker compose run --rm pipeline "$@"
