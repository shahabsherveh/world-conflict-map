# Global Conflict Map

A personal web app that turns the GDELT 2.0 news stream — ~57k geolocated events a day
— into a browsable, self-updating map of armed conflicts. A zero-shot semantic filter
separates real conflict events from noise, a proximity-based grouping algorithm links
events into conflicts, and a Leaflet map lets you scrub through time, zoom into
clusters, and edit the results by hand. Built personal-first but architected so it could
become a product without a rewrite.

## How it works

Every day, the pipeline follows the same four steps:

1. **Fetch** — download the latest GDELT 2.0 raw event files (free, no API key), each
   already coded as a geolocated event with an actor type and an intensity score.
2. **Filter** — keep only candidate conflict events (CAMEO root codes 18/19/20), then
   run a zero-shot semantic classifier to drop false positives like podcasts and plane
   crashes.
3. **Group** — link events into *conflicts* by geographic proximity (not keywords), so
   scattered news reports become one browsable conflict with a timeline.
4. **Serve** — store the results in SQLite and expose them through a FastAPI backend to
   a Leaflet map with time-scrubbing, clustering, and manual editing.

The whole thing runs on a schedule (cron or Docker), and a freshness check alerts you if
the map has stopped updating — because a pipeline that silently fails is worse than one
that visibly fails.

## Why I built this

I wanted to understand armed conflict as *data* — not as headlines, but as a stream of
geolocated events that could be filtered, grouped, and browsed over time. Existing tools
either show static maps or rely on curated, one-off reports; none let you watch the
underlying news stream turn into a map that updates itself.

So I built the pipeline end to end: ingest the raw feed, filter the signal from the
noise, group scattered reports into coherent conflicts, and make the result editable
where automation gets it wrong. Along the way it became an exercise in the unglamorous
parts of real software — dependency pinning, type checking, migration drift, and the
failure mode where a cron job keeps "succeeding" while the map quietly stops updating.

It's a personal tool first, but it's architected as if it might one day be a product.

## Requirements

- Python 3.12+
- Network access (for GDELT + the one-time model download)
- Docker (optional, for the container path) and Node 18+ (optional, for the jsdom UI smoke
  test; the real-browser tests need Node 22+)

## Setup

```bash
git clone https://github.com/OWNER/REPO.git global-conflict-map   # replace OWNER/REPO
cd global-conflict-map
python3 -m venv .venv
source .venv/bin/activate

# One command: requirements.lock pins every runtime dependency (with hashes) and
# carries the PyTorch CPU index, so torch resolves to the +cpu wheel, never the
# multi-GB CUDA build. Edit requirements.txt and run scripts/lock-deps.sh to
# change a dependency.
pip install -r requirements.lock

# Contributors only: the pinned pytest, ruff, ty, pymarkdown and pip-audit that
# ./scripts/ci-check.sh expects.
pip install -r requirements-ci.txt

alembic upgrade head
python scripts/download_model.py   # one-time, ~570 MB; can take 10+ min on slow links
```

The pipeline still runs if the model download fails: it prints a warning and stores
unfiltered events.

## Run

```bash
# 1. Fetch + extract (the daily pipeline)
python -m app.extract.run

# 2. Serve the app
uvicorn app.main:app --reload --port 8000
```

Open **<http://localhost:8000>**.

> **The first full pipeline run is slow.** A recent day is ~57k raw rows and the
> zero-shot filter costs ~0.03 s/event — roughly 30 minutes per day, with output only
> after each day finishes. If you just want to see the map, run `python scripts/seed.py`
> first (instant, no network) and serve that; run the pipeline later.

- Markers are sized and colored by intensity (1–5) and cluster at every zoom, so a wide
  date range stays responsive. Cluster bubbles are a heatmap of event density — blue (few)
  to red (many), with the count printed inside. Single events are drawn as small dots on
  the same ramp, so the whole map speaks one colour language. Events that share a
  coordinate (hundreds can share one GDELT country centroid) stay in a bubble even at full
  zoom; click it to spiderfy them so each one is reachable.
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

A cron job that exits 0 while the map has stopped updating is the expensive failure
mode here (two data paths, one frozen map). Add the freshness check and let cron mail
you when no run has succeeded within `pipeline_stale_hours` (default 48):

```bash
crontab -e
# MAILTO applies to the whole crontab, so set it once at the top
MAILTO=you@example.com
0 6 * * * /absolute/path/to/global-conflict-map/scripts/daily.sh
0 8 * * * /absolute/path/to/global-conflict-map/scripts/check-pipeline.sh
```

