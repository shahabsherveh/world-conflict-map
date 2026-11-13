# Host runbook: the steps that need the deploy host

Everything in this file is host state — Docker daemon config, systemd, crontab, the real
database — so it cannot be exercised from a CI job or a dev container. Each step says
what to run, what to expect, and how to know it worked. Run them in order: the cutover
assumes the daemon can resolve PyPI for the image build, and the watchers assume the app
is answering.

Conventions: `$REPO` is the checkout on the host, `$USER` the account that owns it. All
commands are run from `$REPO` unless noted.

```bash
REPO=/path/to/global-conflict-map   # adjust
cd "$REPO"
```

The checklist these steps close lives in `tasks/todo.md` under "CI/CD follow-ups",
"Operations / data" and "Optional". Tick each item there when its "Done when" holds, so
the next session does not re-open host work it cannot see.

## 1. Fix the Docker daemon's resolvers

Why: build steps and `docker compose run` get the daemon's own fallback nameservers, not
the host's. On this network those are unreachable, so pip stalls on
`files.pythonhosted.org` with `ReadTimeoutError` while every host-side command works.
The `network: host` build flag is a workaround for CI; containers at runtime still get
the broken resolver, which is what breaks `docker compose run pipeline` (model download).

```bash
# The resolvers to copy: the host's own, not hardcoded.
grep '^nameserver' /etc/resolv.conf
sudo cp /etc/docker/daemon.json /etc/docker/daemon.json.bak   # if it exists
sudoedit /etc/docker/daemon.json
```

Add a `dns` array with those addresses, keeping any existing keys:

```json
{
  "dns": ["203.0.113.53", "203.0.113.54"]
}
```

```bash
sudo systemctl restart docker   # a reload does not re-read "dns"
```

Expected: the daemon comes back, and a container with the default bridge resolves names:

```bash
docker run --rm python:3.12-slim python -c \
  "import urllib.request; print(urllib.request.urlopen('https://pypi.org/pypi/httpx/json', timeout=10).status)"
```

Done when that prints `200` **without** `--network=host`. Keep `network: host` on the
builds — it costs nothing and covers a daemon that gets reset by a package upgrade. Note
in `AGENTS.md` gotcha #11 when this is checked, so nobody spends an hour on it again.

## 2. Create the state directories

```bash
sudo install -d -o "$USER" -g "$USER" /data /data/db /data/hf-cache
ls -ld /data /data/db /data/hf-cache
docker compose config --quiet   # interpolation is valid
```

Done when all three are owned by `$USER` and the compose file validates. Docker creates a
missing bind-mount target as root, which is how later pipeline runs lose write access.

## 3. Bring an existing database across (only if one exists)

Skip if this is a fresh deploy. The old stack must be down first, or it keeps writing to
the old file while the copy is taken.

```bash
docker compose ls -a                     # is there an old project?
docker compose -p workspace down         # only if it exists

./scripts/cutover-data.sh                # dry run: prints source, row counts, target
./scripts/cutover-data.sh --apply --owner "$USER"
```

Expected: the dry run names `/data/db/conflicts.db` as the target and prints
`integrity=ok` with `conflict`/`conflict_event` counts. `--apply` copies with SQLite's
backup API (WAL-safe), verifies the counts on the copy, and refuses to overwrite without
`--force`; the old database is left untouched.

```bash
docker compose up -d --build
curl -fsS 'http://127.0.0.1:8000/api/conflicts?start=1970-01-01&end=2100-01-01' \
  | python3 -c 'import json,sys; print(len(json.load(sys.stdin)))'
```

Done when the count matches the number the cutover printed. If it is 0, the app and the
data are on different paths — check `/api/health` first, then `_data-dir.sh`.

## 4. Confirm WAL is on in the deployed database

WAL is persistent per database file, so this is a one-time confirmation:

```bash
docker compose exec -T web python -c \
  "import sqlite3; print(sqlite3.connect('/data/db/conflicts.db').execute('pragma journal_mode').fetchone())"
```

Done when it prints `('wal',)`. If it prints `('delete',)`, the engine pragma is not being
applied — that is a code regression, not a host setting.

## 5. Install the two watchers

The app can be up while its data has stopped updating, and vice versa; these cover both.

```bash
sudo ./scripts/install-health-watch.sh --dry-run   # prints the units, writes nothing
sudo ./scripts/install-health-watch.sh
systemctl list-timers gcm-health-check.timer
sudo systemctl start gcm-health-check.service
journalctl -u gcm-health-check.service -n 20 --no-pager
```

