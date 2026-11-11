#!/usr/bin/env bash
# Single definition of where the deployed stack keeps its SQLite DB, HF model
# cache, and its config file. Sourced by deploy.sh and docker-daily.sh.
#
# This exists because the two did drift: the deploy job exported
# /var/lib/global-conflict-map/db while the cron pipeline used the compose
# default ./data/db — i.e. inside the CI checkout, which the next checkout's
# `git clean -ffdx` deletes. The web app then served a database the pipeline
# never touched.
#
# Override for a throwaway stack by exporting GCM_DATA_DIR. Bare `docker compose
# up` (no GCM_DATA_DIR) still falls back to ./data/db for local use.
: "${GCM_DATA_DIR:=/var/lib/global-conflict-map/db}"
export GCM_DATA_DIR

# Config gets the same treatment. The deploy checkout is disposable (`git clean
# -ffdx` on the next deploy), so the file the running containers read must be
# named in one place and edited in git — a hand edit in the checkout silently
# disappears on the next deploy. Both services mount this directory.
: "${GCM_CONFIG_DIR:=./config}"
export GCM_CONFIG_DIR

# Docker creates a missing bind-mount target as root, which then breaks every
# later non-root write (backups, the pipeline, sqlite3). Create it as the
# invoking user and fail with an actionable message instead.
gcm_ensure_data_dir() {
  if ! mkdir -p "$GCM_DATA_DIR" 2>/dev/null; then
    printf '[data-dir] cannot create %s as %s\n' "$GCM_DATA_DIR" "$(id -un)" >&2
    printf '[data-dir] create it writable by that user (see docs/ci-cd.md)\n' >&2
    return 1
  fi
}
