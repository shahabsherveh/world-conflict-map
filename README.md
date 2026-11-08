# Global Conflict Map

A personal web app that maps armed conflicts worldwide, browsable across time, and
updates itself daily from news data. Built personal-first but architected so it could
become a product without a rewrite.

## What it does

1. Fetches **GDELT 2.0 raw event files** (free, no API key) — news already coded into
   geolocated events.
2. Filters to **armed conflicts** (CAMEO root codes 18/19/20) and applies a
   **zero-shot semantic filter** to drop false positives (podcasts, jet crashes, etc.).
3. Groups events into **conflicts** and stores them in SQLite.
4. Serves an interactive **Leaflet map** with time-scrub and manual editing.

## Requirements

- Python 3.11+
- Network access (for GDELT + the one-time model download)

## Setup

```bash
cd global-conflict-map
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
python scripts/download_model.py   # one-time; downloads the zero-shot model (~570 MB)
```

## Run

```bash
# 1. Fetch + extract (the daily pipeline)
python -m app.extract.run

# 2. Serve the app
uvicorn app.main:app --reload --port 8000
```

Open **http://localhost:8000**.

- Markers are sized and colored by intensity (1–5) and cluster by zoom, so a wide date
  range stays responsive. Cluster bubbles are a heatmap of event density — blue (few) to
  red (many), with the count printed inside. Single events are drawn as small dots on the
  same ramp, so the whole map speaks one colour language.
- Change the **From / To** dates to see conflicts active in that window.
- Click a marker to see the event, its conflict, and the underlying news source.
- Use the side panel to **edit a conflict**, **edit or move an event** (including lat/lon
  via “Pick on map”), **add an event**, or **create a conflict**.
- The side panel lists only the conflicts with a located event in the current view, and
  shows the event count too ("134 of 1670 · 2,601 events"); pan or zoom to reach the
  rest. A newly created conflict opens in the detail panel even before it has events.
- Conflicts the news feed left without coordinates — about 500 in a 30-day window — are
  listed in a separate **No location** panel with a **Set location →** action that reuses
  "Pick on map". They are never auto-placed: a marker only appears where you put it. A
  conflict with no events at all stays out of that panel — it is empty, not unplaceable,
  and opens in the detail panel instead.

## Daily cron

```bash
crontab -e
# fetch + extract every day at 06:00
0 6 * * * /absolute/path/to/global-conflict-map/scripts/daily.sh
```

`scripts/daily.sh` runs the fetch→extract pipeline. `config/gdelt.yaml` controls the
source URL, lookback window, and zero-shot threshold.

## Docker

Serve the app and run the daily pipeline in containers (no host venv needed).

```bash
docker compose up -d --build   # build the image, start the web app
# open http://localhost:8000
```

- **Web app** binds to `127.0.0.1:8000` only — the app has no auth by design, so it is
  deliberately not reachable from the network.
- **State** lives in `./data/db/` (gitignored): `conflicts.db` plus the HuggingFace
  model cache. The first pipeline run downloads the ~570 MB zero-shot model there.
  The CI deploy puts it at `GCM_DATA_DIR=/var/lib/global-conflict-map/db` so the
  database survives checkouts (`docs/ci-cd.md`). `scripts/_data-dir.sh` is the single
  definition of that path: both `scripts/deploy.sh` and `scripts/docker-daily.sh`
  source it, so the served app and the daily pipeline always share one database.
  A bare `docker compose up` still uses `./data/db`.
- **Daily pipeline** is a one-shot service, not started by `up`:

  ```bash
  ./scripts/docker-daily.sh              # default lookback (config/gdelt.yaml)
  ./scripts/docker-daily.sh --days 7     # backfill

  Bare `docker compose run --rm pipeline` uses `./data/db`; the script shares
  `GCM_DATA_DIR` with the deployed web app, so use it whenever the stack is the
  deployed one.
  ```

  Schedule it with host cron (`0 6 * * * /absolute/path/to/scripts/docker-daily.sh`),
  or keep using the host `scripts/daily.sh` — either works.
- **Config** is bind-mounted read-only from `config/gdelt.yaml`; edit it and
  `docker compose restart web` to apply.
- **Existing host database?** The container starts with a fresh empty database. To
  carry over your current data, run the cutover script once; it copies with SQLite's
  backup API (WAL-safe), verifies integrity and row counts, and never deletes the
  original:

  ```bash
  ./scripts/cutover-data.sh                # dry run: source, counts, target
  ./scripts/cutover-data.sh --apply --owner "$USER"
  ```

  It targets `GCM_DATA_DIR` (the same path `deploy.sh` and `docker-daily.sh` use), not
  `./data/db`. Details in `docs/ci-cd.md`.

## Fetch raw data or backfill history

`scripts/fetch_gdelt.py` downloads raw `.export.CSV.zip` files without touching the DB.
It resumes safely: existing complete files are skipped, and failed stamps are listed in
`data/gdelt/fetch_failures.txt` for a re-run.

```bash
# Last 7 complete UTC days → data/gdelt/
python scripts/fetch_gdelt.py --days 7

# Explicit inclusive range
python scripts/fetch_gdelt.py --start 2026-10-29 --end 2026-11-04

# Optional: more parallel requests, or just print the plan
python scripts/fetch_gdelt.py --days 7 --workers 16
python scripts/fetch_gdelt.py --days 7 --dry-run
```

