#!/usr/bin/env bash
# Single definition of where the deployed stack keeps its SQLite DB, HF model
# cache, and its config file. Sourced by every script that touches the stack:
# deploy.sh, docker-daily.sh, daily.sh and cutover-data.sh.
#
# One host directory is mounted at /data by docker-compose.yml, and it holds the
# two stateful siblings:
#
#   GCM_DATA_ROOT=/data          the mount root
#   GCM_DATA_DIR=$root/db        conflicts.db and its WAL files
#   GCM_HF_HOME=$root/hf-cache   the ~570 MB zero-shot model cache
#
# Paths are identical inside and outside the container (/data/db/conflicts.db,
# /data/hf-cache), so a log line, a backup command and a `docker exec` all refer
# to the same file instead of needing a translation. The cache stays a sibling of
# the db directory rather than a subdirectory of it, so the one directory whose
# loss is unrecoverable can be backed up on its own. The Dockerfile sets
# HF_HOME=/data/hf-cache; this file exports the same value for the host pipeline,
# so both resolve the one cache (gotcha #7 in AGENTS.md) instead of downloading
# the weights twice.
#
# This exists because the paths did drift: the deploy job exported a data dir
# while the cron pipeline used the compose default ./data/db — inside the CI
# checkout, which the next checkout's `git clean -ffdx` deletes. The web app
# then served a database the pipeline never touched.
#
# Override for a throwaway stack by exporting GCM_DATA_ROOT (or GCM_DATA_DIR /
# GCM_HF_HOME individually). Bare `docker compose up` (none set) uses ./data.
: "${GCM_DATA_ROOT:=/data}"
export GCM_DATA_ROOT
: "${GCM_DATA_DIR:=$GCM_DATA_ROOT/db}"
export GCM_DATA_DIR

# Config gets the same treatment. The deploy checkout is disposable (`git clean
# -ffdx` on the next deploy), so the file the running containers read must be
# named in one place and edited in git — a hand edit in the checkout silently
# disappears on the next deploy. Both services mount this directory.
: "${GCM_CONFIG_DIR:=./config}"
export GCM_CONFIG_DIR

# HuggingFace model cache (the ~570 MB zero-shot weights). It is its own
# directory beside the db, resolved as HF_HOME by the container and by the host
# pipeline. Without this, `scripts/daily.sh` used ~/.cache/huggingface while the
# container used its own copy: two downloads, so a model copied in from another
# machine looked like it kept re-downloading. Override with GCM_HF_HOME or
# HF_HOME to keep a cache elsewhere.
: "${GCM_HF_HOME:=${HF_HOME:-$GCM_DATA_ROOT/hf-cache}}"
export GCM_HF_HOME
export HF_HOME="$GCM_HF_HOME"

# Docker creates a missing bind-mount target as root, which then breaks every
# later non-root write (backups, the pipeline, sqlite3). Create both targets as
# the invoking user and fail with an actionable message instead. Both matter:
# the cache needs a write during the first model download, the same way the data
# dir does when the first run creates conflicts.db.
gcm_ensure_dirs() {
  local dir
  for dir in "$GCM_DATA_DIR" "$GCM_HF_HOME"; do
    if ! mkdir -p "$dir" 2>/dev/null; then
      printf '[data-dir] cannot create %s as %s\n' "$dir" "$(id -un)" >&2
      printf '[data-dir] create it writable by that user (see docs/ci-cd.md)\n' >&2
      return 1
    fi
  done
}