Expected: the timer is listed with a next run within 15 minutes, the service run exits 0
and logs `ok: web app healthy at http://127.0.0.1:8000`. Then the pipeline cron line:

```bash
crontab -e
# add, with the real path and a MAILTO if you want mail on failure:
MAILTO=you@example.com
0 8 * * * /path/to/global-conflict-map/scripts/check-pipeline.sh
```

Verify both directions rather than assuming: `docker compose stop web` then
`./scripts/check-health.sh` must exit non-zero with a `DOWN:` line, and
`./scripts/check-pipeline.sh` must exit non-zero when the last successful run is older
than `pipeline_stale_hours` (48). Start the container again afterwards.

Done when a stopped container and a stale pipeline each produce a non-zero exit without
anyone inspecting `docker ps`.

## 6. Require review on the `production` environment

This is a repository setting, not a file. In GitHub: **Settings → Environments →
`production` → Required reviewers** (add yourself), and keep the deploy job's
`environment: production` reference. Do it *after* the pipeline has run green once —
approval on an unproven workflow only adds friction.

Verification: a code push to `main` reaches "Deploy to this host" and waits for review;
approving it deploys; a docs-only push deploys nothing (the workflow skips it).

## 7. Decide raw retention, with a backup first

`raw_event` keeps every parsed source row for `raw_retention_days` (default 30) and
prunes processed rows after a successful run. Keeping it is what makes re-filtering
possible without re-downloading; dropping it saves space on a ~1.4 GB database.

Back up first — WAL-safe, through the app image:

```bash
docker compose exec -T web python - <<'PY'
import datetime, pathlib, sqlite3
src = "/data/db/conflicts.db"
dst = pathlib.Path("/data/db/backups") / (
    "conflicts-" + datetime.datetime.now(datetime.UTC).strftime("%Y%m%dT%H%M%SZ") + ".db"
)
dst.parent.mkdir(parents=True, exist_ok=True)
with sqlite3.connect(src) as s, sqlite3.connect(dst) as t:
    s.backup(t)
print(dst)
PY
docker compose exec -T web python -c \
  "import sqlite3; print(sqlite3.connect('/data/db/conflicts.db').execute('select count(*) from raw_event').fetchone())"
```

Then choose, in `config/gdelt.yaml` (in git, then deploy — a hand edit in the deploy
checkout is wiped by the next `git clean`):

- keep `raw_retention_days: 30` (re-filterable month, larger file), or
- set `raw_retention_days: 0` (prune everything processed; the map is unaffected, the
  re-filter option is gone).

Done when the row count follows the choice after one pipeline run and
`/api/pipeline-health` is still fresh.

## 8. Housekeeping

Image layers and the build cache accumulate and nothing prunes them. Monthly is enough:

```bash
docker image prune -f --filter until=168h
docker builder prune -f --filter until=168h
docker system df
```

Expected: `docker system df` reclaimable stays small across deploys. The tagged
`gcm-web:rollback` image is kept (prune without `-a` only removes dangling layers), which
is what `scripts/deploy.sh` rolls back to.

## 9. Backfill more history (optional)

Use the daily wrapper so the container reads the deployed database, and note the model
cost: the zero-shot filter dominates, roughly 30 minutes per day of data.

```bash
./scripts/docker-daily.sh --start 2026-09-01 --end 2026-10-28
```

For a backfill longer than half a day, raise `stale_run_hours` in `config/gdelt.yaml`
first (default 12): the pipeline declares a `running` row older than that failed, and
would otherwise mark a live backfill as dead.

Done when `GET /api/conflicts` covers the earlier dates and the run rows are `success`
with no `degraded_reason` beyond the expected ones.

## When something is wrong

| Symptom | First check |
|---|---|
| Map empty, `/health` 200 | `./scripts/check-pipeline.sh`; then the DB path the pipeline used |
| Deploy stuck at "waiting for review" | step 6, and whether the change was docs-only |
| pip timeouts inside containers only | step 1 (`dns`), and `network: host` on builds |
| `Permission denied` writing the DB | step 2: who owns `/data/db` |
| Pipeline `failed` after a crash | `GET /api/ingestion-runs?limit=5` for `error`/`phase` |
| Marker in the wrong country | do not re-geocode; move that event by hand (see gotcha #3) |
