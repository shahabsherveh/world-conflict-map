#!/usr/bin/env bash
# Notice a web container that has stopped serving, after the deploy job has finished.
#
# The deploy job checks readiness once. Nothing watched a container that started
# crash-looping an hour later, so "is the map up?" could only be answered by
# running `docker ps` on the host. This is the smoke alarm for that.
#
# Readiness is deliberately the same definition scripts/deploy.sh uses: /health
# returns 200 *and* /api/conflicts answers with a JSON array. A static /health
# would pass while the database is unreadable.
#
# Run it from a systemd timer (scripts/install-health-watch.sh) or host cron:
#   */15 * * * * /absolute/path/to/scripts/check-health.sh || mail -s ... me
#
# Exits non-zero with a one-line reason on stderr, so cron's MAILTO (or the
# systemd unit's OnFailure) reaches a human.
set -euo pipefail

base=${GCM_HEALTH_BASE_URL:-http://127.0.0.1:8000}

if ! curl -fsS --max-time 5 "$base/health" >/dev/null; then
  echo "DOWN: $base/health did not return 2xx" >&2
  exit 1
fi

# `curl | head` would trip pipefail when head closes early; capture instead.
body=$(curl -fsS --max-time 10 "$base/api/conflicts?start=1970-01-01&end=2100-01-01" \
  2>/dev/null || true)
if [[ "$body" != \[* ]]; then
  echo "DOWN: /api/conflicts did not answer with a JSON array (database unreadable?)" >&2
  exit 1
fi

echo "ok: web app healthy at $base"
