#!/usr/bin/env bash
# Daily fetch + extract pipeline, containerized.
# Host cron:  0 6 * * * /absolute/path/to/scripts/docker-daily.sh
set -euo pipefail

cd "$(dirname "$0")/.."
docker compose run --rm pipeline