`check-pipeline.sh` asks the running web app for `GET /api/pipeline-health` and exits
non-zero when the last successful ingestion run is too old (override the URL with
`GCM_HEALTH_URL`).

## Docker

Serve the app and run the daily pipeline in containers (no host venv needed).

```bash
docker compose up -d --build   # build the image, start the web app
# open http://localhost:8000
```

This starts the web app against an **empty database** — the map stays empty until you
populate it. Once `up` is healthy, run one of:

```bash
docker compose run --rm pipeline                    # real data (downloads the model on first run)
docker compose run --rm web python scripts/seed.py  # or instant demo data
```

Both use the same volume as the `web` container above (the local `./data` unless
`GCM_DATA_ROOT` is set). Do not run `python scripts/seed.py` on the host for the Docker
stack: the host script writes `./conflicts.db`, while the container reads
`/data/db/conflicts.db` (the `GCM_DATA_ROOT` volume).

- **Web app** binds to `127.0.0.1:8000` only — the app has no auth by design, so it is
  deliberately not reachable from the network.
- **State** lives under one host directory, mounted at `/data` in both services so the
  paths are identical inside and outside the container (`scripts/_data-dir.sh` defines
  all three, locally under `./data`, deployed under `/data`):
  - `GCM_DATA_ROOT` (`./data` / `/data`) — the mount root.
  - `GCM_DATA_DIR` (`$root/db`) — `conflicts.db` and its WAL files:
    `/data/db/conflicts.db`.
  - `GCM_HF_HOME` (`$root/hf-cache`) — the HuggingFace cache for the ~570 MB zero-shot
    model, and the value exported as `HF_HOME` (the Dockerfile's `HF_HOME` points at
    the same directory). Being a sibling of `db/` rather than a subdirectory keeps the
    database backup independent of the model cache.

  The `/data` defaults are what the CI deploy uses, so the database survives checkouts
  (`docs/ci-cd.md`). `scripts/deploy.sh` and `scripts/docker-daily.sh` both source that
  file, so the served app, the daily pipeline, and the host run always share one
  database and one model cache. A bare `docker compose up` (nothing set) uses `./data`.
- **Daily pipeline** is a one-shot service, not started by `up`. For the local stack
  above (data in `./data`):

  ```bash
  docker compose run --rm pipeline          # default lookback (config/gdelt.yaml)
  docker compose run --rm pipeline --days 7 # backfill
  ```

  For the deployed stack, use `./scripts/docker-daily.sh` instead: it sources
  `scripts/_data-dir.sh`, so its `GCM_DATA_ROOT` matches the deployed web app. A bare
  `docker compose run` falls back to `./data` when nothing is set, which is the wrong
  database once the stack is deployed.

  Schedule it with host cron (`0 6 * * * /absolute/path/to/scripts/docker-daily.sh`),
  or keep using the host `scripts/daily.sh` — either works. For a local cron, export
  `GCM_DATA_ROOT=./data` first so it matches the local stack.
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

  It targets `GCM_DATA_ROOT` (`./data` locally, `/data` deployed), so the database
  lands at `<root>/db/conflicts.db`, the same path the container reads. Details in
  `docs/ci-cd.md`.

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

Every run records *why* it did what it did, in columns rather than log lines, so the
answer survives the cron job's stdout:

```bash
# what happened, including failure reasons and degraded runs
curl -s 'http://localhost:8000/api/ingestion-runs?limit=5' | python3 -m json.tool
# is the map still updating?
curl -s http://localhost:8000/api/pipeline-health
```

- `status` is `running` | `success` | `failed`.
- `error` holds `ExcType: message` for a failure (truncated to 2000 chars).
- `phase` names a whole-invocation step — `retry_stranded_raw_days`, `group_events`,
  `prune_raw_events` — with `source_day: null`. Those rows are created `running` and
  settled in place, so a healthy step shows its duration and a crash shows `error`.
- `degraded_reason` is set when a run succeeded **without** the zero-shot filter —
  expected when the model is unavailable, but it means country-centroid coordinates were
  kept, so the map is clustered rather than precise — or when a `--source-dir` day was
  read from a partly corrupt cache. It is deliberately not `failed`: the events still
  land.

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

This writes the host database (`./conflicts.db` by default). For the Docker stack use
`docker compose run --rm web python scripts/seed.py` instead — a host seed does not
populate the container's `/data/db/conflicts.db`.

