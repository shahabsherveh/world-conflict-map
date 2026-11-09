#!/usr/bin/env bash
# Alert when the daily pipeline has stopped updating the map.
#
# The failure this catches is the expensive one: the cron job points at one
# database while the web app reads another (see _data-dir.sh), so every run
# "succeeds" and the map silently freezes. Nothing in the logs says so.
#
# Host cron (mail on a non-zero exit needs MAILTO in the crontab):
#   0 8 * * * /absolute/path/to/scripts/check-pipeline.sh
#
# Exits non-zero when the API reports no successful run within
# config/gdelt.yaml -> pipeline_stale_hours, so cron's MAILTO reaches a human.
set -euo pipefail

cd "$(dirname "$0")/.."

# Overridable so the check can run against a different port/host.
url=${GCM_HEALTH_URL:-http://127.0.0.1:8000/api/pipeline-health}

if ! body=$(curl -fsS --max-time 10 "$url"); then
  echo "error: cannot reach $url — is the web app running?" >&2
  exit 1
fi

# No jq: json is stdlib, and the repo already assumes Python 3.12 on the host.
# The body is passed as an argument rather than on stdin so a stray `-` in the
# JSON can never be read as python's "read from stdin".
python3 - "$body" <<'PY'
import json
import sys

data = json.loads(sys.argv[1])
if data["stale"]:
    last = data["last_success_at"] or "never"
    print(
        f"STALE: last successful ingestion run {last} "
        f"(threshold {data['threshold_hours']}h)",
        file=sys.stderr,
    )
    raise SystemExit(1)
print(f"ok: last successful ingestion run {data['last_success_at']} "
      f"({data['age_hours']}h ago)")
PY
