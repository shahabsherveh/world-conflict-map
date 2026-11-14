# Iran deploy — ArvanCloud Cloud Server (Iranian datacenter)

How to put the map on an ArvanCloud **Cloud Server (ابرک)** inside Iran. This is the
cheapest, lowest-latency option for Iranian readers, and the one that needs the work:
PyPI, Docker Hub, and HuggingFace are either blocked or unreliable from Iranian IPs, so
the deploy must route package installs and the model download through Iranian mirrors
and (for the model) a copied cache. The app itself is unchanged.

The sibling `host-runbook.md` covers the *generic* host steps (WAL check, cutover,
watchers, retention, housekeeping) and applies here too. This file only adds the
Iran-specific pieces and reorders for them. Read both.

## Why mirrors, and which steps need them

From an Iranian IP:

| Your dependency | Status | Fix |
|---|---|---|
| GDELT (`data.gdeltproject.org`) | usually reachable, intermittently slow | none; the pipeline already degrades to *unfiltered* if a run fails |
| PyPI (`files.pythonhosted.org`) | blocked | point `pip`/image builds at an Iranian mirror |
| Docker Hub (`docker.io`) | blocked | registry-mirror in `daemon.json` |
| HuggingFace (`huggingface.co`, `cdn-lfs.huggingface.co`) | blocked/slow | `HF_ENDPOINT=https://hf-mirror.com`, else copy a complete cache |
| GitHub (Actions, clone) | blocked at IP level | clone from a proxy, run deploy/cron manually — do **not** rely on the GitHub Actions deploy path |

The GitHub piece is the biggest conceptual change vs. the normal deploy: `deploy.yml`
and the self-hosted runner assume a host that can reach GitHub. On an Iranian box,
deploy and the daily run are driven by hand + `cron`/`systemd` instead.

## 0. Provision

- ArvanCloud **Cloud Server** (not *Cloud Container* — that is Kubernetes, costs more,
  and needs a persistent-volume rewrite for SQLite; a two-container app does not warrant
  it).
- Package: **2 vCPU / 4 GB / 25–30 GB SSD**, *CPU-optimized* (حافظه/پردازشمحور) — the
  daily zero-shot filter is CPU-bound and ArvanCloud's own docs put "Machine Learning /
  Batch Processing" under the CPU-optimized tiers. The general tiers will make the
  ~30 min/day backfill cost noticeably more.
- Datacenter: any Iranian one (سیمین/فروغ/بامداد تهران، شهریار تبریز، قیصر اهواز).
- OS: Debian 12. Open port 22 for yourself; keep 8000 loopback-only (the compose file
  already binds `127.0.0.1:8000`).

## 1. Docker + registries

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker "$USER" && newgrp docker

# 1a. PyPI mirror — image builds and any host-side pip.
sudo mkdir -p /etc/pip.conf.d
printf '%s\n' \
  '[global]' \
  'index-url = https://mirror.cdn.ir/repository/pypi/simple' \
  'trusted-host = mirror.cdn.ir' \
  | sudo tee /etc/pip.conf >/dev/null
# alternates if that mirror is down: pypi.thealibigdeli.ir, mirrors.hyperclouds.ir

# 1b. Docker Hub registry mirror — so `FROM python:3.12-slim` resolves.
sudo tee /etc/docker/daemon.json >/dev/null <<'EOF'
{
  "registry-mirrors": ["https://docker.mobinhost.com"]
}
EOF
sudo systemctl restart docker
docker pull python:3.12-slim   # must succeed before step 2
```

The `network: host` build flag in `docker-compose.yml` stays (costs nothing, covers a
reset daemon); the registry mirror above is what actually unblocks PyPI inside builds.

## 2. Clone + verify

```bash
git clone <your-repo-url> global-conflict-map   # may need a proxy for github.com
cd global-conflict-map
docker compose config --quiet                   # interpolation valid
GCM_DATA_ROOT=/data docker compose build --network=host web pipeline
```

## 3. The model cache — the one step that will bite

This is the highest-failure-probability step. The model is
`cross-encoder/nli-deberta-v3-small` (~570 MB weights). Two paths, in order:

```bash
source scripts/_data-dir.sh
gcm_ensure_dirs                       # creates /data/db and /data/hf-cache owned by $USER

# 3a. Try the mirror first (download_model.py now honours HF_ENDPOINT).
HF_ENDPOINT=https://hf-mirror.com \
  HF_HOME=/data/hf-cache python scripts/download_model.py

# 3b. If it stalls on *.incomplete blobs, do not retry blindly (gotcha #7 in
# AGENTS.md). Copy a complete cache from ANY machine that can reach HF once:
rsync -a otherbox:~/.cache/huggingface/hub/models--cross-encoder--nli-deberta-v3-small \
          /data/hf-cache/hub/

# Verify either way:
HF_HOME=/data/hf-cache python scripts/download_model.py --check
```

`--check` must print `model present`. If no machine can reach HF and the mirror is also
blocked from your ISP, the app still runs — the zero-shot filter degrades to
*unfiltered* (more non-conflict events pass through), which is an acceptable first
deploy that you can revisit once a cache is available.

## 4. Deploy

```bash
cd global-conflict-map
source scripts/_data-dir.sh
docker compose up -d --build

curl -fsS http://127.0.0.1:8000/health
docker compose exec -T web python -c \
  "import sqlite3; print(sqlite3.connect('/data/db/conflicts.db').execute('pragma journal_mode').fetchone())"
# expect ('wal',)
```

## 5. Daily pipeline + watchers (replaces the GitHub-driven deploy)

```bash
# Health watcher (systemd timer) — see host-runbook.md §5 for the manual curls.
sudo ./scripts/install-health-watch.sh --dry-run
sudo ./scripts/install-health-watch.sh

# Daily pipeline — host cron, the Iranian-box replacement for the deploy workflow.
crontab -e
# add:
MAILTO=you@example.com
0 8 * * * /path/to/global-conflict-map/scripts/docker-daily.sh
```

## 6. Cutover + backfill

Only if you have an existing `conflicts.db` — see `host-runbook.md` §3 (cutover) and
§9 (backfill). The backfill wrapper is `scripts/docker-daily.sh --start … --end …`.

## What "done" looks like

- `/health` → 200 and `/api/conflicts` returns JSON over loopback.
- `pragma journal_mode` on the deployed DB prints `('wal',)`.
- `scripts/download_model.py --check` prints `model present` (or you have deliberately
  accepted the unfiltered fallback and can say why here).
- `crontab -l` shows the `docker-daily.sh` line and the health timer is listed in
  `systemctl list-timers`.