## Weekly briefing (Markdown)

Render a dated digest of recent activity straight from the database — no server, no
network, no writes:

```bash
python scripts/briefing.py --days 7                    # stdout, Markdown
python scripts/briefing.py --days 7 --issue 1 > issue-1.md
python scripts/briefing.py --days 7 --region UA        # one country
python scripts/briefing.py --days 7 --end 2026-11-04   # a past window
```

It lists the 10 busiest theatres with the three most recent sourced events each
(`--top 0` for everything, `--events-per-theatre N` for longer entries), ranks by
recency and then by outlets/articles rather than by the ordinal `confidence` score, and
omits any event without an `http(s)` source link. Output is deterministic for a fixed
database, so two issues can be diffed. On the real data a 7-day issue is ~96 lines.

Read it before publishing: the theatre titles come from GDELT place strings, so a
country-wide cluster can read as a city name (see "Known limitations" in `AGENTS.md`).
The publishing plan and engagement counts live in `tasks/demand-test.md`.

## Data source & filtering

- **Source:** GDELT 2.0 `.export.CSV.zip` files — free, no key, 15-minute granularity.
- **Filter pipeline:** `app/extract/` — root-code filter → field mapping → zero-shot
  gate (`cross-encoder/nli-deberta-v3-small`, threshold `0.7`).
- Measured on a labelled 25-article sample: **80% precision / 100% recall** (vs 32%
  precision before filtering). The two remaining false positives are conflict-adjacent
  stories (a UN complaint, a troop withdrawal).

## Architecture

`storage → ingestion → extraction → api → ui` — see `docs/CAPABILITY-MAP.md` and `docs/SPEC-*.md`.

Diagrams of those boundaries, the daily pipeline, the schema, the class structure, and the
request flow are in [`docs/diagrams/`](docs/diagrams/README.md).

For a plain-language explanation of what the pipeline does and what the data cannot tell
you (no code required), see [`docs/CASE-STUDY.md`](docs/CASE-STUDY.md).

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

# headless UI smoke test (needs Node 18+ and a server on :8000;
# a seeded DB is the fastest fixture — see tests/ui/README.md)
cd tests/ui && npm install && node map-smoke.mjs

# real-browser UI tests (needs Node 22+ and a running Chrome on :9222)
cd tests/ui && node browser-tests.mjs
```

Unfiltered GDELT events often share country-centroid coordinates, but clustering keeps
those events in a bubble at every zoom, so both harnesses run against the real DB. Spiderfy
needs a browser, so `browser-tests.mjs` owns the coincident-event check; a freshly seeded DB
is still the quickest fixture.

`browser-tests.mjs` covers what jsdom cannot — hit-testing, popup anchoring, computed
CSS, basemap tiles, Pick-on-map — by driving a headless Chrome on `:9222` over CDP. It
is read-only and uses no npm dependency. `tests/ui/README.md` has the Chrome install and
start commands, plus the `chrome-devtools` MCP setup for exploratory checks.

## CI/CD

Every push and pull request runs the same gates on a self-hosted runner on this host:
`ruff check`, `ruff format --check`, `shellcheck` on the shell scripts, `pymarkdown` on
the Markdown, `ty check`, `pytest`, a fresh
`alembic upgrade head` plus drift check, an app-import check, an artifact guard, and a
docker build whose container must serve `/health` and answer a real API query. On
`main`, a green CI run deploys automatically: the image is rebuilt, the `web`
container replaced, `/health` plus `/api/conflicts` polled, and the previous image
restored if the new one never becomes ready.

Run the same gates locally before pushing:

```bash
./scripts/ci-check.sh            # lint, format, shellcheck, markdown, types, tests, migrations
./scripts/ci-check.sh --docker   # …plus the image build and import check
```

Setup installs `requirements-ci.txt`; if you skipped that step, the gate stops at the
version check before running any tool.

First-time setup on the host: `scripts/install-runner.sh --url https://github.com/OWNER/REPO`
(pinned runner release, verified hash) and `scripts/cutover-data.sh --apply` for existing
data. See `docs/ci-cd.md` for the pipeline design, runner setup, branch protection, and the
rollback procedure (`GCM_IMAGE_TAG=rollback docker compose up -d --no-deps --force-recreate web`).
The host-only steps — daemon `dns`, the health and pipeline watchers, retention, pruning,
the `production` reviewers and the cutover — are in [`docs/host-runbook.md`](docs/host-runbook.md).
