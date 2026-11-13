#!/usr/bin/env bash
# Build, replace the web container, verify it, and roll back if it never gets
# healthy.
#
# Run on the host that owns the compose stack (the deploy job calls this; it is
# also safe to run by hand). The previous image is captured *before* the build
# because the build re-tags `gcm-web:local`, which would otherwise erase the
# only name pointing at the image that is still running.
set -euo pipefail
cd "$(dirname "$0")/.."
# shellcheck source=scripts/_data-dir.sh
source scripts/_data-dir.sh
gcm_ensure_dirs

HEALTH_URL="${GCM_HEALTH_URL:-http://127.0.0.1:8000/health}"
# /health is a static 200: it stays green if a migration left the schema broken.
# A conflicts query exercises the ORM path, which is what actually breaks.
READY_URL="${GCM_READY_URL:-${HEALTH_URL%/health}/api/conflicts?start=1970-01-01&end=2100-01-01}"
ATTEMPTS="${GCM_HEALTH_ATTEMPTS:-30}"
INTERVAL="${GCM_HEALTH_INTERVAL:-2}"

# Derive the rollback image from compose instead of hardcoding it: if the image
# name and the rollback tag drift apart, rollback silently starts the *new*
# image again (compose rebuilds when the tag is missing and a build is defined).
image=$(docker compose config --images web | head -1)
rollback_image="${image%:*}:rollback"
rollback_tag="${rollback_image##*:}"

log() { printf '[deploy] %s\n' "$*"; }
fail() {
  printf '[deploy] error: %s\n' "$*" >&2
  exit 1
}

ready() {
  local attempt body
  for ((attempt = 1; attempt <= ATTEMPTS; attempt++)); do
    if curl -fsS --max-time 2 "$HEALTH_URL" >/dev/null 2>&1; then
      # Captured, not piped into grep: with `pipefail`, grep -q exits early and
      # curl's SIGPIPE would fail the pipeline even on a match.
      body=$(curl -fsS --max-time 5 "$READY_URL" 2>/dev/null || true)
      if [[ "$body" == \[* ]]; then
        return 0
      fi
    fi
    sleep "$INTERVAL"
  done
  return 1
}

previous_image=""
container=$(docker compose ps -q web || true)
if [ -n "$container" ]; then
  # Image ID, not the tag: the build is about to reassign the tag. Tag it as
  # :rollback *before* building — a later `docker tag` fails, because moving
  # `gcm-web:local` prunes the old (untagged) image ID this would reference.
  # Kept after a successful deploy too: it is the manual rollback target.
  previous_image=$(docker inspect --format '{{.Image}}' "$container")
  docker tag "$previous_image" "$rollback_image"
  log "current image $previous_image (tagged $rollback_image)"
fi

log "building $image and the pipeline image"
# Build-container DNS: on the default bridge Docker substitutes its own resolvers
# (8.8.8.8/8.8.4.4 here), which are unreachable, so pip stalls on PyPI and the
# deploy dies at the first layer. The compose file sets `network: host` on both
# builds and `docker compose build` honours it, so this stays one code path; the
# explicit --network=host is the fallback for older compose/buildkit versions that
# ignore the key. The pipeline image is built here too: it must be the commit CI
# verified, not whatever checkout cron happens to sit in.
docker compose build --build-arg BUILDKIT_INLINE_CACHE=1 web pipeline \
  || docker build --network=host --tag "$image" . \
  || fail "build failed (if pip timed out on PyPI, set \"dns\" in the Docker daemon config)"

# --force-recreate: the tag stays `gcm-web:local`, so compose cannot tell the
# image changed and would otherwise leave the old container running.
log "replacing web container"
docker compose up -d --no-deps --force-recreate web

if ready; then
  log "ready at $HEALTH_URL (health + API query)"
  exit 0
fi

log "new container is not healthy"
if [ -z "$previous_image" ]; then
  log "no previous image to roll back to; leaving the container for inspection"
  docker compose logs --tail=50 web || true
  exit 1
fi

# Rollback is a re-tag, not a rebuild: the old layers are still on disk.
log "rolling back to $rollback_image ($previous_image)"
if GCM_IMAGE_TAG="$rollback_tag" docker compose up -d --no-deps --force-recreate web && ready; then
  log "rolled back; $HEALTH_URL is ready on the previous image"
else
  log "rollback did not become healthy either — needs a human"
fi
docker compose logs --tail=50 web || true
exit 1