Then store the raw rows first (no extraction/filtering), and process them in a second pass:

```bash
# 1. Ingest raw GDELT rows into SQLite
python -m app.extract.run --start 2026-10-29 --end 2026-11-04 \
  --source-dir data/gdelt --raw-only

# 2. Process pending raw rows: adapter → zero-shot → conflict events
python -m app.extract.run --start 2026-10-29 --end 2026-11-04 \
  --source-dir data/gdelt
```

To process pending raw rows without fetching or creating new `ingestion_run` rows:

```bash
python scripts/process_raw.py
```

For data processed before run auditing existed, `scripts/backfill_audit.py` reconstructs
`ingestion_run` rows from the raw outcomes (idempotent per source day).

Without `--raw-only`, the same command does both phases in one pass. Raw rows live in
`raw_event` and are marked `persisted`, `duplicate`, `filtered_out`, or
`not_armed_conflict`. They are much larger than filtered events: roughly 125k rows and
~230 MB per day with indexes. `config/gdelt.yaml → raw_retention_days` prunes processed
rows after 30 days by default; set it to `0` to keep them forever.

If the zero-shot model is already cached but Hugging Face is slow/unreachable, force
offline loading:

```bash
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  python -m app.extract.run --start 2026-10-29 --end 2026-11-04 --source-dir data/gdelt
```

To start from a clean database, back it up first, then reset through Alembic:

```bash
cp conflicts.db /tmp/conflicts.db.bak
alembic downgrade base && alembic upgrade head
```

### Rebuilding the conflict grouping

Conflicts are derived from events by proximity, so a change to that rule leaves older
rows grouped the old way. `scripts/regroup.py` re-derives every conflict from the stored
events; it is a dry run unless you pass `--apply`:

```bash
cp conflicts.db conflicts.before-regroup.db
python scripts/regroup.py            # report: conflicts before -> after, largest groups
python scripts/regroup.py --apply
```

It rewrites `conflict` rows and each event's `conflict_id`, never coordinates — no marker
moves. Conflict ids restart from 1, so an old `?conflict=ID` link will point elsewhere.

## Seed demo data (optional)

To see the map immediately without hitting GDELT:

```bash
python scripts/seed.py
```

## Data source & filtering

- **Source:** GDELT 2.0 `.export.CSV.zip` files — free, no key, 15-minute granularity.
- **Filter pipeline:** `app/extract/` — root-code filter → field mapping → zero-shot
  gate (`cross-encoder/nli-deberta-v3-small`, threshold `0.7`).
- Measured on a labelled 25-article sample: **80% precision / 100% recall** (vs 32%
  precision before filtering). The two remaining false positives are conflict-adjacent
  stories (a UN complaint, a troop withdrawal).

## Architecture

`storage → ingestion → extraction → api → ui` — see `CAPABILITY-MAP.md` and `SPEC-*.md`.

Contributing with an AI agent? Read **`AGENTS.md`** first — it carries the commands,
conventions, boundaries, and the gotchas that cost real debugging time.

- `app/ingest/` — GDELT download + TSV parsing
- `app/extract/` — adapter + filter + grouping (`BaseSourceAdapter` is the swappable boundary)
- `app/api/` — FastAPI routes + Pydantic schemas
- `app/static/` — Leaflet frontend (no build step)

## Future: swap NLP → LLM

The extraction boundary is `app/extract/base.py: BaseSourceAdapter`. To use a T5 model
or an LLM later, add a new adapter implementing `to_event_draft(raw) -> EventDraft | None`
and select it in `app/extract/run.py`. No other module changes.

## Tests & evaluation

```bash
pytest                      # unit + integration tests
python scripts/evaluate.py  # precision/recall of the zero-shot filter (needs model)

# headless UI smoke test (needs Node 18+ and a server on :8000)
cd tests/ui && npm install && node map-smoke.mjs
```

Visual/CSS checks use the `chrome-devtools` MCP against a headless Chrome on `:9222` —
see `tests/ui/README.md` for the Chrome and MCP setup.

## CI/CD

Every push and pull request runs the same gates on a self-hosted runner on this host:
`ruff check`, `ruff format --check`, `shellcheck` on the shell scripts, `ty check`,
`pytest` (on 3.11 and 3.12), a fresh
`alembic upgrade head` plus drift check, an app-import check, an artifact guard, and a
docker build whose container must serve `/health` and answer a real API query. On
`main`, a green CI run deploys automatically: the image is rebuilt, the `web`
container replaced, `/health` plus `/api/conflicts` polled, and the previous image
restored if the new one never becomes ready.

Run the same gates locally before pushing:

```bash
./scripts/ci-check.sh            # lint, format, shellcheck, types, tests, migrations
./scripts/ci-check.sh --docker   # …plus the image build and import check
```

See `docs/ci-cd.md` for the pipeline design, runner setup, branch protection, and the
rollback procedure (`GCM_IMAGE_TAG=rollback docker compose up -d --no-deps --force-recreate web`).
