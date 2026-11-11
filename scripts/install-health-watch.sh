#!/usr/bin/env bash
# Install a systemd timer that runs scripts/check-health.sh every 15 minutes.
#
# A healthy deploy is verified once by scripts/deploy.sh; this covers the rest of
# the week. Without it, a container that starts crash-looping after a deploy is
# only visible by inspecting `docker ps` (see docs/ci-cd.md, monitoring).
#
# Usage (on the deploy host, from the repo root):
#   ./scripts/install-health-watch.sh            # install + enable
#   ./scripts/install-health-watch.sh --dry-run  # print the units, write nothing
#   ./scripts/install-health-watch.sh --remove   # disable + delete
#
# Requires systemd. The unit runs as the invoking user (not root), because the
# check only makes HTTP requests to loopback. Failure output goes to the journal;
# add `OnFailure=` to the service if you want mail, or use cron's MAILTO instead.
set -euo pipefail

cd "$(dirname "$0")/.."
repo=$(pwd)
unit_dir=${GCM_SYSTEMD_DIR:-/etc/systemd/system}
service=gcm-health-check.service
timer=gcm-health-check.timer
mode=install

case "${1:-}" in
  --dry-run) mode=dry-run ;;
  --remove) mode=remove ;;
  "") ;;
  *)
    printf 'unknown argument %s (use --dry-run or --remove)\n' "$1" >&2
    exit 2
    ;;
esac

service_text=$(cat <<EOF
[Unit]
Description=Global Conflict Map health check

[Service]
Type=oneshot
ExecStart=$repo/scripts/check-health.sh
# The check talks to loopback only; never run it as root.
User=$(id -un)
EOF
)

timer_text=$(cat <<'EOF'
[Unit]
Description=Check the Global Conflict Map web app every 15 minutes

[Timer]
OnBootSec=2min
OnUnitActiveSec=15min
# Catch up after a suspend or a missed run instead of silently skipping it.
Persistent=true

[Install]
WantedBy=timers.target
EOF
)

case "$mode" in
  dry-run)
    printf '== %s/%s ==\n%s\n== %s/%s ==\n%s\n' \
      "$unit_dir" "$service" "$service_text" "$unit_dir" "$timer" "$timer_text"
    exit 0
    ;;
  remove)
    sudo systemctl disable --now "$timer" 2>/dev/null || true
    sudo rm -f "$unit_dir/$service" "$unit_dir/$timer"
    sudo systemctl daemon-reload
    printf 'removed %s and %s\n' "$service" "$timer"
    exit 0
    ;;
esac

if ! command -v systemctl >/dev/null 2>&1; then
  printf 'systemctl not found; use host cron instead (see docs/ci-cd.md)\n' >&2
  exit 1
fi

printf '%s\n' "$service_text" | sudo tee "$unit_dir/$service" >/dev/null
printf '%s\n' "$timer_text" | sudo tee "$unit_dir/$timer" >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable --now "$timer"
printf 'installed %s; next run:\n' "$timer"
systemctl list-timers "$timer" --no-pager || true
